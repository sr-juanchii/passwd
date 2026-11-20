"""Endpoints JSON de sesión, login, contraseña y MFA (`/api/web`).

Replican exactamente el flujo de ``app/routes/auth.py`` (rate limit por IP,
hash ficticio en tiempo constante, bloqueo de cuenta, rehash, etapas, doble
cookie CSRF en el login y auditoría), pero responden JSON ``{stage, next}`` y
fijan las cookies con los mismos helpers de ``app.security.sessions``.
"""

from __future__ import annotations

import hmac
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import avisos
from app.api_web.deps import (
    _sesion_de_cookie,
    en_etapa_json,
    no_autenticado,
    sesion_activa_json,
    usuario_actual_json,
    verificar_csrf_json,
)
from app.api_web.serializers import serializar_usuario
from app.config import get_settings
from app.database import get_db
from app.models import (
    ETAPA_ACTIVA,
    ETAPA_CAMBIO_PASSWORD,
    ETAPA_MFA_ENROLAMIENTO,
    ETAPA_MFA_PENDIENTE,
    MFA_CORREO,
    MFA_TOTP,
    SesionWeb,
    Usuario,
)
from app.rbac import PERMISOS, tiene_permiso
from app.security import mfa, recovery, recuperacion, segundo_factor
from app.security.sessions import (
    COOKIE_SESION,
    borrar_cookie,
    configurar_cookie,
    extender,
    plazos,
)
from app.servicios import autenticacion
from app.servicios.autenticacion import ErrorAutenticacion

router = APIRouter()

COOKIE_CSRF_LOGIN = "passwd_csrf_login"
COOKIE_RECUPERACION = "passwd_recuperacion"  # noqa: S105 — nombre de cookie, no es un secreto

# Mapa de etapa → ruta siguiente, idéntico al flujo de la web Jinja.
_SIGUIENTE = {
    ETAPA_CAMBIO_PASSWORD: "/password/cambiar",
    ETAPA_MFA_ENROLAMIENTO: "/mfa/configurar",
    ETAPA_MFA_PENDIENTE: "/mfa/verificar",
    ETAPA_ACTIVA: "/",
}


class CredencialesLogin(BaseModel):
    username: str = ""
    password: str = ""
    csrf_login: str = ""


class CambioPassword(BaseModel):
    password_actual: str = ""
    password_nueva: str = ""
    password_confirmacion: str = ""


class CodigoMFA(BaseModel):
    codigo: str = ""


class RecuperarIniciar(BaseModel):
    username: str = ""
    email: str = ""
    csrf_login: str = ""


class RecuperarVerificar(BaseModel):
    codigo: str = ""


class RecuperarCambiar(BaseModel):
    password_nueva: str = ""
    password_confirmacion: str = ""


def _error(detalle: str, status_code: int) -> HTTPException:
    return HTTPException(status_code=status_code, detail=detalle)


def _usuario_de(db: Session, sesion: SesionWeb) -> Usuario:
    """El titular de la sesión. La dependencia de etapa ya garantizó que existe."""
    usuario = db.get(Usuario, sesion.usuario_id)
    assert usuario is not None
    return usuario


def _respuesta_de_error(exc: ErrorAutenticacion):
    """Traduce el desenlace del servicio. Si la sesión se revocó, cae la cookie."""
    if not exc.revocar_sesion:
        raise _error(exc.mensaje, exc.codigo)
    respuesta = JSONResponse(
        {"detail": exc.mensaje, "next": exc.destino or "/login"}, status_code=exc.codigo,
    )
    borrar_cookie(respuesta)
    return respuesta


def _respuesta_enrolado(enrolado: autenticacion.EnrolamientoCompletado) -> JSONResponse:
    respuesta = JSONResponse(
        {"codigos_recuperacion": enrolado.codigos_recuperacion, "metodo": enrolado.metodo},
        headers={"Cache-Control": "no-store"},
    )
    configurar_cookie(respuesta, enrolado.token)
    return respuesta


# ---------------------------------------------------------------------------
# CSRF de login (doble cookie) y estado de sesión
# ---------------------------------------------------------------------------


