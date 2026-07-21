"""Endpoints JSON de sesión, login, contraseña y MFA (`/api/web`).

Replican exactamente el flujo de ``app/routes/auth.py`` (rate limit por IP,
hash ficticio en tiempo constante, bloqueo de cuenta, rehash, etapas, doble
cookie CSRF en el login y auditoría), pero responden JSON ``{stage, next}`` y
fijan las cookies con los mismos helpers de ``app.security.sessions``.
"""

from __future__ import annotations

import hmac
import secrets
from datetime import timedelta
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.api_web.deps import (
    _sesion_de_cookie,
    en_etapa_json,
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
    SesionWeb,
    Usuario,
    ahora_utc,
)
from app.notifications import enviar_alerta
from app.rbac import PERMISOS, tiene_permiso
from app.security import mfa, ratelimit, recovery, recuperacion
from app.security.crypto import cifrar, descifrar
from app.security.passwords import hashear_password, necesita_rehash, validar_politica, verificar_password
from app.security.sessions import (
    borrar_cookie,
    configurar_cookie,
    crear_sesion,
    revocar_sesion,
    revocar_sesiones_de_usuario,
    rotar_token,
)

router = APIRouter()

COOKIE_CSRF_LOGIN = "passwd_csrf_login"
COOKIE_RECUPERACION = "passwd_recuperacion"  # noqa: S105 — nombre de cookie, no es un secreto

# Hash ficticio para igualar tiempos cuando el usuario no existe.
_HASH_FICTICIO = hashear_password(secrets.token_urlsafe(24))

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


def _etapa_inicial(usuario: Usuario) -> str:
    """Determina la etapa de la sesión tras validar la contraseña."""
    if usuario.debe_cambiar_password:
        return ETAPA_CAMBIO_PASSWORD
    if not usuario.mfa_habilitado:
        return ETAPA_MFA_ENROLAMIENTO
    return ETAPA_MFA_PENDIENTE


def _registrar_fallo(db: Session, request: Request, usuario: Usuario) -> None:
    """Suma un intento fallido y bloquea la cuenta al llegar al límite."""
    settings = get_settings()
    usuario.intentos_fallidos += 1
    if usuario.intentos_fallidos >= settings.max_failed_attempts:
        usuario.bloqueado_hasta = ahora_utc() + timedelta(minutes=settings.lockout_minutes)
        usuario.intentos_fallidos = 0
        revocar_sesiones_de_usuario(db, usuario.id)
        audit.registrar(
            db, audit.CUENTA_BLOQUEADA, request=request, usuario=usuario,
            detalle=f"Bloqueo automático por {settings.lockout_minutes} minutos.", exito=False,
        )
        ip = request.client.host if request.client else "desconocida"
        enviar_alerta(
            "Cuenta bloqueada",
            f"La cuenta «{usuario.username}» se bloqueó automáticamente por intentos "
            f"de acceso fallidos (IP de origen: {ip}).",
        )


def _error(detalle: str, status_code: int) -> HTTPException:
    return HTTPException(status_code=status_code, detail=detalle)


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
    """Estado de la sesión (siempre 200). No exige etapa activa."""
    sesion = _sesion_de_cookie(request, db)
    if sesion is None:
        return {"authenticated": False, "stage": None, "csrf_token": None}

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
    }


# ---------------------------------------------------------------------------
# Inicio de sesión (factor 1: contraseña)
# ---------------------------------------------------------------------------


