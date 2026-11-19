"""Autenticación: login por etapas, contraseña, sesión y reautenticación.

Aquí viven las **reglas** del acceso. Los controladores —``app/routes/auth.py``
para la interfaz clásica y ``app/api_web/auth.py`` para la API JSON— solo
traducen HTTP ↔ servicio: deciden si el desenlace se cuenta con un JSON, con una
plantilla renderizada o con una redirección, y fijan las cookies.

Antes de esta versión el login estaba escrito **dos veces, idéntico**: el mismo
CSRF de doble cookie, el mismo límite por IP, la misma comparación en tiempo
constante contra un hash ficticio, el mismo bloqueo de cuenta y el mismo
*rehash* oportunista, mantenidos en paralelo a mano. Mantener sincronizadas dos
copias de la puerta de entrada es exactamente el tipo de trabajo en el que
falla una rama y no la otra.

El servicio dice **qué pasó**; el controlador dice **cómo se cuenta**. Por eso
``ErrorAutenticacion`` lleva, además del mensaje, el código HTTP equivalente, un
destino opcional y si la sesión quedó revocada —lo justo para que cada interfaz
construya su respuesta sin volver a decidir nada.

Lo que NO está aquí: el manejo de cookies y plantillas (controlador), y las
primitivas de ``app/security/`` (hashing, sesiones, TOTP, límite de tasa), que
este módulo orquesta sin absorber.

---

**Reautenticación para acciones de alto impacto.**

«Mi seguridad» ya pide contraseña + segundo factor para cambiar el método MFA.
La autorización de una rotación necesita lo mismo, con una diferencia
deliberada: **no admite el código por correo**.

Un OTP enviado al buzón no es una segunda persona ni un segundo factor
independiente. El buzón puede ser compartido por el equipo de sistemas, estar
abierto en la misma sesión del navegador o ser accesible para quien ya controla
la cuenta. Toda la regla de dos pares de la gobernanza de rotación descansa en
que el autorizador demuestre posesión de algo que el solicitante no tiene, y el
correo no da esa garantía. Ver ``docs/resistencia-bypass-mfa.md``.

Los códigos de recuperación sí se admiten: son de un solo uso, se entregan al
titular en el enrolamiento y acreditan posesión igual que la aplicación
autenticadora. Es el mismo criterio que ya aplica el cambio de método de
segundo factor.
"""

from __future__ import annotations

import hmac
import secrets
from dataclasses import dataclass
from datetime import timedelta

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit, avisos
from app.config import get_settings
from app.models import (
    ETAPA_CAMBIO_PASSWORD,
    ETAPA_MFA_ENROLAMIENTO,
    ETAPA_MFA_PENDIENTE,
    MFA_TOTP,
    SesionWeb,
    Usuario,
    ahora_utc,
)
from app.notifications import enviar_alerta
from app.security import ratelimit, recovery, segundo_factor
from app.security.passwords import (
    hashear_password,
    necesita_rehash,
    validar_politica,
    verificar_password,
)
from app.security.sessions import (
    crear_sesion,
    revocar_sesion,
    revocar_sesiones_de_usuario,
    rotar_token,
)

# Hash ficticio para igualar tiempos cuando el usuario no existe: sin él, la
# diferencia entre «no existe» y «contraseña incorrecta» se mide con un
# cronómetro y permite enumerar cuentas.
_HASH_FICTICIO = hashear_password(secrets.token_urlsafe(24))


class ErrorAutenticacion(Exception):
    """Algo impidió autenticar. Lleva lo que el controlador necesita para responder.

    - ``codigo``: el HTTP equivalente (la interfaz clásica puede preferir
      renderizar o redirigir, y es asunto suyo).
    - ``destino``: a dónde mandar al usuario, cuando el desenlace lo implica.
    - ``revocar_sesion``: la sesión quedó revocada y el controlador debe borrar
      la cookie.
    """

    def __init__(
        self,
        mensaje: str,
        codigo: int = 400,
        *,
        destino: str | None = None,
        revocar_sesion: bool = False,
    ) -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.codigo = codigo
        self.destino = destino
        self.revocar_sesion = revocar_sesion