def _exigir_csrf(request: Request, sesion: SesionWeb) -> None:
    """Valida el token CSRF por cabecera contra la sesión (etapas pre-activas)."""
    enviado = request.headers.get("x-csrf-token", "")
    if not enviado or not hmac.compare_digest(enviado, sesion.csrf_token):
        raise _error("Token CSRF inválido o ausente.", 403)


@router.get("/csrf")
def csrf_login(request: Request):
    """Emite (o reutiliza) el token de doble cookie para el formulario de login."""
    token = request.cookies.get(COOKIE_CSRF_LOGIN) or secrets.token_urlsafe(24)
    respuesta = JSONResponse({"csrf_login": token})
    respuesta.set_cookie(
        COOKIE_CSRF_LOGIN, token, httponly=True, samesite="strict",
        secure=get_settings().cookie_secure, max_age=3600, path="/",
    )
    return respuesta


@router.get("/session")
def estado_sesion(request: Request, db: Annotated[Session, Depends(get_db)]):
    """Estado de la sesión (siempre 200). No exige etapa activa.

    Es un sondeo: NO cuenta como actividad (no prolonga la sesión). Si la cookie
    ya no abre ninguna sesión, se borra para que el navegador no la conserve.
    """
    sesion = _sesion_de_cookie(request, db, tocar=False)
    if sesion is None:
        respuesta = JSONResponse({"authenticated": False, "stage": None, "csrf_token": None})
        if request.cookies.get(COOKIE_SESION):
            db.commit()  # persistir la revocación por vencimiento
            borrar_cookie(respuesta)
        return respuesta

    usuario = db.get(Usuario, sesion.usuario_id)
    if usuario is None or not usuario.activo:
        return {"authenticated": False, "stage": sesion.etapa, "csrf_token": sesion.csrf_token}

    if sesion.etapa != ETAPA_ACTIVA:
        return {
            "authenticated": False,
            "stage": sesion.etapa,
            "csrf_token": sesion.csrf_token,
            "next": _SIGUIENTE.get(sesion.etapa, "/"),
        }

    permisos = {clave: tiene_permiso(usuario.rol, clave) for clave in PERMISOS}
    return {
        "authenticated": True,
        "stage": sesion.etapa,
        "csrf_token": sesion.csrf_token,
        "usuario": serializar_usuario(usuario),
        "permisos": permisos,
        "sesion": plazos(sesion),
        "password_min_length": get_settings().password_min_length,
    }


@router.post("/session/extender", dependencies=[Depends(verificar_csrf_json)])
def extender_sesion(
    db: Annotated[Session, Depends(get_db)],
    sesion: Annotated[SesionWeb, Depends(sesion_activa_json)],
):
    """Renueva la ventana de inactividad a petición expresa del usuario (botón
    «Extender sesión» del aviso de expiración). La vida máxima no se prolonga."""
    extender(sesion)
    db.commit()
    return {"ok": True, "sesion": plazos(sesion)}


# ---------------------------------------------------------------------------
# Inicio de sesión (factor 1: contraseña)
# ---------------------------------------------------------------------------


@router.post("/login")
def login(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    cuerpo: CredencialesLogin,
):
    try:
        iniciada = autenticacion.iniciar_sesion(
            db, username=cuerpo.username, password=cuerpo.password,
            csrf_login=cuerpo.csrf_login,
            cookie_csrf=request.cookies.get(COOKIE_CSRF_LOGIN, ""),
            request=request,
        )
    except ErrorAutenticacion as exc:
        raise _error(exc.mensaje, exc.codigo) from exc

    respuesta = JSONResponse({"stage": iniciada.etapa, "next": _SIGUIENTE[iniciada.etapa]})
    configurar_cookie(respuesta, iniciada.token)
    respuesta.delete_cookie(COOKIE_CSRF_LOGIN, path="/")
    return respuesta


# ---------------------------------------------------------------------------
# Cambio de contraseña (forzado en el primer acceso o voluntario)
# ---------------------------------------------------------------------------


def _sesion_para_cambio(request: Request, db: Annotated[Session, Depends(get_db)]) -> SesionWeb:
    """Acepta sesiones en etapa de cambio forzado o ya activas (cambio voluntario)."""
    sesion = _sesion_de_cookie(request, db)
    if sesion is None or sesion.etapa not in (ETAPA_CAMBIO_PASSWORD, ETAPA_ACTIVA):
        raise no_autenticado(request, db, sesion)
    usuario = db.get(Usuario, sesion.usuario_id)
    if usuario is None or not usuario.activo:
        raise HTTPException(status_code=401, detail="No autenticado")
    request.state.sesion = sesion
    return sesion


