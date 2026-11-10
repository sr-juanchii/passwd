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

from app import audit, avisos
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
    MFA_CORREO,
    MFA_TOTP,
    SesionWeb,
    Usuario,
    ahora_utc,
)
from app.notifications import enviar_a_direccion, enviar_alerta
from app.security import mfa, otp_correo, ratelimit, recovery, recuperacion, segundo_factor
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

# Hash ficticio para igualar tiempos cuando el usuario no existe
_HASH_FICTICIO = hashear_password(secrets.token_urlsafe(24))


def _cookie_recuperacion(respuesta, token: str) -> None:
    respuesta.set_cookie(
        COOKIE_RECUPERACION, token, httponly=True, samesite="strict",
        secure=get_settings().cookie_secure, max_age=recuperacion.TTL_MINUTOS * 60, path="/",
    )


def _etapa_inicial(usuario: Usuario) -> tuple[str, str]:
    """Determina la etapa de la sesión tras validar la contraseña."""
    if usuario.debe_cambiar_password:
        return ETAPA_CAMBIO_PASSWORD, "/password/cambiar"
    if not usuario.mfa_habilitado:
        return ETAPA_MFA_ENROLAMIENTO, "/mfa/configurar"
    return ETAPA_MFA_PENDIENTE, "/mfa/verificar"


def _ip_de(request: Request) -> str:
    return request.client.host if request.client else "desconocida"


