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
from datetime import timedelta
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
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
    ahora_utc,
)
from app.notifications import enviar_alerta
from app.security import mfa, ratelimit, recovery
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

# Hash ficticio para igualar tiempos cuando el usuario no existe
_HASH_FICTICIO = hashear_password(secrets.token_urlsafe(24))


def _etapa_inicial(usuario: Usuario) -> tuple[str, str]:
    """Determina la etapa de la sesión tras validar la contraseña."""
    if usuario.debe_cambiar_password:
        return ETAPA_CAMBIO_PASSWORD, "/password/cambiar"
    if not usuario.mfa_habilitado:
        return ETAPA_MFA_ENROLAMIENTO, "/mfa/configurar"
    return ETAPA_MFA_PENDIENTE, "/mfa/verificar"


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


# ---------------------------------------------------------------------------
# Inicio de sesión (factor 1: contraseña)
# ---------------------------------------------------------------------------


@router.get("/login")
def login_form(request: Request):
    token = request.cookies.get(COOKIE_CSRF_LOGIN) or secrets.token_urlsafe(24)
    respuesta = render(request, "login.html", {"csrf_login": token})
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
    username = username.strip().lower()
    ip = request.client.host if request.client else "desconocida"

    cookie_csrf = request.cookies.get(COOKIE_CSRF_LOGIN, "")
    if not cookie_csrf or not hmac.compare_digest(csrf_token, cookie_csrf):
        return render(request, "login.html", {"error": "Sesión de formulario inválida; intente de nuevo.",
                                              "csrf_login": cookie_csrf}, status_code=403)

    if not ratelimit.permitir_intento(f"login:{ip}", db=db):
        audit.registrar(db, audit.LOGIN_TASA_EXCEDIDA, request=request, username=username, exito=False)
        return render(request, "login.html", {"error": "Demasiados intentos; espere unos minutos.",
                                              "csrf_login": cookie_csrf}, status_code=429)

    usuario = db.scalar(select(Usuario).where(func.lower(Usuario.username) == username))

    if usuario is None:
        verificar_password(_HASH_FICTICIO, password)  # tiempo constante
        audit.registrar(db, audit.LOGIN_FALLIDO, request=request, username=username,
                        detalle="Usuario inexistente.", exito=False)
        return render(request, "login.html", {"error": "Credenciales inválidas.",
                                              "csrf_login": cookie_csrf}, status_code=401)

    if usuario.esta_bloqueado():
        audit.registrar(db, audit.LOGIN_BLOQUEADO, request=request, usuario=usuario, exito=False)
        return render(request, "login.html", {"error": "Cuenta bloqueada temporalmente por intentos fallidos.",
                                              "csrf_login": cookie_csrf}, status_code=423)

    if not usuario.activo:
        audit.registrar(db, audit.LOGIN_FALLIDO, request=request, usuario=usuario,
                        detalle="Cuenta desactivada.", exito=False)
        return render(request, "login.html", {"error": "Credenciales inválidas.",
                                              "csrf_login": cookie_csrf}, status_code=401)

    if not verificar_password(usuario.password_hash, password):
        _registrar_fallo(db, request, usuario)
        audit.registrar(db, audit.LOGIN_FALLIDO, request=request, usuario=usuario, exito=False)
        return render(request, "login.html", {"error": "Credenciales inválidas.",
                                              "csrf_login": cookie_csrf}, status_code=401)

    # Contraseña correcta
    usuario.intentos_fallidos = 0
    usuario.bloqueado_hasta = None
    if necesita_rehash(usuario.password_hash):
        usuario.password_hash = hashear_password(password)

    etapa, destino = _etapa_inicial(usuario)
    _sesion, token = crear_sesion(
        db, usuario, etapa,
        direccion_ip=ip, agente_usuario=request.headers.get("user-agent", ""),
    )
    audit.registrar(db, audit.LOGIN_OK, request=request, usuario=usuario,
                    detalle=f"Primer factor correcto; etapa: {etapa}.")

    respuesta = RedirectResponse(destino, status_code=303)
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

    if not verificar_password(usuario.password_hash, password_actual):
        _registrar_fallo(db, request, usuario)
        if usuario.esta_bloqueado():
            revocar_sesion(sesion)
            respuesta = RedirectResponse("/login", status_code=303)
            borrar_cookie(respuesta)
            return respuesta
        return render(request, "password_cambiar.html",
                      {**ctx, "error": "La contraseña actual no es correcta."}, status_code=400)

    if password_nueva != password_confirmacion:
        return render(request, "password_cambiar.html",
                      {**ctx, "error": "La confirmación no coincide."}, status_code=400)
    if password_nueva == password_actual:
        return render(request, "password_cambiar.html",
                      {**ctx, "error": "La nueva contraseña debe ser distinta de la actual."}, status_code=400)
    errores = validar_politica(password_nueva, usuario.username)
    if errores:
        return render(request, "password_cambiar.html", {**ctx, "error": " ".join(errores)}, status_code=400)

    usuario.password_hash = hashear_password(password_nueva)
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
        destino = "/mfa/verificar" if usuario.mfa_habilitado else "/mfa/configurar"
    else:
        destino = "/?msg=Contraseña actualizada correctamente."
    respuesta = RedirectResponse(destino, status_code=303)
    configurar_cookie(respuesta, token)
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
    usuario = db.get(Usuario, sesion.usuario_id)
    assert usuario is not None
    if usuario.totp_secret_cifrado is None or usuario.mfa_habilitado:
        usuario.totp_secret_cifrado = cifrar(mfa.generar_secreto())
        usuario.mfa_habilitado = False
    secreto = descifrar(usuario.totp_secret_cifrado)
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
    usuario = db.get(Usuario, sesion.usuario_id)
    assert usuario is not None and usuario.totp_secret_cifrado is not None
    secreto = descifrar(usuario.totp_secret_cifrado)
    ctx = {"qr_data_uri": mfa.qr_svg_data_uri(secreto, usuario.username),
           "secreto": secreto, "csrf_token": sesion.csrf_token}

    if not hmac.compare_digest(csrf_token, sesion.csrf_token):
        return render(request, "mfa_configurar.html", {**ctx, "error": "Token CSRF inválido."}, status_code=403)

    if not mfa.verificar_codigo(secreto, codigo):
        audit.registrar(db, audit.MFA_FALLIDO, request=request, usuario=usuario,
                        detalle="Código de enrolamiento incorrecto.", exito=False)
        return render(request, "mfa_configurar.html",
                      {**ctx, "error": "Código incorrecto. Verifique su aplicación autenticadora."},
                      status_code=400)

    usuario.mfa_habilitado = True
    usuario.ultimo_otp_usado = codigo.strip()
    usuario.ultimo_acceso = ahora_utc()
    sesion.etapa = ETAPA_ACTIVA
    token = rotar_token(db, sesion)
    codigos_recuperacion = recovery.emitir_codigos(db, usuario)
    audit.registrar(db, audit.MFA_ENROLADO, request=request, usuario=usuario,
                    detalle=f"{len(codigos_recuperacion)} códigos de recuperación emitidos.")
    audit.registrar(db, audit.MFA_OK, request=request, usuario=usuario)

    # Los códigos de recuperación se muestran una única vez
    respuesta = render(request, "mfa_codigos.html", {
        "usuario_actual": usuario,
        "codigos": codigos_recuperacion,
        "csrf_token": sesion.csrf_token,
    })
    configurar_cookie(respuesta, token)
    return respuesta