@router.post("/password/cambiar")
def cambiar_password(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    sesion: Annotated[SesionWeb, Depends(_sesion_para_cambio)],
    cuerpo: CambioPassword,
):
    # CSRF por cabecera (la sesión ya existe en etapa de cambio o activa).
    enviado = request.headers.get("x-csrf-token", "")
    if not enviado or not hmac.compare_digest(enviado, sesion.csrf_token):
        raise _error("Token CSRF inválido o ausente.", 403)

    try:
        cambiada = autenticacion.cambiar_password(
            db, sesion=sesion, actual=cuerpo.password_actual, nueva=cuerpo.password_nueva,
            confirmacion=cuerpo.password_confirmacion, request=request,
        )
    except ErrorAutenticacion as exc:
        if exc.revocar_sesion:
            respuesta = JSONResponse(
                {"detail": exc.mensaje, "next": exc.destino or "/login"}, status_code=exc.codigo,
            )
            borrar_cookie(respuesta)
            return respuesta
        raise _error(exc.mensaje, exc.codigo) from exc

    if cambiada.forzado:
        cuerpo_resp: dict = {"stage": cambiada.etapa, "next": _SIGUIENTE[cambiada.etapa]}
    else:
        cuerpo_resp = {"ok": True, "next": "/"}
    respuesta = JSONResponse(cuerpo_resp)
    configurar_cookie(respuesta, cambiada.token)
    return respuesta


# ---------------------------------------------------------------------------
# MFA: enrolamiento y verificación (factor 2: TOTP)
# ---------------------------------------------------------------------------


@router.get("/mfa/configurar/metodos")
def mfa_configurar_metodos(
    db: Annotated[Session, Depends(get_db)],
    sesion: Annotated[SesionWeb, Depends(en_etapa_json(ETAPA_MFA_ENROLAMIENTO))],
):
    """Métodos entre los que el usuario puede elegir su segundo factor."""
    return autenticacion.metodos_de_enrolamiento(db, _usuario_de(db, sesion))


@router.get("/mfa/configurar")
def mfa_configurar_datos(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    sesion: Annotated[SesionWeb, Depends(en_etapa_json(ETAPA_MFA_ENROLAMIENTO))],
):
    usuario = _usuario_de(db, sesion)
    secreto = autenticacion.secreto_totp_para_enrolar(db, usuario)
    return {"qr_data_uri": mfa.qr_svg_data_uri(secreto, usuario.username), "secreto": secreto}


@router.post("/mfa/configurar")
def mfa_configurar(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    sesion: Annotated[SesionWeb, Depends(en_etapa_json(ETAPA_MFA_ENROLAMIENTO))],
    cuerpo: CodigoMFA,
):
    # El CSRF se valida en línea: esta etapa aún no es "activa", de modo que no
    # puede depender de ``verificar_csrf_json`` (que exige sesión activa).
    _exigir_csrf(request, sesion)
    try:
        enrolado = autenticacion.confirmar_enrolamiento_totp(
            db, sesion=sesion, usuario=_usuario_de(db, sesion),
            codigo=cuerpo.codigo, request=request,
        )
    except ErrorAutenticacion as exc:
        return _respuesta_de_error(exc)
    return _respuesta_enrolado(enrolado)


@router.post("/mfa/configurar/correo/enviar")
def mfa_configurar_correo_enviar(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    sesion: Annotated[SesionWeb, Depends(en_etapa_json(ETAPA_MFA_ENROLAMIENTO))],
):
    """Envía el código con el que el usuario confirma su buzón al elegir el
    correo como método principal de segundo factor."""
    _exigir_csrf(request, sesion)
    usuario = _usuario_de(db, sesion)
    if not segundo_factor.correo_principal_disponible(usuario):
        raise _error(segundo_factor.motivo_correo_no_disponible(usuario), 409)
    try:
        return autenticacion.enviar_codigo_correo(
            db, usuario=usuario, proposito="alta de método por correo", request=request,
        )
    except ErrorAutenticacion as exc:
        raise _error(exc.mensaje, exc.codigo) from exc


