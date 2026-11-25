"""Configuración central de la aplicación.

Todos los parámetros se leen de variables de entorno con prefijo ``PASSWD_``.
Los secretos (clave de sesión y clave de cifrado) nunca se versionan: si no
se proporcionan por entorno se generan una sola vez y se persisten en el
directorio de datos con permisos 0600 (CIS 3.11 — cifrado de datos en reposo).
"""

from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from cryptography.fernet import Fernet

_PREFIX = "PASSWD_"

logger = logging.getLogger(__name__)


def _env(nombre: str, por_defecto: str) -> str:
    return os.environ.get(f"{_PREFIX}{nombre}", por_defecto)


def _env_int(nombre: str, por_defecto: int) -> int:
    return int(_env(nombre, str(por_defecto)))


def _env_bool(nombre: str, por_defecto: bool) -> bool:
    valor = _env(nombre, "true" if por_defecto else "false").strip().lower()
    return valor in {"1", "true", "yes", "si", "sí", "on"}


def _secreto_entorno(nombre: str) -> str | None:
    """Lee un secreto del entorno con soporte de **Docker secrets**.

    Prioriza ``PASSWD_<NOMBRE>_FILE`` (ruta a un fichero montado por el gestor
    de secretos, p. ej. ``/run/secrets/...``) sobre ``PASSWD_<NOMBRE>``. Así el
    secreto no aparece en la tabla de procesos ni en ``docker inspect``.
    Devuelve ``None`` si no está definido por ninguna vía.
    """
    ruta = os.environ.get(f"{_PREFIX}{nombre}_FILE")
    if ruta:
        contenido = Path(ruta).read_text(encoding="utf-8").strip()
        if contenido:
            return contenido
    valor = os.environ.get(f"{_PREFIX}{nombre}")
    return valor or None


def _leer_o_generar_secreto(ruta: Path, generador) -> str:
    """Lee un secreto persistido o lo genera con permisos restrictivos."""
    if ruta.exists():
        return ruta.read_text(encoding="utf-8").strip()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    secreto = generador()
    ruta.touch(mode=0o600)
    ruta.write_text(secreto, encoding="utf-8")
    os.chmod(ruta, 0o600)
    return secreto


SMTP_STARTTLS = "starttls"
SMTP_SSL = "ssl"
SMTP_SIN_CIFRADO = "ninguna"
SMTP_SEGURIDADES = (SMTP_STARTTLS, SMTP_SSL, SMTP_SIN_CIFRADO)


def _smtp_enabled_base() -> bool:
    """Interruptor del servicio de correo; hereda NOTIFY_ENABLED si no se define."""
    return _env_bool("SMTP_ENABLED", _env_bool("NOTIFY_ENABLED", False))


def _smtp_security_base() -> str:
    """Modo de cifrado SMTP; compatible con la antigua PASSWD_SMTP_TLS."""
    valor = _env("SMTP_SECURITY", "").strip().lower()
    if valor in SMTP_SEGURIDADES:
        return valor
    return SMTP_STARTTLS if _env_bool("SMTP_TLS", True) else SMTP_SIN_CIFRADO