@router.get("/mfa/verificar")
def mfa_verificar_form(
    request: Request,
    sesion: Annotated[SesionWeb, Depends(en_etapa(ETAPA_MFA_PENDIENTE))],
):
    return render(request, "mfa_verificar.html", {"csrf_token": sesion.csrf_token})


@router.post("/mfa/verificar")
def mfa_verificar(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    sesion: Annotated[SesionWeb, Depends(en_etapa(ETAPA_MFA_PENDIENTE))],
    codigo: Annotated[str, Form()] = "",
    csrf_token: Annotated[str, Form()] = "",
):
    usuario = db.get(Usuario, sesion.usuario_id)
    assert usuario is not None and usuario.totp_secret_cifrado is not None

    if not hmac.compare_digest(csrf_token, sesion.csrf_token):
        return render(request, "mfa_verificar.html",
                      {"csrf_token": sesion.csrf_token, "error": "Token CSRF inválido."}, status_code=403)

    codigo_limpio = codigo.strip().replace(" ", "")
    secreto = descifrar(usuario.totp_secret_cifrado)
    reutilizado = usuario.ultimo_otp_usado is not None and codigo_limpio == usuario.ultimo_otp_usado

    totp_valido = not reutilizado and mfa.verificar_codigo(secreto, codigo)
    recuperacion_usada = False
    if not totp_valido:
        # Alternativa: código de recuperación de un solo uso
        recuperacion_usada = recovery.consumir_codigo(db, usuario, codigo)

    if not totp_valido and not recuperacion_usada:
        _registrar_fallo(db, request, usuario)
        audit.registrar(db, audit.MFA_FALLIDO, request=request, usuario=usuario,
                        detalle="Código reutilizado." if reutilizado else "Código incorrecto.", exito=False)
        if usuario.esta_bloqueado():
            revocar_sesion(sesion)
            respuesta = RedirectResponse("/login", status_code=303)
            borrar_cookie(respuesta)
            return respuesta
        return render(request, "mfa_verificar.html",
                      {"csrf_token": sesion.csrf_token, "error": "Código incorrecto."}, status_code=401)

    usuario.intentos_fallidos = 0
    if totp_valido:
        usuario.ultimo_otp_usado = codigo_limpio
    usuario.ultimo_acceso = ahora_utc()
    sesion.etapa = ETAPA_ACTIVA
    token = rotar_token(db, sesion)

    if recuperacion_usada:
        restantes = recovery.codigos_restantes(db, usuario)
        audit.registrar(db, audit.MFA_RECUPERACION, request=request, usuario=usuario,
                        detalle=f"Quedan {restantes} código(s) de recuperación sin usar.")
        aviso = (f"Código de recuperación aceptado; le quedan {restantes}. "
                 "Si perdió su dispositivo, pida al administrador reiniciar su MFA.")
        destino = f"/?msg={quote(aviso)}"
    else:
        audit.registrar(db, audit.MFA_OK, request=request, usuario=usuario)
        destino = "/"

    respuesta = RedirectResponse(destino, status_code=303)
    configurar_cookie(respuesta, token)
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
    revocar_sesion(sesion)
    audit.registrar(db, audit.LOGOUT, request=request, usuario=usuario)
    respuesta = RedirectResponse("/login", status_code=303)
    borrar_cookie(respuesta)
    return respuesta
