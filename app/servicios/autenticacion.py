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


# ---------------------------------------------------------------------------
# Segundo factor: enrolamiento
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EnrolamientoCompletado:
    """MFA activado: la sesión queda abierta y se entregan los códigos una vez."""

    usuario: Usuario
    token: str
    metodo: str
    codigos_recuperacion: list[str]


@dataclass(frozen=True)
class SegundoFactorVerificado:
    """Segundo factor superado. ``etapa`` puede ser el reenrolamiento forzado."""

    usuario: Usuario
    token: str
    etapa: str
    aviso: str | None = None


def _fallar_segundo_factor(
    db: Session,
    *,
    usuario: Usuario,
    sesion: SesionWeb,
    detalle: str,
    mensaje: str,
    codigo: int,
    request: Request | None = None,
) -> None:
    """Registra un código incorrecto y lanza. Vale para enrolar y para verificar.

    Un código erróneo cuenta para el bloqueo de la cuenta: si la cuenta se
    bloquea, la sesión a medio autenticar se revoca y el usuario vuelve al
    principio.
    """
    registrar_fallo(db, usuario, request)
    audit.registrar(db, audit.MFA_FALLIDO, request=request, usuario=usuario,
                    detalle=detalle, exito=False)
    if usuario.esta_bloqueado():
        revocar_sesion(sesion)
        db.commit()
        raise ErrorAutenticacion(
            "Cuenta bloqueada; vuelva a iniciar sesión.", 423,
            destino="/login?motivo=bloqueada", revocar_sesion=True,
        )
    db.commit()
    raise ErrorAutenticacion(mensaje, codigo)


def metodos_de_enrolamiento(db: Session, usuario: Usuario) -> dict:
    """Entre qué métodos puede elegir el usuario su segundo factor."""
    disponible = segundo_factor.correo_principal_disponible(usuario)
    return {
        "metodos": segundo_factor.metodos_enrolables(usuario),
        "correo": {
            "disponible": disponible,
            "destino": avisos.enmascarar_correo(usuario.email) if disponible else "",
            "motivo": "" if disponible else segundo_factor.motivo_correo_no_disponible(usuario),
        },
        # Cuenta enrolada por correo que ahora debe pasar a aplicación autenticadora.
        "obligado_totp": segundo_factor.debe_reenrolar_con_totp(usuario),
    }


def secreto_totp_para_enrolar(db: Session, usuario: Usuario) -> str:
    """Secreto TOTP con el que montar el QR, regenerándolo si hace falta."""
    reenrolando = usuario.mfa_habilitado and usuario.mfa_metodo == MFA_CORREO
    if usuario.totp_secret_cifrado is None or (usuario.mfa_habilitado and not reenrolando):
        usuario.totp_secret_cifrado = cifrar(mfa.generar_secreto())
        # Al pasar de correo a TOTP el MFA NO se desactiva mientras tanto: si el
        # usuario abandona a medias, su siguiente acceso sigue exigiendo el
        # código por correo en vez de quedarse sin segundo factor.
        if not reenrolando:
            usuario.mfa_habilitado = False
    secreto = descifrar(usuario.totp_secret_cifrado)
    # Confirmar aquí: el POST de confirmación relee el secreto de la base para
    # validar el código.
    db.commit()
    return secreto


def _completar_enrolamiento(
    db: Session,
    *,
    usuario: Usuario,
    sesion: SesionWeb,
    metodo: str,
    request: Request | None = None,
) -> EnrolamientoCompletado:
    usuario.mfa_habilitado = True
    usuario.mfa_metodo = metodo
    if metodo == MFA_CORREO:
        usuario.totp_secret_cifrado = None
        usuario.ultimo_totp_paso = None
        usuario.ultimo_otp_usado = None
    usuario.intentos_fallidos = 0
    usuario.ultimo_acceso = ahora_utc()
    sesion.etapa = ETAPA_ACTIVA
    token = rotar_token(db, sesion)
    codigos = recovery.emitir_codigos(db, usuario)
    audit.registrar(db, audit.MFA_ENROLADO, request=request, usuario=usuario,
                    detalle=f"Método: {metodo}. {len(codigos)} códigos de "
                            "recuperación emitidos.")
    audit.registrar(db, audit.MFA_OK, request=request, usuario=usuario)
    avisar_inicio_sesion(db, usuario, request)
    db.commit()
    return EnrolamientoCompletado(usuario=usuario, token=token, metodo=metodo,
                                  codigos_recuperacion=codigos)