@router.post("/login")
def login(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    cuerpo: CredencialesLogin,
):
    username = cuerpo.username.strip().lower()
    ip = request.client.host if request.client else "desconocida"

    cookie_csrf = request.cookies.get(COOKIE_CSRF_LOGIN, "")
    if not cookie_csrf or not hmac.compare_digest(cuerpo.csrf_login, cookie_csrf):
        raise _error("Sesión de formulario inválida; intente de nuevo.", 403)

    if not ratelimit.permitir_intento(f"login:{ip}", db=db):
        audit.registrar(db, audit.LOGIN_TASA_EXCEDIDA, request=request, username=username, exito=False)
        db.commit()
        raise _error("Demasiados intentos; espere unos minutos.", 429)

    usuario = db.scalar(select(Usuario).where(func.lower(Usuario.username) == username))

    if usuario is None:
        verificar_password(_HASH_FICTICIO, cuerpo.password)  # tiempo constante
        audit.registrar(db, audit.LOGIN_FALLIDO, request=request, username=username,
                        detalle="Usuario inexistente.", exito=False)
        db.commit()
        raise _error("Credenciales inválidas.", 401)

    if usuario.esta_bloqueado():
        audit.registrar(db, audit.LOGIN_BLOQUEADO, request=request, usuario=usuario, exito=False)
        db.commit()
        raise _error("Cuenta bloqueada temporalmente por intentos fallidos.", 423)

    if not usuario.activo:
        audit.registrar(db, audit.LOGIN_FALLIDO, request=request, usuario=usuario,
                        detalle="Cuenta desactivada.", exito=False)
        db.commit()
        raise _error("Credenciales inválidas.", 401)

    if not verificar_password(usuario.password_hash, cuerpo.password):
        _registrar_fallo(db, request, usuario)
        audit.registrar(db, audit.LOGIN_FALLIDO, request=request, usuario=usuario, exito=False)
        db.commit()
        raise _error("Credenciales inválidas.", 401)

    # Contraseña correcta
    usuario.intentos_fallidos = 0
    usuario.bloqueado_hasta = None
    if necesita_rehash(usuario.password_hash):
        usuario.password_hash = hashear_password(cuerpo.password)

    etapa = _etapa_inicial(usuario)
    _sesion, token = crear_sesion(
        db, usuario, etapa,
        direccion_ip=ip, agente_usuario=request.headers.get("user-agent", ""),
    )
    audit.registrar(db, audit.LOGIN_OK, request=request, usuario=usuario,
                    detalle=f"Primer factor correcto; etapa: {etapa}.")

    # Confirmar ANTES de responder: el frontend consulta /session de inmediato y
    # debe ver la sesión recién creada. El cleanup diferido de get_db (que corre
    # tras enviar la respuesta) provocaría una lectura-tras-escritura obsoleta en
    # MySQL (REPEATABLE READ); este commit explícito lo evita.
    db.commit()
    respuesta = JSONResponse({"stage": etapa, "next": _SIGUIENTE[etapa]})
    configurar_cookie(respuesta, token)
    respuesta.delete_cookie(COOKIE_CSRF_LOGIN, path="/")
    return respuesta


# ---------------------------------------------------------------------------
# Cambio de contraseña (forzado en el primer acceso o voluntario)
# ---------------------------------------------------------------------------


