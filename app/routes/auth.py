"""Flujo de autenticación: contraseña → (cambio forzado) → MFA TOTP → sesión.

Controles aplicados:
- Bloqueo de cuenta tras intentos fallidos y limitación de tasa por IP.
- Mensajes genéricos para impedir enumeración de usuarios.
- MFA obligatorio: ninguna sesión llega a la etapa activa sin TOTP válido.
- Rotación de token de sesión en cada elevación de privilegio.
- Anti-CSRF: doble cookie en el login y token de sesión en el resto.
"""

from __future__ import annotations

import hmac
import secrets
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.deps import (
    RedirigirLogin,
    _sesion_de_cookie,
    en_etapa,
    render,
    sesion_activa,
    usuario_actual,
    verificar_csrf,
)
from app.models import (
    ETAPA_ACTIVA,
    ETAPA_CAMBIO_PASSWORD,
    ETAPA_MFA_ENROLAMIENTO,
    ETAPA_MFA_PENDIENTE,
    SesionWeb,
    Usuario,
)
from app.security import mfa, recuperacion, segundo_factor
from app.security.crypto import descifrar
from app.security.sessions import (
    borrar_cookie,
    configurar_cookie,
)
from app.servicios import autenticacion
from app.servicios.autenticacion import ErrorAutenticacion

router = APIRouter()

COOKIE_CSRF_LOGIN = "passwd_csrf_login"
COOKIE_RECUPERACION = "passwd_recuperacion"  # noqa: S105 — nombre de cookie, no es un secreto


def _cookie_recuperacion(respuesta, token: str) -> None:
    respuesta.set_cookie(
        COOKIE_RECUPERACION, token, httponly=True, samesite="strict",
        secure=get_settings().cookie_secure, max_age=recuperacion.TTL_MINUTOS * 60, path="/",
    )


# Etapa de la sesión → a dónde lleva en ESTA interfaz. El servicio devuelve solo
# la etapa; la URL es presentación, y la API JSON tiene su propio mapa.
_DESTINO_ETAPA = {
    ETAPA_CAMBIO_PASSWORD: "/password/cambiar",
    ETAPA_MFA_ENROLAMIENTO: "/mfa/configurar",
    ETAPA_MFA_PENDIENTE: "/mfa/verificar",
}


def _usuario_de(db: Session, sesion: SesionWeb) -> Usuario:
    """El titular de la sesión. La dependencia de etapa ya garantizó que existe."""
    usuario = db.get(Usuario, sesion.usuario_id)
    assert usuario is not None
    return usuario


# ---------------------------------------------------------------------------
# Inicio de sesión (factor 1: contraseña)
# ---------------------------------------------------------------------------


@router.get("/login")
def login_form(request: Request):
    token = request.cookies.get(COOKIE_CSRF_LOGIN) or secrets.token_urlsafe(24)
    aviso = request.query_params.get("msg", "")[:200]
    respuesta = render(request, "login.html", {"csrf_login": token, "aviso": aviso})
    respuesta.set_cookie(
        COOKIE_CSRF_LOGIN, token, httponly=True, samesite="strict",
        secure=get_settings().cookie_secure, max_age=3600, path="/",
    )
    return respuesta


@router.post("/login")
def login(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    username: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
):
    cookie_csrf = request.cookies.get(COOKIE_CSRF_LOGIN, "")
    try:
        iniciada = autenticacion.iniciar_sesion(
            db, username=username, password=password, csrf_login=csrf_token,
            cookie_csrf=cookie_csrf, request=request,
        )
    except ErrorAutenticacion as exc:
        # Esta interfaz cuenta el fallo volviendo al formulario con su mensaje,
        # conservando el código HTTP que el servicio determinó.
        return render(request, "login.html",
                      {"error": exc.mensaje, "csrf_login": cookie_csrf},
                      status_code=exc.codigo)

    respuesta = RedirectResponse(_DESTINO_ETAPA[iniciada.etapa], status_code=303)
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
        raise RedirigirLogin()
    usuario = db.get(Usuario, sesion.usuario_id)
    if usuario is None or not usuario.activo:
        raise RedirigirLogin()
    return sesion


@router.get("/password/cambiar")
def cambiar_password_form(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    sesion: Annotated[SesionWeb, Depends(_sesion_para_cambio)],
):
    usuario = db.get(Usuario, sesion.usuario_id)
    return render(request, "password_cambiar.html", {
        "usuario_actual": usuario if sesion.etapa == ETAPA_ACTIVA else None,
        "forzado": sesion.etapa == ETAPA_CAMBIO_PASSWORD,
        "csrf_token": sesion.csrf_token,
    })