class ErrorReautenticacion(ErrorAutenticacion):
    """La reautenticación no se superó. ``codigo`` es el HTTP que corresponde."""

    def __init__(self, mensaje: str, codigo: int = 403) -> None:
        super().__init__(mensaje, codigo)


@dataclass(frozen=True)
class SesionIniciada:
    """Primer factor superado: queda la sesión creada, en su etapa inicial."""

    usuario: Usuario
    etapa: str
    token: str


@dataclass(frozen=True)
class PasswordCambiada:
    """Contraseña cambiada; el token de sesión se rotó."""

    usuario: Usuario
    token: str
    forzado: bool
    etapa: str | None  # la etapa nueva, solo si el cambio era forzado


def reautenticar(db: Session, usuario: Usuario, password: str, codigo: str) -> None:
    """Exige contraseña y segundo factor **sin correo**. Lanza si no se cumple.

    No distingue en el mensaje si falló la contraseña o el código: decirlo
    convertiría esta pantalla en un oráculo para comprobar contraseñas de
    administrador desde una sesión ya abierta.
    """
    if not password or not codigo:
        raise ErrorReautenticacion(
            "Para autorizar esta acción debe confirmar su contraseña y un código "
            "de su aplicación autenticadora.", codigo=400,
        )
    if usuario.mfa_metodo != MFA_TOTP and recovery.codigos_restantes(db, usuario) == 0:
        raise ErrorReautenticacion(
            "Esta acción exige una aplicación autenticadora. El código por correo no "
            "sirve para autorizar una rotación: configure el segundo factor en «Mi "
            "seguridad» antes de autorizar.",
        )
    password_ok = verificar_password(usuario.password_hash, password)
    resultado = segundo_factor.comprobar(db, usuario, codigo, permitir_correo=False)
    if not (password_ok and resultado.valido):
        raise ErrorReautenticacion(
            "No se pudo confirmar su identidad. Revise la contraseña y el código "
            "de su aplicación autenticadora.",
        )


# ---------------------------------------------------------------------------
# Etapas y bloqueo de cuenta
# ---------------------------------------------------------------------------


def etapa_inicial(usuario: Usuario) -> str:
    """Etapa de la sesión tras validar la contraseña.

    Devuelve **solo la etapa**: a qué URL lleva cada una es presentación, y cada
    interfaz tiene la suya.
    """
    if usuario.debe_cambiar_password:
        return ETAPA_CAMBIO_PASSWORD
    if not usuario.mfa_habilitado:
        return ETAPA_MFA_ENROLAMIENTO
    return ETAPA_MFA_PENDIENTE


def ip_de(request: Request | None) -> str:
    if request is None or request.client is None:
        return "desconocida"
    return request.client.host


def registrar_fallo(db: Session, usuario: Usuario, request: Request | None = None) -> None:
    """Suma un intento fallido y bloquea la cuenta al llegar al límite.

    El bloqueo revoca además las sesiones vivas del usuario: si alguien está
    probando contraseñas, una sesión suya abierta en otro sitio es justo lo que
    no conviene dejar en pie.
    """
    settings = get_settings()
    usuario.intentos_fallidos += 1
    if usuario.intentos_fallidos < settings.max_failed_attempts:
        return

    usuario.bloqueado_hasta = ahora_utc() + timedelta(minutes=settings.lockout_minutes)
    usuario.intentos_fallidos = 0
    revocar_sesiones_de_usuario(db, usuario.id)
    audit.registrar(
        db, audit.CUENTA_BLOQUEADA, request=request, usuario=usuario,
        detalle=f"Bloqueo automático por {settings.lockout_minutes} minutos.", exito=False,
    )
    enviar_alerta(
        "Cuenta bloqueada",
        f"La cuenta «{usuario.username}» se bloqueó automáticamente por intentos "
        f"de acceso fallidos (IP de origen: {ip_de(request)}).",
    )