@dataclass
class Settings:
    """Parámetros de operación con valores seguros por defecto."""

    app_name: str = field(default_factory=lambda: _env("APP_NAME", "Gestor de Contraseñas de Servidores"))
    data_dir: Path = field(default_factory=lambda: Path(_env("DATA_DIR", "./data")))
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL", ""))

    # Pool de conexiones (solo motores cliente/servidor como MySQL; SQLite lo ignora).
    # pool_recycle recicla conexiones antes del wait_timeout del servidor.
    db_pool_size: int = field(default_factory=lambda: _env_int("DB_POOL_SIZE", 5))
    db_max_overflow: int = field(default_factory=lambda: _env_int("DB_MAX_OVERFLOW", 10))
    db_pool_recycle: int = field(default_factory=lambda: _env_int("DB_POOL_RECYCLE_SECONDS", 1800))

    # Sesiones (CIS 4.3 — bloqueo automático por inactividad)
    session_idle_minutes: int = field(default_factory=lambda: _env_int("SESSION_IDLE_MINUTES", 15))
    session_max_hours: int = field(default_factory=lambda: _env_int("SESSION_MAX_HOURS", 8))
    cookie_secure: bool = field(default_factory=lambda: _env_bool("COOKIE_SECURE", True))

    # Cuentas (CIS 5.2, 6.2 — política de contraseñas y bloqueo)
    password_min_length: int = field(default_factory=lambda: _env_int("PASSWORD_MIN_LENGTH", 12))
    max_failed_attempts: int = field(default_factory=lambda: _env_int("MAX_FAILED_ATTEMPTS", 5))
    lockout_minutes: int = field(default_factory=lambda: _env_int("LOCKOUT_MINUTES", 15))

    # Limitación de tasa para el inicio de sesión
    login_rate_limit: int = field(default_factory=lambda: _env_int("LOGIN_RATE_LIMIT", 15))
    login_rate_window_minutes: int = field(default_factory=lambda: _env_int("LOGIN_RATE_WINDOW_MINUTES", 5))

    # Anti-exfiltración: máximo de revelados/copiados de contraseñas por usuario
    reveal_rate_limit: int = field(default_factory=lambda: _env_int("REVEAL_RATE_LIMIT", 20))
    reveal_rate_window_minutes: int = field(default_factory=lambda: _env_int("REVEAL_RATE_WINDOW_MINUTES", 5))

    # Amortiguación de escrituras de "última actividad" de sesión y "último uso"
    # de token: solo se persisten si pasó al menos este intervalo, para no escribir
    # en cada petición (reduce presión de escritura/bloqueos en la BD).
    activity_throttle_seconds: int = field(default_factory=lambda: _env_int("ACTIVITY_THROTTLE_SECONDS", 60))

    # Tamaño máximo del cuerpo de una petición (OWASP API4)
    max_request_bytes: int = field(default_factory=lambda: _env_int("MAX_REQUEST_BYTES", 65536))

    # Proxies de confianza (CSV de IPs, o "*"). Si se define, la app confía en
    # X-Forwarded-For/-Proto SOLO cuando la conexión llega desde estas IPs, de
    # modo que la auditoría y el límite de tasa usan la IP real del cliente y
    # no la del proxy TLS (nginx). Vacío = desactivado (sin proxy delante).
    trusted_proxies: str = field(default_factory=lambda: _env("TRUSTED_PROXIES", ""))

    # Auditoría (CIS 8.10 — retención mínima de 90 días; por defecto 365)
    audit_retention_days: int = field(default_factory=lambda: _env_int("AUDIT_RETENTION_DAYS", 365))

    # Rotación de credenciales: días sin rotar antes de alertar. Es también el
    # INTERVALO DE POLÍTICA con el que la gobernanza calcula la fecha programada
    # de cada credencial y la desviación al rotar; no se duplica en otro ajuste.
    rotation_max_days: int = field(default_factory=lambda: _env_int("ROTATION_MAX_DAYS", 90))

    # --- Gobernanza de rotación (v1.3.0) ---------------------------------
    # Porcentaje del intervalo de política por debajo del cual una rotación se
    # marca TEMPRANA y exige motivo reforzado (25 % de 90 días = 22 días).
    rotacion_temprana_pct: int = field(default_factory=lambda: _env_int("ROTACION_TEMPRANA_PCT", 25))
    # Vía de emergencia: ventana, desde la solicitud, en la que un único
    # administrador puede autorizar su propia solicitud de emergencia. Fuera de
    # ella vuelve a exigirse la regla de dos pares.
    rotacion_emergencia_ventana_min: int = field(
        default_factory=lambda: _env_int("ROTACION_EMERGENCIA_VENTANA_MIN", 60))
    # Emergencias sin segundo par admitidas en 30 días antes de considerarlo un
    # patrón de abuso (se señala; nunca se bloquea una contención en curso).
    rotacion_emergencia_max_por_mes: int = field(
        default_factory=lambda: _env_int("ROTACION_EMERGENCIA_MAX_POR_MES", 3))
    # Las reglas de patrón arrancan en MODO OBSERVACIÓN: se evalúan y se ven en
    # métricas, pero no notifican. Se desactiva cuando los umbrales están
    # calibrados con datos reales de la instalación.
    rotacion_patrones_modo_observacion: bool = field(
        default_factory=lambda: _env_bool("ROTACION_PATRONES_MODO_OBSERVACION", True))

    # --- Agentes de rotación (v1.4.0) ------------------------------------
    # Interruptor general. Apagado, ningún agente se enrola ni recibe trabajos
    # y toda rotación sigue el flujo manual de la 1.3.0.
    agentes_enabled: bool = field(default_factory=lambda: _env_bool("AGENTES_ENABLED", False))
    # Vida de la identidad de un agente. Se renueva en cada latido, de modo que
    # un token robado del disco de un servidor caduca en horas, no en años.
    agentes_token_vida_horas: int = field(default_factory=lambda: _env_int("AGENTES_TOKEN_VIDA_HORAS", 24))
    # Sin latido durante este tiempo, el agente se muestra «sin contacto».
    agentes_umbral_sin_contacto_horas: int = field(
        default_factory=lambda: _env_int("AGENTES_UMBRAL_SIN_CONTACTO_HORAS", 24))
    # Cadencia de latido y telemetría que se indica a los agentes.
    agentes_telemetria_intervalo_min: int = field(
        default_factory=lambda: _env_int("AGENTES_TELEMETRIA_INTERVALO_MIN", 15))
    # Días que se conserva la telemetría.
    agentes_retencion_telemetria_dias: int = field(
        default_factory=lambda: _env_int("AGENTES_RETENCION_TELEMETRIA_DIAS", 30))
    # Versión mínima de agente que recibe trabajos (vacío = cualquiera) y días
    # de gracia desde que se fija en el panel.
    agentes_version_minima: str = field(default_factory=lambda: _env("AGENTES_VERSION_MINIMA", ""))
    agentes_gracia_version_dias: int = field(
        default_factory=lambda: _env_int("AGENTES_GRACIA_VERSION_DIAS", 14))
    # Avisar cuando un agente renueva su identidad desde dos IPs distintas en la
    # misma ventana. Detrás de NAT con varias salidas puede dar falsos positivos.
    agentes_alertar_ip_distinta: bool = field(
        default_factory=lambda: _env_bool("AGENTES_ALERTAR_IP_DISTINTA", True))
    # Historial de contraseñas anteriores conservadas por credencial
    password_history_max: int = field(default_factory=lambda: _env_int("PASSWORD_HISTORY_MAX", 5))

    # MFA
    totp_issuer: str = field(default_factory=lambda: _env("TOTP_ISSUER", "Gestor-Passwd"))

    # MFA de respaldo por correo: permite pedir un OTP al buzón registrado cuando
    # el usuario no tiene su dispositivo TOTP. Requiere SMTP + NOTIFY_ENABLED (sin
    # correo no puede funcionar). Es un factor MÁS DÉBIL que el TOTP —quien
    # controle el buzón y conozca la contraseña entra—, así que se puede desactivar
    # con PASSWD_EMAIL_OTP_ENABLED=false; ver docs/notificaciones-y-mfa-correo.md.
    email_otp_enabled: bool = field(default_factory=lambda: _env_bool("EMAIL_OTP_ENABLED", True))
    email_otp_ttl_minutes: int = field(default_factory=lambda: _env_int("EMAIL_OTP_TTL_MINUTES", 10))
    # Permite que un usuario ELIJA el correo como método principal de segundo
    # factor (sin aplicación autenticadora). Independiente del respaldo anterior.
    email_otp_primary_enabled: bool = field(
        default_factory=lambda: _env_bool("EMAIL_OTP_PRIMARY_ENABLED", True))
    # Los administradores deben usar aplicación autenticadora: el correo no les
    # vale como método principal (sí como respaldo, si está habilitado).
    mfa_totp_required_admin: bool = field(
        default_factory=lambda: _env_bool("MFA_TOTP_REQUIRED_ADMIN", True))

    # Avisos dinámicos por usuario (actividad propia, cambios de permisos,
    # credenciales compartidas y caducidad de rotación). Se resuelven contra la
    # matriz de permisos de cada usuario. Van dentro de NOTIFY_ENABLED: si el
    # correo está apagado, no se envía nada.
    notify_users_enabled: bool = field(default_factory=lambda: _env_bool("NOTIFY_USERS_ENABLED", True))
    # Días de antelación con los que se avisa de una rotación obligatoria próxima.
    rotation_warning_days: int = field(default_factory=lambda: _env_int("ROTATION_WARNING_DAYS", 14))

    # Servicio de correo saliente (SMTP). ``smtp_enabled`` es el interruptor del
    # SERVICIO: de él dependen el código por correo del segundo factor, el envío
    # de contraseñas temporales, las alertas y los avisos. Por compatibilidad, si
    # PASSWD_SMTP_ENABLED no está definida hereda PASSWD_NOTIFY_ENABLED (que antes
    # hacía de interruptor general).
    smtp_enabled: bool = field(default_factory=lambda: _smtp_enabled_base())
    # Alertas de seguridad a la lista de administradores (NOTIFY_TO). Solo eso:
    # ya no apaga el resto del correo. Los correos NUNCA incluyen secretos.
    notify_enabled: bool = field(default_factory=lambda: _env_bool("NOTIFY_ENABLED", False))
    smtp_host: str = field(default_factory=lambda: _env("SMTP_HOST", ""))
    smtp_port: int = field(default_factory=lambda: _env_int("SMTP_PORT", 587))
    smtp_user: str = field(default_factory=lambda: _env("SMTP_USER", ""))
    smtp_password: str = field(default="", repr=False)
    smtp_from: str = field(default_factory=lambda: _env("SMTP_FROM", ""))
    # Cifrado de la conexión SMTP: "starttls" (587), "ssl" (TLS implícito, 465) o
    # "ninguna". Si PASSWD_SMTP_SECURITY no está definida se deduce de la antigua
    # PASSWD_SMTP_TLS (true → starttls, false → ninguna).
    smtp_security: str = field(default_factory=lambda: _smtp_security_base())
    notify_to: str = field(default_factory=lambda: _env("NOTIFY_TO", ""))

    # Backend del limitador de tasa: "memoria" (un proceso) o "bd" (compartido)
    rate_limit_backend: str = field(default_factory=lambda: _env("RATE_LIMIT_BACKEND", "memoria"))

    # Arranque inicial del administrador (solo si no existen usuarios)
    admin_username: str = field(default_factory=lambda: _env("ADMIN_USERNAME", ""))
    admin_email: str = field(default_factory=lambda: _env("ADMIN_EMAIL", ""))
    admin_password: str = field(default_factory=lambda: _env("ADMIN_PASSWORD", ""))

    secret_key: str = field(default="", repr=False)
    encryption_key: str = field(default="", repr=False)
    # Clave de firma de la bitácora de auditoría (HMAC-SHA256). Sin ella el
    # encadenamiento es un SHA-256 público que cualquiera con acceso de
    # escritura a la base de datos puede recalcular entero; con ella, reescribir
    # la bitácora exige además la clave, que vive fuera de la base de datos.
    audit_key: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        self.data_dir = self.data_dir.resolve()
        if not self.database_url:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self.database_url = f"sqlite:///{self.data_dir / 'passwd.db'}"

        # Modo estricto (producción): exige que las claves criptográficas
        # lleguen por entorno (gestor de secretos) y prohíbe autogenerarlas en
        # el directorio de datos, donde conviven con la base de datos — un
        # compromiso del volumen expondría datos y clave a la vez (ISO A.8.24).
        requiere_env = _env_bool("REQUIRE_ENV_KEYS", False)
        secret_env = _secreto_entorno("SECRET_KEY")
        encryption_env = _secreto_entorno("ENCRYPTION_KEY")
        if requiere_env and not (secret_env and encryption_env):
            faltan = [
                f"{_PREFIX}{nombre}"
                for nombre, valor in (("SECRET_KEY", secret_env), ("ENCRYPTION_KEY", encryption_env))
                if not valor
            ]
            raise RuntimeError(
                f"{_PREFIX}REQUIRE_ENV_KEYS=true exige definir por entorno: {', '.join(faltan)}. "
                "Genere las claves (ver .env.produccion.example) y provéalas mediante su "
                "gestor de secretos; no se autogenerarán en el directorio de datos."
            )
        if not (secret_env and encryption_env):
            logger.warning(
                "Claves criptográficas autogeneradas en %s (modo solo-desarrollo): en producción "
                "defina %sSECRET_KEY y %sENCRYPTION_KEY por entorno y active %sREQUIRE_ENV_KEYS=true.",
                self.data_dir, _PREFIX, _PREFIX, _PREFIX,
            )

        self.secret_key = secret_env or _leer_o_generar_secreto(
            self.data_dir / ".secret_key", lambda: secrets.token_urlsafe(48)
        )
        self.encryption_key = encryption_env or _leer_o_generar_secreto(
            self.data_dir / ".encryption_key", lambda: Fernet.generate_key().decode("ascii")
        )
        # Clave de la bitácora. Deliberadamente NO entra en REQUIRE_ENV_KEYS en
        # esta versión: exigirla dejaría sin arrancar a una instalación que hoy
        # funciona en modo estricto, y eso sería una rotura en una versión MENOR.
        # Se avisa cuando se autogenera estando el modo estricto activo; la 2.0
        # la incorpora al grupo de claves obligatorias por entorno (rotura R2).
        audit_env = _secreto_entorno("AUDIT_KEY")
        if requiere_env and not audit_env:
            logger.warning(
                "%sREQUIRE_ENV_KEYS=true pero %sAUDIT_KEY no está definida: la clave de firma "
                "de la bitácora se autogenera en %s. Defínala por entorno (su gestor de "
                "secretos) para que la evidencia de auditoría no comparta volumen con la "
                "base de datos.", _PREFIX, _PREFIX, self.data_dir,
            )
        self.audit_key = audit_env or _leer_o_generar_secreto(
            self.data_dir / ".audit_key", lambda: secrets.token_urlsafe(48)
        )
        self.smtp_password = _secreto_entorno("SMTP_PASSWORD") or ""