def confirmar_enrolamiento_totp(
    db: Session, *, sesion: SesionWeb, usuario: Usuario, codigo: str,
    request: Request | None = None,
) -> EnrolamientoCompletado:
    if usuario.totp_secret_cifrado is None:
        raise ErrorAutenticacion(
            "Inicie de nuevo la configuración de la aplicación autenticadora.", 409,
        )
    # El código se registra como usado (paso temporal): no podrá repetirse en la
    # verificación ni reformateado con espacios. Es la vulnerabilidad que
    # documenta docs/resistencia-bypass-mfa.md §3.
    valido, _reutilizado = segundo_factor.aceptar_totp(usuario, codigo)
    if not valido:
        _fallar_segundo_factor(
            db, usuario=usuario, sesion=sesion, request=request,
            detalle="Código de enrolamiento incorrecto.",
            mensaje="Código incorrecto. Verifique su aplicación autenticadora.", codigo=400,
        )
    return _completar_enrolamiento(db, usuario=usuario, sesion=sesion,
                                   metodo=MFA_TOTP, request=request)


def confirmar_enrolamiento_correo(
    db: Session, *, sesion: SesionWeb, usuario: Usuario, codigo: str,
    request: Request | None = None,
) -> EnrolamientoCompletado:
    if not segundo_factor.correo_principal_disponible(usuario):
        raise ErrorAutenticacion(segundo_factor.motivo_correo_no_disponible(usuario), 409)
    if not otp_correo.consumir(db, usuario, codigo):
        _fallar_segundo_factor(
            db, usuario=usuario, sesion=sesion, request=request,
            detalle="Código de enrolamiento por correo incorrecto.",
            mensaje="Código incorrecto o caducado. Revise su correo o pida uno nuevo.",
            codigo=400,
        )
    otp_correo.invalidar_codigos(db, usuario.id)
    return _completar_enrolamiento(db, usuario=usuario, sesion=sesion,
                                   metodo=MFA_CORREO, request=request)


def enviar_codigo_correo(
    db: Session, *, usuario: Usuario, proposito: str, request: Request | None = None
) -> dict:
    """Emite y envía un código de un solo uso al buzón del usuario.

    Doble límite: por cuenta (no inundar el buzón de un usuario concreto) y por
    IP (no convertir el sistema en un amplificador de correo). La respuesta
    NUNCA lleva el código: solo confirma el envío y a qué buzón, enmascarado.
    """
    ip = ip_de(request)
    for clave in (f"otp-correo-user:{usuario.id}", f"otp-correo-ip:{ip}"):
        if not ratelimit.permitir_intento(clave, limite=3, ventana_minutos=15, db=db):
            audit.registrar(db, audit.MFA_OTP_CORREO_SOLICITADO, request=request, usuario=usuario,
                            detalle="Tasa excedida al pedir código por correo.", exito=False)
            db.commit()
            raise ErrorAutenticacion("Demasiadas solicitudes; espere unos minutos.", 429)

    codigo = otp_correo.emitir(db, usuario, ip)
    asunto, cuerpo_correo = otp_correo.texto_correo(usuario, codigo, ip)
    entregado = enviar_a_direccion(usuario.email, asunto, cuerpo_correo)
    audit.registrar(
        db, audit.MFA_OTP_CORREO_SOLICITADO, request=request, usuario=usuario,
        detalle=(f"Código enviado al correo registrado ({proposito})." if entregado
                 else f"No se pudo entregar el código por correo ({proposito}; fallo SMTP)."),
        exito=entregado,
    )
    db.commit()
    if not entregado:
        raise ErrorAutenticacion(
            "No se pudo enviar el código a su correo. Avise al administrador.", 502,
        )
    return {
        "ok": True,
        "destino": avisos.enmascarar_correo(usuario.email),
        "vigencia_minutos": get_settings().email_otp_ttl_minutes,
    }