def avisar_inicio_sesion(db: Session, usuario: Usuario, request: Request | None = None) -> None:
    """Aviso al titular de que se abrió una sesión con su cuenta (mejor esfuerzo)."""
    agente = request.headers.get("user-agent", "") if request is not None else ""
    avisos.aviso_inicio_sesion(db, usuario, ip_de(request), agente)


# ---------------------------------------------------------------------------
# Primer factor
# ---------------------------------------------------------------------------


def iniciar_sesion(
    db: Session,
    *,
    username: str,
    password: str,
    csrf_login: str,
    cookie_csrf: str,
    request: Request | None = None,
) -> SesionIniciada:
    """Valida el primer factor y abre la sesión en su etapa inicial.

    El orden importa y cada rechazo deja rastro:

    1. **CSRF de doble cookie**: el formulario debe traer el valor que la cookie
       fijó, de modo que un tercero no pueda enviar el login desde otro origen.
    2. **Límite por IP**: frena la prueba sistemática de contraseñas.
    3. **Usuario inexistente**: se comprueba igualmente contra un hash ficticio
       para que el tiempo de respuesta no distinga una cuenta real de una que no
       existe.
    4. **Bloqueo** y **cuenta desactivada**.
    5. **Contraseña**: un fallo suma al bloqueo.

    Los mensajes de los pasos 3 y 5 son el mismo a propósito: decir cuál de los
    dos falló convierte el formulario en un enumerador de cuentas.
    """
    username = username.strip().lower()

    if not cookie_csrf or not hmac.compare_digest(csrf_login, cookie_csrf):
        raise ErrorAutenticacion("Sesión de formulario inválida; intente de nuevo.", 403)

    if not ratelimit.permitir_intento(f"login:{ip_de(request)}", db=db):
        audit.registrar(db, audit.LOGIN_TASA_EXCEDIDA, request=request,
                        username=username, exito=False)
        db.commit()
        raise ErrorAutenticacion("Demasiados intentos; espere unos minutos.", 429)

    usuario = db.scalar(select(Usuario).where(func.lower(Usuario.username) == username))

    if usuario is None:
        verificar_password(_HASH_FICTICIO, password)  # tiempo constante
        audit.registrar(db, audit.LOGIN_FALLIDO, request=request, username=username,
                        detalle="Usuario inexistente.", exito=False)
        db.commit()
        raise ErrorAutenticacion("Credenciales inválidas.", 401)

    if usuario.esta_bloqueado():
        audit.registrar(db, audit.LOGIN_BLOQUEADO, request=request, usuario=usuario, exito=False)
        db.commit()
        raise ErrorAutenticacion("Cuenta bloqueada temporalmente por intentos fallidos.", 423)

    if not usuario.activo:
        audit.registrar(db, audit.LOGIN_FALLIDO, request=request, usuario=usuario,
                        detalle="Cuenta desactivada.", exito=False)
        db.commit()
        raise ErrorAutenticacion("Credenciales inválidas.", 401)

    if not verificar_password(usuario.password_hash, password):
        registrar_fallo(db, usuario, request)
        audit.registrar(db, audit.LOGIN_FALLIDO, request=request, usuario=usuario, exito=False)
        db.commit()
        raise ErrorAutenticacion("Credenciales inválidas.", 401)

    usuario.intentos_fallidos = 0
    usuario.bloqueado_hasta = None
    # Rehash oportunista: si la política de coste de Argon2id subió desde que se
    # guardó, se aprovecha el único momento en el que la contraseña está en
    # claro para actualizar el hash.
    if necesita_rehash(usuario.password_hash):
        usuario.password_hash = hashear_password(password)

    etapa = etapa_inicial(usuario)
    agente = request.headers.get("user-agent", "") if request is not None else ""
    _sesion, token = crear_sesion(
        db, usuario, etapa, direccion_ip=ip_de(request), agente_usuario=agente,
    )
    audit.registrar(db, audit.LOGIN_OK, request=request, usuario=usuario,
                    detalle=f"Primer factor correcto; etapa: {etapa}.")
    # Confirmar ANTES de responder: el frontend consulta /session de inmediato y
    # debe ver la sesión recién creada. El cleanup diferido de get_db (que corre
    # tras enviar la respuesta) provocaría una lectura-tras-escritura obsoleta
    # en MySQL (REPEATABLE READ); este commit explícito lo evita.
    db.commit()
    return SesionIniciada(usuario=usuario, etapa=etapa, token=token)