# ---------------------------------------------------------------------------
# Ajustes editables en tiempo de ejecución (módulo `app/ajustes.py`)
# ---------------------------------------------------------------------------
#
# Lista blanca de parámetros que un administrador puede modificar en caliente:
# cada override se persiste en la tabla `configuracion` y anula el valor base
# (por defecto o de variable de entorno). Cada entrada mapea el atributo de
# ``Settings`` a (sufijo de env, tipo, valor por defecto). Los tipos rigen el
# parseo/serialización. Deliberadamente EXCLUIDOS (solo por entorno, nunca
# editables en caliente): claves criptográficas, URL/pool de BD, cookie_secure,
# max_request_bytes, trusted_proxies, rate_limit_backend y el arranque admin —
# afectan al arranque o son secretos de despliegue.
OVERRIDABLES: dict[str, tuple[str, str, object]] = {
    "session_idle_minutes": ("SESSION_IDLE_MINUTES", "entero", 15),
    "session_max_hours": ("SESSION_MAX_HOURS", "entero", 8),
    "activity_throttle_seconds": ("ACTIVITY_THROTTLE_SECONDS", "entero", 60),
    "password_min_length": ("PASSWORD_MIN_LENGTH", "entero", 12),
    "max_failed_attempts": ("MAX_FAILED_ATTEMPTS", "entero", 5),
    "lockout_minutes": ("LOCKOUT_MINUTES", "entero", 15),
    "login_rate_limit": ("LOGIN_RATE_LIMIT", "entero", 15),
    "login_rate_window_minutes": ("LOGIN_RATE_WINDOW_MINUTES", "entero", 5),
    "reveal_rate_limit": ("REVEAL_RATE_LIMIT", "entero", 20),
    "reveal_rate_window_minutes": ("REVEAL_RATE_WINDOW_MINUTES", "entero", 5),
    "rotation_max_days": ("ROTATION_MAX_DAYS", "entero", 90),
    "password_history_max": ("PASSWORD_HISTORY_MAX", "entero", 5),
    "audit_retention_days": ("AUDIT_RETENTION_DAYS", "entero", 365),
    "totp_issuer": ("TOTP_ISSUER", "texto", "Gestor-Passwd"),
    "smtp_enabled": ("SMTP_ENABLED", "booleano", False),
    "notify_enabled": ("NOTIFY_ENABLED", "booleano", False),
    "smtp_host": ("SMTP_HOST", "texto", ""),
    "smtp_port": ("SMTP_PORT", "entero", 587),
    "smtp_user": ("SMTP_USER", "texto", ""),
    "smtp_password": ("SMTP_PASSWORD", "secreto", ""),
    "smtp_from": ("SMTP_FROM", "texto", ""),
    "smtp_security": ("SMTP_SECURITY", "opcion", SMTP_STARTTLS),
    "notify_to": ("NOTIFY_TO", "texto", ""),
    "email_otp_enabled": ("EMAIL_OTP_ENABLED", "booleano", True),
    "email_otp_ttl_minutes": ("EMAIL_OTP_TTL_MINUTES", "entero", 10),
    "email_otp_primary_enabled": ("EMAIL_OTP_PRIMARY_ENABLED", "booleano", True),
    "mfa_totp_required_admin": ("MFA_TOTP_REQUIRED_ADMIN", "booleano", True),
    "notify_users_enabled": ("NOTIFY_USERS_ENABLED", "booleano", True),
    "rotation_warning_days": ("ROTATION_WARNING_DAYS", "entero", 14),
    "rotacion_temprana_pct": ("ROTACION_TEMPRANA_PCT", "entero", 25),
    "rotacion_emergencia_ventana_min": ("ROTACION_EMERGENCIA_VENTANA_MIN", "entero", 60),
    "rotacion_emergencia_max_por_mes": ("ROTACION_EMERGENCIA_MAX_POR_MES", "entero", 3),
    "rotacion_patrones_modo_observacion": ("ROTACION_PATRONES_MODO_OBSERVACION", "booleano", True),
    "agentes_enabled": ("AGENTES_ENABLED", "booleano", False),
    "agentes_token_vida_horas": ("AGENTES_TOKEN_VIDA_HORAS", "entero", 24),
    "agentes_umbral_sin_contacto_horas": ("AGENTES_UMBRAL_SIN_CONTACTO_HORAS", "entero", 24),
    "agentes_telemetria_intervalo_min": ("AGENTES_TELEMETRIA_INTERVALO_MIN", "entero", 15),
    "agentes_retencion_telemetria_dias": ("AGENTES_RETENCION_TELEMETRIA_DIAS", "entero", 30),
    "agentes_version_minima": ("AGENTES_VERSION_MINIMA", "texto", ""),
    "agentes_gracia_version_dias": ("AGENTES_GRACIA_VERSION_DIAS", "entero", 14),
    "agentes_alertar_ip_distinta": ("AGENTES_ALERTAR_IP_DISTINTA", "booleano", True),
}