def _sesion_para_cambio(request: Request, db: Annotated[Session, Depends(get_db)]) -> SesionWeb:
    """Acepta sesiones en etapa de cambio forzado o ya activas (cambio voluntario)."""
    sesion = _sesion_de_cookie(request, db)
    if sesion is None or sesion.etapa not in (ETAPA_CAMBIO_PASSWORD, ETAPA_ACTIVA):
        raise HTTPException(status_code=401, detail="No autenticado")
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

    usuario = db.get(Usuario, sesion.usuario_id)
    assert usuario is not None
    forzado = sesion.etapa == ETAPA_CAMBIO_PASSWORD

    if not verificar_password(usuario.password_hash, cuerpo.password_actual):
        _registrar_fallo(db, request, usuario)
        if usuario.esta_bloqueado():
            revocar_sesion(sesion)
            db.commit()
            respuesta = JSONResponse(
                {"detail": "Cuenta bloqueada; vuelva a iniciar sesión.", "next": "/login"},
                status_code=423,
            )
            borrar_cookie(respuesta)
            return respuesta
        raise _error("La contraseña actual no es correcta.", 400)

    if cuerpo.password_nueva != cuerpo.password_confirmacion:
        raise _error("La confirmación no coincide.", 400)
    if cuerpo.password_nueva == cuerpo.password_actual:
        raise _error("La nueva contraseña debe ser distinta de la actual.", 400)
    errores = validar_politica(cuerpo.password_nueva, usuario.username)
    if errores:
        raise _error(" ".join(errores), 400)

    usuario.password_hash = hashear_password(cuerpo.password_nueva)
    usuario.debe_cambiar_password = False
    usuario.password_cambiada_en = ahora_utc()
    usuario.intentos_fallidos = 0

    # Se revocan las demás sesiones del usuario; la actual rota su token.
    otras = [s for s in db.scalars(select(SesionWeb).where(
        SesionWeb.usuario_id == usuario.id, SesionWeb.revocada_en.is_(None))).all() if s.id != sesion.id]
    for s in otras:
        revocar_sesion(s)
    token = rotar_token(db, sesion)
    audit.registrar(db, audit.PASSWORD_CAMBIADA, request=request, usuario=usuario)

    if forzado:
        sesion.etapa = ETAPA_MFA_PENDIENTE if usuario.mfa_habilitado else ETAPA_MFA_ENROLAMIENTO
        cuerpo_resp = {"stage": sesion.etapa, "next": _SIGUIENTE[sesion.etapa]}
    else:
        cuerpo_resp = {"ok": True, "next": "/"}
    # Confirmar antes de responder (ver nota en login): el siguiente paso del
    # flujo lee la etapa/el token recién rotados de inmediato.
    db.commit()
    respuesta = JSONResponse(cuerpo_resp)
    configurar_cookie(respuesta, token)
    return respuesta


# ---------------------------------------------------------------------------
# MFA: enrolamiento y verificación (factor 2: TOTP)
# ---------------------------------------------------------------------------


@router.get("/mfa/configurar")
def mfa_configurar_datos(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    sesion: Annotated[SesionWeb, Depends(en_etapa_json(ETAPA_MFA_ENROLAMIENTO))],
):
    usuario = db.get(Usuario, sesion.usuario_id)
    assert usuario is not None
    if usuario.totp_secret_cifrado is None or usuario.mfa_habilitado:
        usuario.totp_secret_cifrado = cifrar(mfa.generar_secreto())
        usuario.mfa_habilitado = False
    secreto = descifrar(usuario.totp_secret_cifrado)
    # Si se regeneró el secreto hay que confirmarlo antes de responder, pues el
    # POST de confirmación lo lee de la BD para validar el código TOTP.
    db.commit()
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
    usuario = db.get(Usuario, sesion.usuario_id)
    assert usuario is not None and usuario.totp_secret_cifrado is not None
    secreto = descifrar(usuario.totp_secret_cifrado)

    if not mfa.verificar_codigo(secreto, cuerpo.codigo):
        audit.registrar(db, audit.MFA_FALLIDO, request=request, usuario=usuario,
                        detalle="Código de enrolamiento incorrecto.", exito=False)
        db.commit()
        raise _error("Código incorrecto. Verifique su aplicación autenticadora.", 400)

    usuario.mfa_habilitado = True
    usuario.ultimo_otp_usado = cuerpo.codigo.strip()
    usuario.ultimo_acceso = ahora_utc()
    sesion.etapa = ETAPA_ACTIVA
    token = rotar_token(db, sesion)
    codigos_recuperacion = recovery.emitir_codigos(db, usuario)
    audit.registrar(db, audit.MFA_ENROLADO, request=request, usuario=usuario,
                    detalle=f"{len(codigos_recuperacion)} códigos de recuperación emitidos.")
    audit.registrar(db, audit.MFA_OK, request=request, usuario=usuario)

    # Confirmar antes de responder: el frontend consulta /session enseguida y
    # debe ver la sesión ya activa (ver nota en login).
    db.commit()
    # Los códigos de recuperación se entregan una única vez.
    respuesta = JSONResponse({"codigos_recuperacion": codigos_recuperacion},
                             headers={"Cache-Control": "no-store"})
    configurar_cookie(respuesta, token)
    return respuesta


