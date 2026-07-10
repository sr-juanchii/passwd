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

    # Rotación de credenciales: días sin rotar antes de alertar
    rotation_max_days: int = field(default_factory=lambda: _env_int("ROTATION_MAX_DAYS", 90))
    # Historial de contraseñas anteriores conservadas por credencial
    password_history_max: int = field(default_factory=lambda: _env_int("PASSWORD_HISTORY_MAX", 5))

    # MFA
    totp_issuer: str = field(default_factory=lambda: _env("TOTP_ISSUER", "Gestor-Passwd"))

    # Notificaciones por correo (opt-in; los correos NUNCA incluyen secretos)
    notify_enabled: bool = field(default_factory=lambda: _env_bool("NOTIFY_ENABLED", False))
    smtp_host: str = field(default_factory=lambda: _env("SMTP_HOST", ""))
    smtp_port: int = field(default_factory=lambda: _env_int("SMTP_PORT", 587))
    smtp_user: str = field(default_factory=lambda: _env("SMTP_USER", ""))
    smtp_password: str = field(default="", repr=False)
    smtp_from: str = field(default_factory=lambda: _env("SMTP_FROM", ""))
    smtp_tls: bool = field(default_factory=lambda: _env_bool("SMTP_TLS", True))
    notify_to: str = field(default_factory=lambda: _env("NOTIFY_TO", ""))

    # Backend del limitador de tasa: "memoria" (un proceso) o "bd" (compartido)
    rate_limit_backend: str = field(default_factory=lambda: _env("RATE_LIMIT_BACKEND", "memoria"))

    # Arranque inicial del administrador (solo si no existen usuarios)
    admin_username: str = field(default_factory=lambda: _env("ADMIN_USERNAME", ""))
    admin_email: str = field(default_factory=lambda: _env("ADMIN_EMAIL", ""))
    admin_password: str = field(default_factory=lambda: _env("ADMIN_PASSWORD", ""))

    secret_key: str = field(default="", repr=False)
    encryption_key: str = field(default="", repr=False)

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
        self.smtp_password = _secreto_entorno("SMTP_PASSWORD") or ""


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