def base_overridable(clave: str) -> object:
    """Valor BASE (por defecto o de entorno) de una clave editable, sin overrides.

    No tiene efectos secundarios (no toca disco ni la BD): reutiliza los mismos
    lectores de entorno que ``Settings``. Sirve de línea base sobre la que la
    capa de configuración aplica los overrides guardados.
    """
    sufijo, tipo, defecto = OVERRIDABLES[clave]
    # Claves cuya base se deduce de otra variable por compatibilidad.
    if clave == "smtp_enabled":
        return _smtp_enabled_base()
    if clave == "smtp_security":
        return _smtp_security_base()
    if tipo == "entero":
        return _env_int(sufijo, int(defecto))  # type: ignore[arg-type]
    if tipo == "booleano":
        return _env_bool(sufijo, bool(defecto))
    if tipo == "secreto":
        return _secreto_entorno(sufijo) or ""
    return _env(sufijo, str(defecto))


def base_overridables() -> dict[str, object]:
    """Todos los valores base de las claves editables (sin overrides de BD)."""
    return {clave: base_overridable(clave) for clave in OVERRIDABLES}


# Variables antiguas que todavía fijan el valor base de una clave editable, y
# que la 2.0 elimina (rotura R4 de docs/plan-v2.0.md). Una sola fuente de
# verdad: la usan `env_definida()` para resolver el origen de un ajuste y
# `obsoletas_en_uso()` para avisar en el arranque.
SUFIJOS_OBSOLETOS: dict[str, list[tuple[str, str]]] = {
    # clave editable → [(variable antigua, variable que la sustituye)]
    "smtp_enabled": [("NOTIFY_ENABLED", "SMTP_ENABLED")],
    "smtp_security": [("SMTP_TLS", "SMTP_SECURITY")],
}