def _avisar_inicio_sesion(db: Session, request: Request, usuario: Usuario) -> None:
    """Aviso al titular de que se abrió una sesión con su cuenta (mejor esfuerzo)."""
    avisos.aviso_inicio_sesion(
        db, usuario, _ip_de(request), request.headers.get("user-agent", "")
    )


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
    reenrolando = usuario.mfa_habilitado and usuario.mfa_metodo == MFA_CORREO
    if usuario.totp_secret_cifrado is None or (usuario.mfa_habilitado and not reenrolando):
        usuario.totp_secret_cifrado = cifrar(mfa.generar_secreto())
        if not reenrolando:
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

    valido, _reutilizado = segundo_factor.aceptar_totp(usuario, codigo)
    if not valido:
        audit.registrar(db, audit.MFA_FALLIDO, request=request, usuario=usuario,
                        detalle="Código de enrolamiento incorrecto.", exito=False)
        return render(request, "mfa_configurar.html",
                      {**ctx, "error": "Código incorrecto. Verifique su aplicación autenticadora."},
                      status_code=400)

    usuario.mfa_habilitado = True
    usuario.mfa_metodo = MFA_TOTP  # la interfaz clásica solo enrola TOTP
    usuario.ultimo_acceso = ahora_utc()
    sesion.etapa = ETAPA_ACTIVA
    token = rotar_token(db, sesion)
    codigos_recuperacion = recovery.emitir_codigos(db, usuario)
    audit.registrar(db, audit.MFA_ENROLADO, request=request, usuario=usuario,
                    detalle=f"{len(codigos_recuperacion)} códigos de recuperación emitidos.")
    audit.registrar(db, audit.MFA_OK, request=request, usuario=usuario)
    _avisar_inicio_sesion(db, request, usuario)

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
    usuario = db.get(Usuario, sesion.usuario_id)
    assert usuario is not None
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

    ip = _ip_de(request)

    # Doble límite: por cuenta (no inundar el buzón de un usuario) y por IP (no
    # convertir el sistema en un amplificador de correo).
    for clave in (f"otp-correo-user:{usuario.id}", f"otp-correo-ip:{ip}"):
        if not ratelimit.permitir_intento(clave, limite=3, ventana_minutos=15, db=db):
            audit.registrar(db, audit.MFA_OTP_CORREO_SOLICITADO, request=request, usuario=usuario,
                            detalle="Tasa excedida al pedir OTP por correo.", exito=False)
            db.commit()
            return render(request, "mfa_verificar.html", {
                **contexto, "error": "Demasiadas solicitudes; espere unos minutos.",
            }, status_code=429)

    codigo = otp_correo.emitir(db, usuario, ip)
    asunto, cuerpo_correo = otp_correo.texto_correo(usuario, codigo, ip)
    entregado = enviar_a_direccion(usuario.email, asunto, cuerpo_correo)
    audit.registrar(
        db, audit.MFA_OTP_CORREO_SOLICITADO, request=request, usuario=usuario,
        detalle=("Código de respaldo enviado al correo registrado." if entregado
                 else "No se pudo entregar el código de respaldo (fallo SMTP)."),
        exito=entregado,
    )
    db.commit()
    if not entregado:
        return render(request, "mfa_verificar.html", {
            **contexto,
            "error": "No se pudo enviar el código a su correo. Avise al administrador.",
        }, status_code=502)
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
    usuario = db.get(Usuario, sesion.usuario_id)
    assert usuario is not None

    if not hmac.compare_digest(csrf_token, sesion.csrf_token):
        return render(request, "mfa_verificar.html",
                      {"csrf_token": sesion.csrf_token, "error": "Token CSRF inválido."}, status_code=403)

    # Comprobación ÚNICA del segundo factor, común con la API JSON: TOTP (si es
    # el método del usuario) → código de recuperación → código por correo.
    resultado = segundo_factor.comprobar(db, usuario, codigo)
    reutilizado = resultado.reutilizado
    totp_valido = resultado.via == segundo_factor.VIA_TOTP
    recuperacion_usada = resultado.via == segundo_factor.VIA_RECUPERACION
    otp_correo_usado = resultado.via == segundo_factor.VIA_CORREO

    if not totp_valido and not recuperacion_usada and not otp_correo_usado:
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
    token = rotar_token(db, sesion)
    if segundo_factor.debe_reenrolar_con_totp(usuario):
        # Factores verificados, pero la política ya no admite el correo como
        # método principal para esta cuenta: debe configurar TOTP antes de entrar.
        sesion.etapa = ETAPA_MFA_ENROLAMIENTO
        audit.registrar(db, audit.MFA_OTP_CORREO_USADO, request=request, usuario=usuario,
                        detalle="Código por correo aceptado; se exige configurar TOTP.")
        respuesta = RedirectResponse("/mfa/configurar", status_code=303)
        configurar_cookie(respuesta, token)
        return respuesta
    usuario.ultimo_acceso = ahora_utc()
    sesion.etapa = ETAPA_ACTIVA

    if recuperacion_usada:
        restantes = recovery.codigos_restantes(db, usuario)
        audit.registrar(db, audit.MFA_RECUPERACION, request=request, usuario=usuario,
                        detalle=f"Quedan {restantes} código(s) de recuperación sin usar.")
        aviso = (f"Código de recuperación aceptado; le quedan {restantes}. "
                 "Si perdió su dispositivo, pida al administrador reiniciar su MFA.")
        destino = f"/?msg={quote(aviso)}"
    elif otp_correo_usado and usuario.mfa_metodo == MFA_CORREO:
        audit.registrar(db, audit.MFA_OTP_CORREO_USADO, request=request, usuario=usuario,
                        detalle="Acceso completado con código por correo (método principal).")
        destino = "/"
    elif otp_correo_usado:
        # Un acceso por el factor de respaldo merece revisión: se audita y se
        # alerta al equipo de seguridad, no solo al titular.
        audit.registrar(db, audit.MFA_OTP_CORREO_USADO, request=request, usuario=usuario,
                        detalle="Acceso completado con OTP de respaldo enviado al correo.")
        enviar_alerta(
            "Acceso con MFA de respaldo (OTP por correo)",
            f"La cuenta «{usuario.username}» completó el segundo factor con un código "
            f"enviado por correo, no con su aplicación autenticadora "
            f"(IP de origen: {_ip_de(request)}). Si no corresponde a una pérdida de "
            f"dispositivo conocida, revíselo.",
        )
        aviso = ("Acceso verificado con el código enviado a su correo. Vuelva a "
                 "configurar su aplicación autenticadora en cuanto pueda.")
        destino = f"/?msg={quote(aviso)}"
    else:
        audit.registrar(db, audit.MFA_OK, request=request, usuario=usuario)
        destino = "/"

    _avisar_inicio_sesion(db, request, usuario)

    respuesta = RedirectResponse(destino, status_code=303)
    configurar_cookie(respuesta, token)
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
    ip = request.client.host if request.client else "desconocida"
    cookie_csrf = request.cookies.get(COOKIE_CSRF_LOGIN, "")
    if not cookie_csrf or not hmac.compare_digest(csrf_token, cookie_csrf):
        return render(request, "recuperar_identidad.html",
                      {"error": "Sesión de formulario inválida; intente de nuevo.",
                       "csrf_login": cookie_csrf}, status_code=403)
    if not ratelimit.permitir_intento(f"recuperar:{ip}", db=db):
        audit.registrar(db, audit.RECUPERACION_FALLIDA, request=request,
                        username=username.strip().lower(), detalle="Tasa excedida.", exito=False)
        db.commit()
        return render(request, "recuperar_identidad.html",
                      {"error": "Demasiados intentos; espere unos minutos.", "csrf_login": cookie_csrf},
                      status_code=429)

    usuario = db.scalar(select(Usuario).where(func.lower(Usuario.username) == username.strip().lower()))
    coincide = (
        usuario is not None and usuario.activo and usuario.mfa_habilitado
        and usuario.totp_secret_cifrado is not None
        and hmac.compare_digest(usuario.email.strip().lower(), email.strip().lower())
    )
    # Se crea SIEMPRE un desafío (real o señuelo sin usuario) para que el paso 2
    # responda igual y con la misma latencia exista o no la cuenta.
    if coincide and ratelimit.permitir_intento(f"recuperar-user:{usuario.id}", db=db):
        token, _csrf = recuperacion.crear_desafio(db, usuario.id)
        audit.registrar(db, audit.RECUPERACION_INICIADA, request=request, usuario=usuario,
                        detalle="Identidad verificada; desafío de recuperación emitido.")
    else:
        token, _csrf = recuperacion.crear_desafio(db, None)
        audit.registrar(db, audit.RECUPERACION_FALLIDA, request=request,
                        usuario=usuario if coincide else None, username=username.strip().lower(),
                        detalle="Tasa por usuario excedida." if coincide else "Identidad no coincide.",
                        exito=False)
    db.commit()
    # PRG + anti-enumeración: SIEMPRE se redirige al paso 2 con cookie de desafío.
    respuesta = RedirectResponse("/recuperar/verificar", status_code=303)
    _cookie_recuperacion(respuesta, token)
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
    desafio = recuperacion.desafio_vigente(db, request.cookies.get(COOKIE_RECUPERACION))
    if desafio is None:
        return RedirectResponse("/recuperar", status_code=303)
    if not hmac.compare_digest(csrf_token, desafio.csrf_token):
        return render(request, "recuperar_verificar.html",
                      {"csrf_token": desafio.csrf_token, "error": "Token CSRF inválido."}, status_code=403)
    if desafio.verificado:
        return RedirectResponse("/recuperar/cambiar", status_code=303)
    if not ratelimit.permitir_intento(f"recuperar-verif:{desafio.usuario_id}", db=db):
        db.commit()
        return render(request, "recuperar_verificar.html",
                      {"csrf_token": desafio.csrf_token, "error": "Demasiados intentos; espere unos minutos."},
                      status_code=429)

    # Señuelo (usuario_id nulo) o cuenta inválida → mismo camino y respuesta que
    # un código incorrecto sobre una cuenta real (anti-enumeración en el paso 2).
    usuario = db.get(Usuario, desafio.usuario_id) if desafio.usuario_id is not None else None
    recuperable = usuario is not None and usuario.activo and usuario.mfa_habilitado
    if recuperable:
        # TOTP en vivo o código de recuperación; el código por correo no vale
        # aquí (la identidad ya se acreditó con el correo: sería un único factor).
        resultado = segundo_factor.comprobar(db, usuario, codigo, permitir_correo=False)
        totp_valido = resultado.via == segundo_factor.VIA_TOTP
        codigo_recuperacion = resultado.via == segundo_factor.VIA_RECUPERACION
    else:
        mfa.verificar_codigo(mfa.generar_secreto(), codigo)  # equipara el tiempo, nunca válido
        totp_valido = False
        codigo_recuperacion = False

    if not totp_valido and not codigo_recuperacion:
        agotado = recuperacion.registrar_fallo(db, desafio)
        audit.registrar(db, audit.RECUPERACION_FALLIDA, request=request, usuario=usuario,
                        detalle="Segundo factor incorrecto." + (" Desafío agotado." if agotado else ""),
                        exito=False)
        db.commit()
        if agotado:
            respuesta = RedirectResponse("/recuperar", status_code=303)
            respuesta.delete_cookie(COOKIE_RECUPERACION, path="/")
            return respuesta
        return render(request, "recuperar_verificar.html",
                      {"csrf_token": desafio.csrf_token, "error": "Código incorrecto."}, status_code=401)

    recuperacion.marcar_verificado(db, desafio)
    audit.registrar(db, audit.RECUPERACION_VERIFICADA, request=request, usuario=usuario,
                    detalle="Código de recuperación usado." if codigo_recuperacion else "TOTP verificado.")
    db.commit()
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
    if not hmac.compare_digest(csrf_token, desafio.csrf_token):
        return render(request, "recuperar_cambiar.html", {**ctx, "error": "Token CSRF inválido."}, status_code=403)

    usuario = db.get(Usuario, desafio.usuario_id)
    if usuario is None or not usuario.activo:
        recuperacion.consumir(db, desafio)
        db.commit()
        return RedirectResponse("/recuperar", status_code=303)

    if password_nueva != password_confirmacion:
        return render(request, "recuperar_cambiar.html", {**ctx, "error": "La confirmación no coincide."},
                      status_code=400)
    errores = validar_politica(password_nueva, usuario.username)
    if errores:
        return render(request, "recuperar_cambiar.html", {**ctx, "error": " ".join(errores)}, status_code=400)
    if verificar_password(usuario.password_hash, password_nueva):
        return render(request, "recuperar_cambiar.html",
                      {**ctx, "error": "La nueva contraseña debe ser distinta de la anterior."}, status_code=400)

    usuario.password_hash = hashear_password(password_nueva)
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
    revocar_sesion(sesion)
    audit.registrar(db, audit.LOGOUT, request=request, usuario=usuario)
    respuesta = RedirectResponse("/login", status_code=303)
    borrar_cookie(respuesta)
    return respuesta