# ---------------------------------------------------------------------------
# Segundo factor: verificación
# ---------------------------------------------------------------------------


def metodos_de_acceso(db: Session, usuario: Usuario) -> dict:
    """Con qué puede completar el segundo factor quien ya pasó la contraseña."""
    return {
        "metodo": usuario.mfa_metodo,
        "correo_disponible": segundo_factor.correo_en_login(usuario),
        "destino_correo": avisos.enmascarar_correo(usuario.email),
        "codigos_recuperacion": recovery.codigos_restantes(db, usuario),
    }


def verificar_segundo_factor(
    db: Session, *, sesion: SesionWeb, usuario: Usuario, codigo: str,
    request: Request | None = None,
) -> SegundoFactorVerificado:
    """Comprueba el segundo factor y abre la sesión.

    Acepta, en este orden, TOTP (si es el método del usuario), código de
    recuperación y código por correo. Un acceso por el **factor de respaldo**
    —correo cuando el método es la aplicación autenticadora— se audita y se
    alerta al equipo de seguridad: puede ser una pérdida de dispositivo
    legítima, o alguien que controla el buzón.

    Si la política dejó de admitir el correo como método principal para esta
    cuenta, los dos factores quedan verificados pero la sesión pasa al
    reenrolamiento en vez de activarse.
    """
    # Límite propio de la verificación, además del bloqueo de cuenta por fallos.
    # Hasta la 1.3.0 existía SOLO en la API JSON: la interfaz clásica se quedaba
    # con el bloqueo de cuenta como única defensa.
    if not ratelimit.permitir_intento(f"mfa-verif:{usuario.id}", db=db):
        audit.registrar(db, audit.MFA_FALLIDO, request=request, usuario=usuario,
                        detalle="Tasa de verificación excedida.", exito=False)
        db.commit()
        raise ErrorAutenticacion("Demasiados intentos; espere unos minutos.", 429)

    resultado = segundo_factor.comprobar(db, usuario, codigo)
    if not resultado.valido:
        _fallar_segundo_factor(
            db, usuario=usuario, sesion=sesion, request=request,
            detalle="Código reutilizado." if resultado.reutilizado else "Código incorrecto.",
            mensaje="Código incorrecto.", codigo=401,
        )

    usuario.intentos_fallidos = 0
    token = rotar_token(db, sesion)

    if segundo_factor.debe_reenrolar_con_totp(usuario):
        sesion.etapa = ETAPA_MFA_ENROLAMIENTO
        audit.registrar(db, audit.MFA_OTP_CORREO_USADO, request=request, usuario=usuario,
                        detalle="Código por correo aceptado; se exige configurar TOTP.")
        db.commit()
        return SegundoFactorVerificado(
            usuario=usuario, token=token, etapa=ETAPA_MFA_ENROLAMIENTO,
            aviso="Su cuenta debe usar ahora una aplicación autenticadora. "
                  "Configúrela para continuar.",
        )

    aviso = None
    if resultado.via == segundo_factor.VIA_RECUPERACION:
        restantes = recovery.codigos_restantes(db, usuario)
        audit.registrar(db, audit.MFA_RECUPERACION, request=request, usuario=usuario,
                        detalle=f"Quedan {restantes} código(s) de recuperación sin usar.")
        aviso = (f"Código de recuperación aceptado; le quedan {restantes}. "
                 "Puede generar códigos nuevos en «Mi seguridad».")
    elif resultado.via == segundo_factor.VIA_CORREO and usuario.mfa_metodo == MFA_TOTP:
        audit.registrar(db, audit.MFA_OTP_CORREO_USADO, request=request, usuario=usuario,
                        detalle="Acceso completado con código de respaldo enviado al correo.")
        enviar_alerta(
            "Acceso con MFA de respaldo (OTP por correo)",
            f"La cuenta «{usuario.username}» completó el segundo factor con un código "
            f"enviado por correo, no con su aplicación autenticadora "
            f"(IP de origen: {ip_de(request)}). Si no corresponde a una pérdida de "
            f"dispositivo conocida, revíselo.",
        )
        aviso = ("Acceso verificado con el código enviado a su correo. Vuelva a "
                 "configurar su aplicación autenticadora en cuanto pueda.")
    elif resultado.via == segundo_factor.VIA_CORREO:
        audit.registrar(db, audit.MFA_OTP_CORREO_USADO, request=request, usuario=usuario,
                        detalle="Acceso completado con código por correo (método principal).")
    else:
        audit.registrar(db, audit.MFA_OK, request=request, usuario=usuario)

    usuario.ultimo_acceso = ahora_utc()
    sesion.etapa = ETAPA_ACTIVA
    avisar_inicio_sesion(db, usuario, request)
    db.commit()
    return SegundoFactorVerificado(usuario=usuario, token=token,
                                   etapa=ETAPA_ACTIVA, aviso=aviso)