def _env_presente(sufijo: str) -> bool:
    return bool(os.environ.get(f"{_PREFIX}{sufijo}") or os.environ.get(f"{_PREFIX}{sufijo}_FILE"))


def env_definida(clave: str) -> bool:
    """¿La clave editable está fijada por variable de entorno (o su *_FILE)?"""
    sufijos = [OVERRIDABLES[clave][0]]
    sufijos += [antigua for antigua, _nueva in SUFIJOS_OBSOLETOS.get(clave, [])]
    return any(_env_presente(sufijo) for sufijo in sufijos)


def obsoletas_en_uso() -> list[tuple[str, str]]:
    """Herencias obsoletas que hoy están EN EFECTO, con la variable sustituta.

    Lo que la 2.0 retira no son las variables en sí, sino que una fije el valor
    de otra. Por eso solo se avisa cuando la sustituta no está definida, que es
    cuando la herencia decide de verdad: con las dos puestas manda la nueva y no
    hay nada que corregir.

    La distinción no es cosmética. `PASSWD_NOTIFY_ENABLED` sigue teniendo
    significado propio —gobierna las alertas de seguridad a los
    administradores— y solo es obsoleta como origen de `PASSWD_SMTP_ENABLED`.
    Avisar de ella sin más llevaría a quien la use a borrarla y quedarse sin
    alertas, que es peor que no avisar.
    """
    return [
        (antigua, nueva)
        for pares in SUFIJOS_OBSOLETOS.values()
        for antigua, nueva in pares
        if _env_presente(antigua) and not _env_presente(nueva)
    ]


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Reinicia la configuración (uso exclusivo en pruebas)."""
    global _settings
    _settings = None