@router.post("/password/cambiar")
def cambiar_password(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    sesion: Annotated[SesionWeb, Depends(_sesion_para_cambio)],
    password_actual: Annotated[str, Form()] = "",
    password_nueva: Annotated[str, Form()] = "",
    password_confirmacion: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
):
    usuario = db.get(Usuario, sesion.usuario_id)
    assert usuario is not None
    forzado = sesion.etapa == ETAPA_CAMBIO_PASSWORD
    ctx = {"usuario_actual": usuario if not forzado else None, "forzado": forzado, "csrf_token": sesion.csrf_token}

    if not hmac.compare_digest(csrf_token, sesion.csrf_token):
        return render(request, "password_cambiar.html", {**ctx, "error": "Token CSRF inválido."}, status_code=403)

    try:
        cambiada = autenticacion.cambiar_password(
            db, sesion=sesion, actual=password_actual, nueva=password_nueva,
            confirmacion=password_confirmacion, request=request,
        )
    except ErrorAutenticacion as exc:
        if exc.revocar_sesion:
            # La cuenta se bloqueó al fallar la contraseña actual: fuera.
            respuesta = RedirectResponse(exc.destino or "/login", status_code=303)
            borrar_cookie(respuesta)
            return respuesta
        return render(request, "password_cambiar.html",
                      {**ctx, "error": exc.mensaje}, status_code=exc.codigo)

    if cambiada.forzado:
        destino = _DESTINO_ETAPA[cambiada.etapa]
    else:
        destino = "/?msg=Contraseña actualizada correctamente."
    respuesta = RedirectResponse(destino, status_code=303)
    configurar_cookie(respuesta, cambiada.token)
    return respuesta


# ---------------------------------------------------------------------------
# MFA: enrolamiento y verificación (factor 2: TOTP)
# ---------------------------------------------------------------------------


@router.get("/mfa/configurar")
def mfa_configurar_form(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    sesion: Annotated[SesionWeb, Depends(en_etapa(ETAPA_MFA_ENROLAMIENTO))],
):
    usuario = _usuario_de(db, sesion)
    secreto = autenticacion.secreto_totp_para_enrolar(db, usuario)
    return render(request, "mfa_configurar.html", {
        "qr_data_uri": mfa.qr_svg_data_uri(secreto, usuario.username),
        "secreto": secreto,
        "csrf_token": sesion.csrf_token,
    })


@router.post("/mfa/configurar")
def mfa_configurar(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    sesion: Annotated[SesionWeb, Depends(en_etapa(ETAPA_MFA_ENROLAMIENTO))],
    codigo: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
):
    usuario = _usuario_de(db, sesion)
    assert usuario.totp_secret_cifrado is not None
    secreto = descifrar(usuario.totp_secret_cifrado)
    ctx = {"qr_data_uri": mfa.qr_svg_data_uri(secreto, usuario.username),
           "secreto": secreto, "csrf_token": sesion.csrf_token}

    if not hmac.compare_digest(csrf_token, sesion.csrf_token):
        return render(request, "mfa_configurar.html", {**ctx, "error": "Token CSRF inválido."}, status_code=403)

    # Esta interfaz solo enrola TOTP; el método por correo se elige en la nueva.
    try:
        enrolado = autenticacion.confirmar_enrolamiento_totp(
            db, sesion=sesion, usuario=usuario, codigo=codigo, request=request,
        )
    except ErrorAutenticacion as exc:
        if exc.revocar_sesion:
            respuesta = RedirectResponse(exc.destino or "/login", status_code=303)
            borrar_cookie(respuesta)
            return respuesta
        return render(request, "mfa_configurar.html",
                      {**ctx, "error": exc.mensaje}, status_code=exc.codigo)

    # Los códigos de recuperación se muestran una única vez
    respuesta = render(request, "mfa_codigos.html", {
        "usuario_actual": enrolado.usuario,
        "codigos": enrolado.codigos_recuperacion,
        "csrf_token": sesion.csrf_token,
    })
    configurar_cookie(respuesta, enrolado.token)
    return respuesta


@router.get("/mfa/verificar")
def mfa_verificar_form(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    sesion: Annotated[SesionWeb, Depends(en_etapa(ETAPA_MFA_PENDIENTE))],
):
    usuario = db.get(Usuario, sesion.usuario_id)
    assert usuario is not None
    return render(request, "mfa_verificar.html", {
        "csrf_token": sesion.csrf_token,
        "otp_correo_disponible": segundo_factor.correo_en_login(usuario),
        "aviso": request.query_params.get("msg", "")[:200],
    })