@router.post("/mfa/configurar/correo")
def mfa_configurar_correo(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    sesion: Annotated[SesionWeb, Depends(en_etapa_json(ETAPA_MFA_ENROLAMIENTO))],
    cuerpo: CodigoMFA,
):
    """Confirma el código recibido y activa el correo como método principal."""
    _exigir_csrf(request, sesion)
    try:
        enrolado = autenticacion.confirmar_enrolamiento_correo(
            db, sesion=sesion, usuario=_usuario_de(db, sesion),
            codigo=cuerpo.codigo, request=request,
        )
    except ErrorAutenticacion as exc:
        return _respuesta_de_error(exc)
    return _respuesta_enrolado(enrolado)


@router.get("/mfa/verificar")
def mfa_verificar_estado(
    sesion: Annotated[SesionWeb, Depends(en_etapa_json(ETAPA_MFA_PENDIENTE))],
):
    return {"ok": True}


@router.post("/mfa/otp-correo")
def mfa_solicitar_otp_correo(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    sesion: Annotated[SesionWeb, Depends(en_etapa_json(ETAPA_MFA_PENDIENTE))],
):
    """Envía un código al correo del usuario para completar el segundo factor.

    Para quien eligió el correo es su método principal; para quien usa TOTP es
    el respaldo (si está habilitado). Solo alcanzable desde ``mfa_pendiente``: la
    contraseña ya fue validada, así que NO es un punto de entrada por sí solo. El
    código se verifica después en ``POST /mfa/verificar``.
    """
    _exigir_csrf(request, sesion)
    usuario = _usuario_de(db, sesion)
    if not segundo_factor.correo_en_login(usuario):
        raise _error(
            "El código por correo no está disponible. Use un código de recuperación "
            "o pida al administrador que reinicie su verificación en dos pasos."
            if usuario.mfa_metodo == MFA_CORREO else
            "El código por correo no está disponible. Use su aplicación "
            "autenticadora o un código de recuperación.",
            409,
        )
    principal = usuario.mfa_metodo == MFA_CORREO
    try:
        return autenticacion.enviar_codigo_correo(
            db, usuario=usuario, request=request,
            proposito="método principal" if principal else "respaldo",
        )
    except ErrorAutenticacion as exc:
        raise _error(exc.mensaje, exc.codigo) from exc


@router.get("/mfa/metodos")
def mfa_metodos_disponibles(
    db: Annotated[Session, Depends(get_db)],
    sesion: Annotated[SesionWeb, Depends(en_etapa_json(ETAPA_MFA_PENDIENTE))],
):
    """Métodos de segundo factor disponibles, para que la interfaz los ofrezca.

    No revela nada que el titular de la sesión no sepa ya: la contraseña está
    validada y solo se indica qué vías tiene para completar el acceso.
    """
    usuario = _usuario_de(db, sesion)
    correo = segundo_factor.correo_en_login(usuario)
    return {
        "principal": usuario.mfa_metodo,
        "totp": usuario.mfa_metodo == MFA_TOTP,
        "codigos_recuperacion": recovery.codigos_restantes(db, usuario) > 0,
        "otp_correo": correo,
        "destino": avisos.enmascarar_correo(usuario.email) if correo else "",
    }


@router.post("/mfa/verificar")
def mfa_verificar(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    sesion: Annotated[SesionWeb, Depends(en_etapa_json(ETAPA_MFA_PENDIENTE))],
    cuerpo: CodigoMFA,
):
    _exigir_csrf(request, sesion)
    try:
        verificado = autenticacion.verificar_segundo_factor(
            db, sesion=sesion, usuario=_usuario_de(db, sesion),
            codigo=cuerpo.codigo, request=request,
        )
    except ErrorAutenticacion as exc:
        return _respuesta_de_error(exc)

    cuerpo_resp: dict = {"ok": True, "stage": verificado.etapa}
    cuerpo_resp["next"] = ("/" if verificado.etapa == ETAPA_ACTIVA
                           else _SIGUIENTE[verificado.etapa])
    if verificado.aviso is not None:
        cuerpo_resp["aviso"] = verificado.aviso
    respuesta = JSONResponse(cuerpo_resp)
    configurar_cookie(respuesta, verificado.token)
    return respuesta