# ---------------------------------------------------------------------------
# Auto-recuperación de contraseña (identidad → segundo factor → clave nueva)
# ---------------------------------------------------------------------------
#
# Todo el flujo está construido para no convertirse en un oráculo de
# enumeración: los tres pasos hacen el mismo trabajo y responden lo mismo exista
# o no la cuenta. Un atacante que pruebe usuarios no debe poder distinguir, ni
# por el cuerpo, ni por la cookie, ni por la latencia, cuál existe.


@dataclass(frozen=True)
class DesafioRecuperacion:
    """Paso 1 superado (real o señuelo: desde fuera son indistinguibles)."""

    token: str
    csrf: str


def recuperacion_iniciar(
    db: Session,
    *,
    username: str,
    email: str,
    csrf_login: str,
    cookie_csrf: str,
    request: Request | None = None,
) -> DesafioRecuperacion:
    """Paso 1: identifica la cuenta y emite un desafío.

    Se crea **siempre** un desafío —real si la identidad coincide y la tasa por
    usuario lo permite, señuelo sin usuario en caso contrario— con el mismo
    trabajo de base de datos y la misma respuesta.
    """
    if not cookie_csrf or not hmac.compare_digest(csrf_login, cookie_csrf):
        raise ErrorAutenticacion("Sesión de formulario inválida; intente de nuevo.", 403)

    username = username.strip().lower()
    if not ratelimit.permitir_intento(f"recuperar:{ip_de(request)}", db=db):
        audit.registrar(db, audit.RECUPERACION_FALLIDA, request=request,
                        username=username, detalle="Tasa excedida.", exito=False)
        db.commit()
        raise ErrorAutenticacion("Demasiados intentos; espere unos minutos.", 429)

    email = email.strip().lower()
    usuario = db.scalar(select(Usuario).where(func.lower(Usuario.username) == username))
    coincide = (
        usuario is not None
        and usuario.activo
        and usuario.mfa_habilitado
        and hmac.compare_digest(usuario.email.strip().lower(), email)
    )

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
    return DesafioRecuperacion(token=token, csrf=csrf_desafio)