@router.get("/mfa/verificar")
def mfa_verificar_estado(
    sesion: Annotated[SesionWeb, Depends(en_etapa_json(ETAPA_MFA_PENDIENTE))],
):
    return {"ok": True}


@router.post("/mfa/verificar")
def mfa_verificar(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    sesion: Annotated[SesionWeb, Depends(en_etapa_json(ETAPA_MFA_PENDIENTE))],
    cuerpo: CodigoMFA,
):
    _exigir_csrf(request, sesion)
    usuario = db.get(Usuario, sesion.usuario_id)
    assert usuario is not None and usuario.totp_secret_cifrado is not None

    codigo_limpio = cuerpo.codigo.strip().replace(" ", "")
    secreto = descifrar(usuario.totp_secret_cifrado)
    reutilizado = usuario.ultimo_otp_usado is not None and codigo_limpio == usuario.ultimo_otp_usado

    totp_valido = not reutilizado and mfa.verificar_codigo(secreto, cuerpo.codigo)
    recuperacion_usada = False
    if not totp_valido:
        recuperacion_usada = recovery.consumir_codigo(db, usuario, cuerpo.codigo)

    if not totp_valido and not recuperacion_usada:
        _registrar_fallo(db, request, usuario)
        audit.registrar(db, audit.MFA_FALLIDO, request=request, usuario=usuario,
                        detalle="Código reutilizado." if reutilizado else "Código incorrecto.", exito=False)
        if usuario.esta_bloqueado():
            revocar_sesion(sesion)
            db.commit()
            respuesta = JSONResponse(
                {"detail": "Cuenta bloqueada; vuelva a iniciar sesión.", "next": "/login"},
                status_code=423,
            )
            borrar_cookie(respuesta)
            return respuesta
        db.commit()
        raise _error("Código incorrecto.", 401)

    usuario.intentos_fallidos = 0
    if totp_valido:
        usuario.ultimo_otp_usado = codigo_limpio
    usuario.ultimo_acceso = ahora_utc()
    sesion.etapa = ETAPA_ACTIVA
    token = rotar_token(db, sesion)

    aviso = None
    if recuperacion_usada:
        restantes = recovery.codigos_restantes(db, usuario)
        audit.registrar(db, audit.MFA_RECUPERACION, request=request, usuario=usuario,
                        detalle=f"Quedan {restantes} código(s) de recuperación sin usar.")
        aviso = (f"Código de recuperación aceptado; le quedan {restantes}. "
                 "Si perdió su dispositivo, pida al administrador reiniciar su MFA.")
    else:
        audit.registrar(db, audit.MFA_OK, request=request, usuario=usuario)

    cuerpo_resp: dict = {"ok": True}
    if aviso is not None:
        cuerpo_resp["aviso"] = aviso
        # Compatibilidad con la web: el aviso se transporta vía query si se desea.
        cuerpo_resp["next"] = f"/?msg={quote(aviso)}"
    # Confirmar antes de responder: el frontend consulta /session a continuación.
    db.commit()
    respuesta = JSONResponse(cuerpo_resp)
    configurar_cookie(respuesta, token)
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
    ip = request.client.host if request.client else "desconocida"
    cookie_csrf = request.cookies.get(COOKIE_CSRF_LOGIN, "")
    if not cookie_csrf or not hmac.compare_digest(cuerpo.csrf_login, cookie_csrf):
        raise _error("Sesión de formulario inválida; intente de nuevo.", 403)

    if not ratelimit.permitir_intento(f"recuperar:{ip}", db=db):
        audit.registrar(db, audit.RECUPERACION_FALLIDA, request=request,
                        username=cuerpo.username.strip().lower(), detalle="Tasa excedida.", exito=False)
        db.commit()
        raise _error("Demasiados intentos; espere unos minutos.", 429)

    username = cuerpo.username.strip().lower()
    email = cuerpo.email.strip().lower()
    usuario = db.scalar(select(Usuario).where(func.lower(Usuario.username) == username))
    coincide = (
        usuario is not None
        and usuario.activo
        and usuario.mfa_habilitado
        and usuario.totp_secret_cifrado is not None
        and hmac.compare_digest(usuario.email.strip().lower(), email)
    )

    # Se crea SIEMPRE un desafío (real si la identidad coincide y la tasa por
    # usuario lo permite; señuelo sin usuario en caso contrario), con el mismo
    # trabajo de BD y la misma respuesta, de modo que ni el cuerpo ni la cookie
    # ni la latencia distingan si la cuenta existe (anti-enumeración).
    if coincide and ratelimit.permitir_intento(f"recuperar-user:{usuario.id}", db=db):
        token, csrf_desafio = recuperacion.crear_desafio(db, usuario.id)
        audit.registrar(db, audit.RECUPERACION_INICIADA, request=request, usuario=usuario,
                        detalle="Identidad verificada; desafío de recuperación emitido.")
    else:
        token, csrf_desafio = recuperacion.crear_desafio(db, None)
        audit.registrar(db, audit.RECUPERACION_FALLIDA, request=request,
                        usuario=usuario if coincide else None, username=username,
                        detalle="Tasa por usuario excedida." if coincide else "Identidad no coincide.",
                        exito=False)
    db.commit()
    respuesta = JSONResponse({"ok": True, "csrf": csrf_desafio})
    _cookie_recuperacion(respuesta, token)
    return respuesta


