"""Configuración central de la aplicación.

Todos los parámetros se leen de variables de entorno con prefijo ``PASSWD_``.
Los secretos (clave de sesión y clave de cifrado) nunca se versionan: si no
se proporcionan por entorno se generan una sola vez y se persisten en el
directorio de datos con permisos 0600 (CIS 3.11 — cifrado de datos en reposo).
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from cryptography.fernet import Fernet

_PREFIX = "PASSWD_"


def _env(nombre: str, por_defecto: str) -> str:
    return os.environ.get(f"{_PREFIX}{nombre}", por_defecto)


def _env_int(nombre: str, por_defecto: int) -> int:
    return int(_env(nombre, str(por_defecto)))


def _env_bool(nombre: str, por_defecto: bool) -> bool:
    valor = _env(nombre, "true" if por_defecto else "false").strip().lower()
    return valor in {"1", "true", "yes", "si", "sí", "on"}


def _env_lista(nombre: str, por_defecto: str = "") -> list[str]:
    """Lista separada por comas (p. ej. orígenes CORS)."""
    return [parte.strip() for parte in _env(nombre, por_defecto).split(",") if parte.strip()]


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

    # Sesiones (CIS 4.3 — bloqueo automático por inactividad)
    session_idle_minutes: int = field(default_factory=lambda: _env_int("SESSION_IDLE_MINUTES", 15))
    session_max_hours: int = field(default_factory=lambda: _env_int("SESSION_MAX_HOURS", 8))
    cookie_secure: bool = field(default_factory=lambda: _env_bool("COOKIE_SECURE", True))
    # SameSite de las cookies de sesión: "strict" (mismo origen, por defecto y más
    # seguro) o "none" para despliegues cross-site (frontend en otro dominio, p. ej.
    # Vercel/v0 + backend en un VPS). "none" obliga a Secure (HTTPS).
    cookie_samesite: str = field(default_factory=lambda: _env("COOKIE_SAMESITE", "strict").strip().lower())

    # Orígenes permitidos para CORS con credenciales (vacío = sin CORS, mismo
    # origen). Define el/los dominios del frontend, p. ej.:
    #   PASSWD_CORS_ORIGINS=https://mi-app.vercel.app,https://preview.vercel.app
    cors_origins: list[str] = field(default_factory=lambda: _env_lista("CORS_ORIGINS", ""))

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

    # Tamaño máximo del cuerpo de una petición (OWASP API4)
    max_request_bytes: int = field(default_factory=lambda: _env_int("MAX_REQUEST_BYTES", 65536))

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
        if self.cookie_samesite not in {"strict", "lax", "none"}:
            self.cookie_samesite = "strict"
        # SameSite=None solo es válido con cookies Secure (requisito del navegador).
        if self.cookie_samesite == "none":
            self.cookie_secure = True
        self.data_dir = self.data_dir.resolve()
        if not self.database_url:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self.database_url = f"sqlite:///{self.data_dir / 'passwd.db'}"

        self.secret_key = os.environ.get(f"{_PREFIX}SECRET_KEY") or _leer_o_generar_secreto(
            self.data_dir / ".secret_key", lambda: secrets.token_urlsafe(48)
        )
        self.encryption_key = os.environ.get(f"{_PREFIX}ENCRYPTION_KEY") or _leer_o_generar_secreto(
            self.data_dir / ".encryption_key", lambda: Fernet.generate_key().decode("ascii")
        )
        self.smtp_password = os.environ.get(f"{_PREFIX}SMTP_PASSWORD", "")


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