@router.post("/mfa/otp-correo")
def mfa_solicitar_otp_correo(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    sesion: Annotated[SesionWeb, Depends(en_etapa(ETAPA_MFA_PENDIENTE))],
    csrf_token: Annotated[str, Form()] = "",
):
    """Envía un OTP de respaldo al correo del usuario (MFA sin dispositivo TOTP).

    Solo alcanzable desde ``mfa_pendiente``: la contraseña ya fue validada, así
    que no es un punto de entrada por sí solo. El código se verifica luego en
    ``POST /mfa/verificar``, igual que un TOTP.
    """
    usuario = _usuario_de(db, sesion)
    contexto = {"csrf_token": sesion.csrf_token,
                "otp_correo_disponible": segundo_factor.correo_en_login(usuario)}
    if not hmac.compare_digest(csrf_token, sesion.csrf_token):
        return render(request, "mfa_verificar.html",
                      {**contexto, "error": "Token CSRF inválido."}, status_code=403)
    if not segundo_factor.correo_en_login(usuario):
        return render(request, "mfa_verificar.html", {
            **contexto,
            "error": "El código por correo no está disponible. Use su aplicación "
                     "autenticadora o un código de recuperación.",
        }, status_code=409)

    try:
        autenticacion.enviar_codigo_correo(
            db, usuario=usuario, proposito="respaldo", request=request,
        )
    except ErrorAutenticacion as exc:
        return render(request, "mfa_verificar.html",
                      {**contexto, "error": exc.mensaje}, status_code=exc.codigo)

    minutos = get_settings().email_otp_ttl_minutes
    return render(request, "mfa_verificar.html", {
        **contexto,
        "aviso": f"Le enviamos un código a su correo registrado. Caduca en {minutos} minutos.",
    })


@router.post("/mfa/verificar")
def mfa_verificar(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    sesion: Annotated[SesionWeb, Depends(en_etapa(ETAPA_MFA_PENDIENTE))],
    codigo: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
):
    usuario = _usuario_de(db, sesion)

    if not hmac.compare_digest(csrf_token, sesion.csrf_token):
        return render(request, "mfa_verificar.html",
                      {"csrf_token": sesion.csrf_token, "error": "Token CSRF inválido."}, status_code=403)

    try:
        verificado = autenticacion.verificar_segundo_factor(
            db, sesion=sesion, usuario=usuario, codigo=codigo, request=request,
        )
    except ErrorAutenticacion as exc:
        if exc.revocar_sesion:
            # La cuenta se bloqueó con este intento: fuera y a empezar.
            respuesta = RedirectResponse("/login", status_code=303)
            borrar_cookie(respuesta)
            return respuesta
        return render(request, "mfa_verificar.html",
                      {"csrf_token": sesion.csrf_token, "error": exc.mensaje},
                      status_code=exc.codigo)

    if verificado.etapa == ETAPA_MFA_ENROLAMIENTO:
        destino = "/mfa/configurar"
    elif verificado.aviso:
        destino = f"/?msg={quote(verificado.aviso)}"
    else:
        destino = "/"
    respuesta = RedirectResponse(destino, status_code=303)
    configurar_cookie(respuesta, verificado.token)
    return respuesta


# ---------------------------------------------------------------------------
# Auto-recuperación de contraseña (usuario + email → 2.º factor → nueva clave)
# ---------------------------------------------------------------------------


@router.get("/recuperar")
def recuperar_form(request: Request):
    token = request.cookies.get(COOKIE_CSRF_LOGIN) or secrets.token_urlsafe(24)
    respuesta = render(request, "recuperar_identidad.html", {"csrf_login": token})
    respuesta.set_cookie(
        COOKIE_CSRF_LOGIN, token, httponly=True, samesite="strict",
        secure=get_settings().cookie_secure, max_age=3600, path="/",
    )
    return respuesta