@router.post("/password/recuperar/verificar")
def recuperar_verificar(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    cuerpo: RecuperarVerificar,
):
    """Paso 2: valida el segundo factor (TOTP en vivo o código de recuperación)."""
    desafio = recuperacion.desafio_vigente(db, request.cookies.get(COOKIE_RECUPERACION))
    if desafio is None:
        raise _error("Solicitud de recuperación inválida o caducada. Reiníciela.", 400)
    enviado = request.headers.get("x-csrf-token", "")
    if not enviado or not hmac.compare_digest(enviado, desafio.csrf_token):
        raise _error("Token CSRF inválido o ausente.", 403)
    if desafio.verificado:
        return {"ok": True}  # idempotente: permite reintentar el paso de cambio

    if not ratelimit.permitir_intento(f"recuperar-verif:{desafio.usuario_id}", db=db):
        db.commit()
        raise _error("Demasiados intentos; espere unos minutos.", 429)

    # Un desafío señuelo (usuario_id nulo) o una cuenta ya inválida se tratan
    # EXACTAMENTE como un segundo factor incorrecto: mismo trabajo criptográfico
    # y misma respuesta que un código erróneo sobre una cuenta real, para no
    # reintroducir un oráculo de enumeración en este paso.
    usuario = db.get(Usuario, desafio.usuario_id) if desafio.usuario_id is not None else None
    recuperable = usuario is not None and usuario.activo and usuario.totp_secret_cifrado is not None
    codigo_limpio = cuerpo.codigo.strip().replace(" ", "")
    if recuperable:
        secreto = descifrar(usuario.totp_secret_cifrado)
        reutilizado = usuario.ultimo_otp_usado is not None and codigo_limpio == usuario.ultimo_otp_usado
        totp_valido = not reutilizado and mfa.verificar_codigo(secreto, cuerpo.codigo)
        codigo_recuperacion = recovery.consumir_codigo(db, usuario, cuerpo.codigo) if not totp_valido else False
    else:
        mfa.verificar_codigo(mfa.generar_secreto(), cuerpo.codigo)  # equipara el tiempo, nunca válido
        totp_valido = False
        codigo_recuperacion = False

    if not totp_valido and not codigo_recuperacion:
        agotado = recuperacion.registrar_fallo(db, desafio)
        audit.registrar(db, audit.RECUPERACION_FALLIDA, request=request, usuario=usuario,
                        detalle="Segundo factor incorrecto." + (" Desafío agotado." if agotado else ""),
                        exito=False)
        db.commit()
        if agotado:
            respuesta = JSONResponse(
                {"detail": "Demasiados códigos incorrectos; reinicie la recuperación.", "next": "/recuperar"},
                status_code=400,
            )
            _borrar_cookie_recuperacion(respuesta)
            return respuesta
        raise _error("Código incorrecto.", 401)

    if totp_valido:
        usuario.ultimo_otp_usado = codigo_limpio  # cierra reutilización del mismo TOTP
    recuperacion.marcar_verificado(db, desafio)
    audit.registrar(db, audit.RECUPERACION_VERIFICADA, request=request, usuario=usuario,
                    detalle="Código de recuperación usado." if codigo_recuperacion else "TOTP verificado.")
    db.commit()
    return {"ok": True}