# ---------------------------------------------------------------------------
# Cambio de contraseña
# ---------------------------------------------------------------------------


def cambiar_password(
    db: Session,
    *,
    sesion: SesionWeb,
    actual: str,
    nueva: str,
    confirmacion: str,
    request: Request | None = None,
) -> PasswordCambiada:
    """Cambia la contraseña del titular de la sesión.

    Sirve al cambio **forzado** (primer acceso o contraseña temporal) y al
    voluntario; los distingue la etapa de la sesión.

    Al cambiarla se revocan **las demás** sesiones del usuario y la actual rota
    su token: si la contraseña se cambia porque pudo quedar expuesta, dejar
    vivas las sesiones abiertas con la anterior anularía el motivo del cambio.
    """
    usuario = db.get(Usuario, sesion.usuario_id)
    if usuario is None:
        raise ErrorAutenticacion("No autenticado", 401)
    forzado = sesion.etapa == ETAPA_CAMBIO_PASSWORD

    if not verificar_password(usuario.password_hash, actual):
        registrar_fallo(db, usuario, request)
        if usuario.esta_bloqueado():
            revocar_sesion(sesion)
            db.commit()
            raise ErrorAutenticacion(
                "Cuenta bloqueada; vuelva a iniciar sesión.", 423,
                destino="/login", revocar_sesion=True,
            )
        db.commit()
        raise ErrorAutenticacion("La contraseña actual no es correcta.", 400)

    if nueva != confirmacion:
        raise ErrorAutenticacion("La confirmación no coincide.", 400)
    if nueva == actual:
        raise ErrorAutenticacion("La nueva contraseña debe ser distinta de la actual.", 400)
    errores = validar_politica(nueva, usuario.username)
    if errores:
        raise ErrorAutenticacion(" ".join(errores), 400)

    usuario.password_hash = hashear_password(nueva)
    usuario.debe_cambiar_password = False
    usuario.password_cambiada_en = ahora_utc()
    usuario.intentos_fallidos = 0

    otras = [
        s for s in db.scalars(select(SesionWeb).where(
            SesionWeb.usuario_id == usuario.id, SesionWeb.revocada_en.is_(None))).all()
        if s.id != sesion.id
    ]
    for s in otras:
        revocar_sesion(s)
    token = rotar_token(db, sesion)
    audit.registrar(db, audit.PASSWORD_CAMBIADA, request=request, usuario=usuario)

    etapa = None
    if forzado:
        etapa = ETAPA_MFA_PENDIENTE if usuario.mfa_habilitado else ETAPA_MFA_ENROLAMIENTO
        sesion.etapa = etapa
    # Confirmar antes de responder (ver la nota en iniciar_sesion): el paso
    # siguiente del flujo lee la etapa y el token recién rotados de inmediato.
    db.commit()
    return PasswordCambiada(usuario=usuario, token=token, forzado=forzado, etapa=etapa)


# ---------------------------------------------------------------------------
# Cierre de sesión
# ---------------------------------------------------------------------------


def cerrar_sesion(
    db: Session, *, sesion: SesionWeb, usuario: Usuario, request: Request | None = None
) -> None:
    revocar_sesion(sesion)
    audit.registrar(db, audit.LOGOUT, request=request, usuario=usuario)
    db.commit()