@router.post("/recuperar")
def recuperar_iniciar(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    username: Annotated[str, Form()] = "",
    email: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
):
    cookie_csrf = request.cookies.get(COOKIE_CSRF_LOGIN, "")
    try:
        desafio = autenticacion.recuperacion_iniciar(
            db, username=username, email=email, csrf_login=csrf_token,
            cookie_csrf=cookie_csrf, request=request,
        )
    except ErrorAutenticacion as exc:
        return render(request, "recuperar_identidad.html",
                      {"error": exc.mensaje, "csrf_login": cookie_csrf},
                      status_code=exc.codigo)

    # PRG + anti-enumeración: SIEMPRE se redirige al paso 2 con cookie de
    # desafío, exista o no la cuenta.
    respuesta = RedirectResponse("/recuperar/verificar", status_code=303)
    _cookie_recuperacion(respuesta, desafio.token)
    return respuesta


@router.get("/recuperar/verificar")
def recuperar_verificar_form(request: Request, db: Annotated[Session, Depends(get_db)]):
    desafio = recuperacion.desafio_vigente(db, request.cookies.get(COOKIE_RECUPERACION))
    if desafio is None:
        return RedirectResponse("/recuperar", status_code=303)
    return render(request, "recuperar_verificar.html", {"csrf_token": desafio.csrf_token})


@router.post("/recuperar/verificar")
def recuperar_verificar(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    codigo: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
):
    # El CSRF de este paso viaja en el formulario y se compara contra el del
    # desafío, no contra una sesión: aquí todavía no hay sesión.
    desafio = recuperacion.desafio_vigente(db, request.cookies.get(COOKIE_RECUPERACION))
    if desafio is None:
        return RedirectResponse("/recuperar", status_code=303)
    if desafio.verificado:
        return RedirectResponse("/recuperar/cambiar", status_code=303)

    try:
        autenticacion.recuperacion_verificar(
            db, token_desafio=request.cookies.get(COOKIE_RECUPERACION),
            csrf_enviado=csrf_token, codigo=codigo, request=request,
        )
    except ErrorAutenticacion as exc:
        if exc.revocar_sesion:  # desafío agotado
            respuesta = RedirectResponse("/recuperar", status_code=303)
            respuesta.delete_cookie(COOKIE_RECUPERACION, path="/")
            return respuesta
        return render(request, "recuperar_verificar.html",
                      {"csrf_token": desafio.csrf_token, "error": exc.mensaje},
                      status_code=exc.codigo)
    return RedirectResponse("/recuperar/cambiar", status_code=303)


@router.get("/recuperar/cambiar")
def recuperar_cambiar_form(request: Request, db: Annotated[Session, Depends(get_db)]):
    desafio = recuperacion.desafio_vigente(db, request.cookies.get(COOKIE_RECUPERACION))
    if desafio is None or not desafio.verificado:
        return RedirectResponse("/recuperar", status_code=303)
    return render(request, "recuperar_cambiar.html", {"csrf_token": desafio.csrf_token})


@router.post("/recuperar/cambiar")
def recuperar_cambiar(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    password_nueva: Annotated[str, Form()] = "",
    password_confirmacion: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
):
    desafio = recuperacion.desafio_vigente(db, request.cookies.get(COOKIE_RECUPERACION))
    if desafio is None or not desafio.verificado:
        return RedirectResponse("/recuperar", status_code=303)
    ctx = {"csrf_token": desafio.csrf_token}

    try:
        autenticacion.recuperacion_cambiar(
            db, token_desafio=request.cookies.get(COOKIE_RECUPERACION),
            csrf_enviado=csrf_token, nueva=password_nueva,
            confirmacion=password_confirmacion, request=request,
        )
    except ErrorAutenticacion as exc:
        if exc.codigo == 400 and "Reiníciela" in exc.mensaje:
            # El desafío dejó de ser utilizable: vuelta al principio.
            return RedirectResponse("/recuperar", status_code=303)
        return render(request, "recuperar_cambiar.html",
                      {**ctx, "error": exc.mensaje}, status_code=exc.codigo)

    aviso = "Contraseña restablecida. Inicie sesión con su nueva contraseña."
    respuesta = RedirectResponse(f"/login?msg={quote(aviso)}", status_code=303)
    respuesta.delete_cookie(COOKIE_RECUPERACION, path="/")
    return respuesta


# ---------------------------------------------------------------------------
# Cierre de sesión
# ---------------------------------------------------------------------------


@router.post("/logout", dependencies=[Depends(verificar_csrf)])
def logout(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    sesion: Annotated[SesionWeb, Depends(sesion_activa)],
    usuario: Annotated[Usuario, Depends(usuario_actual)],
):
    autenticacion.cerrar_sesion(db, sesion=sesion, usuario=usuario, request=request)
    respuesta = RedirectResponse("/login", status_code=303)
    borrar_cookie(respuesta)
    return respuesta