@router.post("/password/recuperar/cambiar")
def recuperar_cambiar(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    cuerpo: RecuperarCambiar,
):
    """Paso 3: fija la nueva contraseña y revoca todas las sesiones del usuario."""
    desafio = recuperacion.desafio_vigente(db, request.cookies.get(COOKIE_RECUPERACION))
    if desafio is None or not desafio.verificado:
        raise _error("Solicitud de recuperación inválida o sin verificar. Reiníciela.", 400)
    enviado = request.headers.get("x-csrf-token", "")
    if not enviado or not hmac.compare_digest(enviado, desafio.csrf_token):
        raise _error("Token CSRF inválido o ausente.", 403)

    usuario = db.get(Usuario, desafio.usuario_id)
    if usuario is None or not usuario.activo:
        recuperacion.consumir(db, desafio)
        db.commit()
        raise _error("Solicitud de recuperación inválida. Reiníciela.", 400)

    if cuerpo.password_nueva != cuerpo.password_confirmacion:
        raise _error("La confirmación no coincide.", 400)
    errores = validar_politica(cuerpo.password_nueva, usuario.username)
    if errores:
        raise _error(" ".join(errores), 400)
    if verificar_password(usuario.password_hash, cuerpo.password_nueva):
        raise _error("La nueva contraseña debe ser distinta de la anterior.", 400)

    usuario.password_hash = hashear_password(cuerpo.password_nueva)
    usuario.debe_cambiar_password = False
    usuario.password_cambiada_en = ahora_utc()
    usuario.intentos_fallidos = 0
    usuario.bloqueado_hasta = None
    revocar_sesiones_de_usuario(db, usuario.id)
    recuperacion.consumir(db, desafio)
    audit.registrar(db, audit.RECUPERACION_COMPLETADA, request=request, usuario=usuario,
                    detalle="Contraseña restablecida por auto-recuperación.")
    ip = request.client.host if request.client else "desconocida"
    enviar_alerta(
        "Contraseña restablecida por auto-recuperación",
        f"La contraseña de «{usuario.username}» se restableció mediante el flujo de "
        f"auto-recuperación (IP de origen: {ip}). Si no fue usted, contacte al "
        f"administrador de inmediato.",
    )
    db.commit()
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
    revocar_sesion(sesion)
    audit.registrar(db, audit.LOGOUT, request=request, usuario=usuario)
    # Confirmar antes de responder: el frontend consulta /session tras el logout
    # y debe ver la sesión ya revocada.
    db.commit()
    respuesta = JSONResponse({"ok": True})
    borrar_cookie(respuesta)
    return respuesta