# ---------------------------------------------------------------------------
# Auto-recuperación de contraseña (usuario + email → 2.º factor → nueva clave)
# ---------------------------------------------------------------------------


def _cookie_recuperacion(respuesta: JSONResponse, token: str) -> None:
    respuesta.set_cookie(
        COOKIE_RECUPERACION, token, httponly=True, samesite="strict",
        secure=get_settings().cookie_secure, max_age=recuperacion.TTL_MINUTOS * 60, path="/",
    )


def _borrar_cookie_recuperacion(respuesta: JSONResponse) -> None:
    respuesta.delete_cookie(COOKIE_RECUPERACION, path="/")


@router.post("/password/recuperar/iniciar")
def recuperar_iniciar(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    cuerpo: RecuperarIniciar,
):
    """Paso 1: identifica la cuenta (usuario + email) y emite un desafío.

    Respuesta *anti-enumeración*: SIEMPRE devuelve ``{ok, csrf}`` y fija una
    cookie de desafío, exista o no la cuenta. Solo hay un desafío real (con
    fila en BD) cuando usuario y email coinciden y la cuenta tiene MFA activo;
    en caso contrario la cookie lleva un token aleatorio sin respaldo, de modo
    que el atacante no puede distinguir ambos casos por la respuesta.
    """
    try:
        desafio = autenticacion.recuperacion_iniciar(
            db, username=cuerpo.username, email=cuerpo.email, csrf_login=cuerpo.csrf_login,
            cookie_csrf=request.cookies.get(COOKIE_CSRF_LOGIN, ""), request=request,
        )
    except ErrorAutenticacion as exc:
        raise _error(exc.mensaje, exc.codigo) from exc
    respuesta = JSONResponse({"ok": True, "csrf": desafio.csrf})
    _cookie_recuperacion(respuesta, desafio.token)
    return respuesta


@router.post("/password/recuperar/verificar")
def recuperar_verificar(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    cuerpo: RecuperarVerificar,
):
    """Paso 2: valida el segundo factor (TOTP en vivo o código de recuperación)."""
    try:
        autenticacion.recuperacion_verificar(
            db, token_desafio=request.cookies.get(COOKIE_RECUPERACION),
            csrf_enviado=request.headers.get("x-csrf-token", ""),
            codigo=cuerpo.codigo, request=request,
        )
    except ErrorAutenticacion as exc:
        if exc.revocar_sesion:  # desafío agotado: se retira la cookie
            respuesta = JSONResponse(
                {"detail": exc.mensaje, "next": exc.destino or "/recuperar"},
                status_code=exc.codigo,
            )
            _borrar_cookie_recuperacion(respuesta)
            return respuesta
        raise _error(exc.mensaje, exc.codigo) from exc
    return {"ok": True}


@router.post("/password/recuperar/cambiar")
def recuperar_cambiar(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    cuerpo: RecuperarCambiar,
):
    """Paso 3: fija la nueva contraseña y revoca todas las sesiones del usuario."""
    try:
        autenticacion.recuperacion_cambiar(
            db, token_desafio=request.cookies.get(COOKIE_RECUPERACION),
            csrf_enviado=request.headers.get("x-csrf-token", ""),
            nueva=cuerpo.password_nueva, confirmacion=cuerpo.password_confirmacion,
            request=request,
        )
    except ErrorAutenticacion as exc:
        raise _error(exc.mensaje, exc.codigo) from exc
    respuesta = JSONResponse({"ok": True, "next": "/login"})
    _borrar_cookie_recuperacion(respuesta)
    return respuesta


# ---------------------------------------------------------------------------
# Cierre de sesión
# ---------------------------------------------------------------------------


@router.post("/logout", dependencies=[Depends(verificar_csrf_json)])
def logout(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    sesion: Annotated[SesionWeb, Depends(sesion_activa_json)],
    usuario: Annotated[Usuario, Depends(usuario_actual_json)],
):
    # El servicio confirma antes de devolver: el frontend consulta /session tras
    # el logout y debe ver la sesión ya revocada.
    autenticacion.cerrar_sesion(db, sesion=sesion, usuario=usuario, request=request)
    respuesta = JSONResponse({"ok": True})
    borrar_cookie(respuesta)
    return respuesta