def recuperacion_verificar(
    db: Session,
    *,
    token_desafio: str | None,
    csrf_enviado: str,
    codigo: str,
    request: Request | None = None,
) -> None:
    """Paso 2: valida el segundo factor (TOTP en vivo o código de recuperación).

    El código **por correo no vale aquí**: la identidad ya se acreditó con el
    correo en el paso 1, así que aceptarlo dejaría toda la recuperación
    apoyada en un único factor.

    Idempotente: si el desafío ya estaba verificado, no vuelve a pedir nada.
    """
    desafio = recuperacion.desafio_vigente(db, token_desafio)
    if desafio is None:
        raise ErrorAutenticacion("Solicitud de recuperación inválida o caducada. Reiníciela.", 400)
    if not csrf_enviado or not hmac.compare_digest(csrf_enviado, desafio.csrf_token):
        raise ErrorAutenticacion("Token CSRF inválido o ausente.", 403)
    if desafio.verificado:
        return

    if not ratelimit.permitir_intento(f"recuperar-verif:{desafio.usuario_id}", db=db):
        db.commit()
        raise ErrorAutenticacion("Demasiados intentos; espere unos minutos.", 429)

    # Un desafío señuelo (sin usuario) o una cuenta ya inválida se tratan
    # EXACTAMENTE como un segundo factor incorrecto: mismo trabajo criptográfico
    # y misma respuesta que un código erróneo sobre una cuenta real.
    usuario = db.get(Usuario, desafio.usuario_id) if desafio.usuario_id is not None else None
    recuperable = usuario is not None and usuario.activo and usuario.mfa_habilitado
    if recuperable:
        resultado = segundo_factor.comprobar(db, usuario, codigo, permitir_correo=False)
        aceptado = resultado.via in (segundo_factor.VIA_TOTP, segundo_factor.VIA_RECUPERACION)
        por_recuperacion = resultado.via == segundo_factor.VIA_RECUPERACION
    else:
        mfa.verificar_codigo(mfa.generar_secreto(), codigo)  # equipara el tiempo, nunca válido
        aceptado = False
        por_recuperacion = False

    if not aceptado:
        agotado = recuperacion.registrar_fallo(db, desafio)
        audit.registrar(db, audit.RECUPERACION_FALLIDA, request=request, usuario=usuario,
                        detalle="Segundo factor incorrecto." + (" Desafío agotado." if agotado else ""),
                        exito=False)
        db.commit()
        if agotado:
            raise ErrorAutenticacion(
                "Demasiados códigos incorrectos; reinicie la recuperación.", 400,
                destino="/recuperar", revocar_sesion=True,
            )
        raise ErrorAutenticacion("Código incorrecto.", 401)

    recuperacion.marcar_verificado(db, desafio)
    audit.registrar(db, audit.RECUPERACION_VERIFICADA, request=request, usuario=usuario,
                    detalle="Código de recuperación usado." if por_recuperacion else "TOTP verificado.")
    db.commit()


def recuperacion_cambiar(
    db: Session,
    *,
    token_desafio: str | None,
    csrf_enviado: str,
    nueva: str,
    confirmacion: str,
    request: Request | None = None,
) -> Usuario:
    """Paso 3: fija la contraseña nueva y revoca **todas** las sesiones.

    Se revocan todas, incluidas las que pudiera tener abiertas quien provocó la
    recuperación: si se llega aquí es porque el acceso pudo estar comprometido.
    """
    desafio = recuperacion.desafio_vigente(db, token_desafio)
    if desafio is None or not desafio.verificado:
        raise ErrorAutenticacion(
            "Solicitud de recuperación inválida o sin verificar. Reiníciela.", 400,
        )
    if not csrf_enviado or not hmac.compare_digest(csrf_enviado, desafio.csrf_token):
        raise ErrorAutenticacion("Token CSRF inválido o ausente.", 403)

    usuario = db.get(Usuario, desafio.usuario_id)
    if usuario is None or not usuario.activo:
        recuperacion.consumir(db, desafio)
        db.commit()
        raise ErrorAutenticacion("Solicitud de recuperación inválida. Reiníciela.", 400)

    if nueva != confirmacion:
        raise ErrorAutenticacion("La confirmación no coincide.", 400)
    errores = validar_politica(nueva, usuario.username)
    if errores:
        raise ErrorAutenticacion(" ".join(errores), 400)
    if verificar_password(usuario.password_hash, nueva):
        raise ErrorAutenticacion("La nueva contraseña debe ser distinta de la anterior.", 400)

    usuario.password_hash = hashear_password(nueva)
    usuario.debe_cambiar_password = False
    usuario.password_cambiada_en = ahora_utc()
    usuario.intentos_fallidos = 0
    usuario.bloqueado_hasta = None
    revocar_sesiones_de_usuario(db, usuario.id)
    recuperacion.consumir(db, desafio)
    audit.registrar(db, audit.RECUPERACION_COMPLETADA, request=request, usuario=usuario,
                    detalle="Contraseña restablecida por auto-recuperación.")
    enviar_alerta(
        "Contraseña restablecida por auto-recuperación",
        f"La contraseña de «{usuario.username}» se restableció mediante el flujo de "
        f"auto-recuperación (IP de origen: {ip_de(request)}). Si no fue usted, contacte al "
        f"administrador de inmediato.",
    )
    db.commit()
    return usuario
