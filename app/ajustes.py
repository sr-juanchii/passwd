"""Configuración en tiempo de ejecución (ajustes operativos editables por el admin).

Sobre la configuración base —valores por defecto y variables de entorno, en
``app/config.py``— este módulo superpone una capa de *overrides* persistidos en
la tabla ``configuracion``. Solo un administrador (permiso
``configuracion.gestionar``) los modifica y **cada cambio queda auditado**.

Los valores efectivos se aplican sobre el singleton de ``Settings`` para que
todos los consumidores existentes (que leen ``get_settings()``) los respeten sin
cambios: sesiones, límites de tasa, política de contraseñas, rotación,
auditoría y notificaciones por correo. El singleton se refresca desde la BD al
arranque y periódicamente (TTL) para propagar cambios entre varios *workers*.

Fuera de alcance a propósito (solo por entorno/gestor de secretos, nunca
editable en caliente): claves criptográficas, URL/pool de la base de datos,
``cookie_secure``, tamaño máximo de petición, proxies de confianza, backend del
limitador y el arranque del administrador. Se muestran como información de solo
lectura en ``info_sistema``.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit, config
from app.config import OVERRIDABLES, base_overridable, base_overridables, get_settings
from app.models import Configuracion, Usuario
from app.security.crypto import cifrar, descifrar

logger = logging.getLogger("passwd.ajustes")

# Grupos para presentar los ajustes en la interfaz.
GRUPO_SESION = "Sesión y comportamiento"
GRUPO_CUENTAS = "Política de cuentas"
GRUPO_TASA = "Límites de tasa (anti-abuso)"
GRUPO_INVENTARIO = "Inventario y auditoría"
GRUPO_CORREO = "Notificaciones por correo"


@dataclass(frozen=True)
class Ajuste:
    """Metadatos de presentación y validación de un ajuste editable."""

    clave: str
    grupo: str
    etiqueta: str
    ayuda: str
    minimo: int | None = None
    maximo: int | None = None

    @property
    def tipo(self) -> str:
        return OVERRIDABLES[self.clave][1]

    @property
    def es_secreto(self) -> bool:
        return OVERRIDABLES[self.clave][1] == "secreto"


# Registro ORDENADO de ajustes editables (define también el orden en la interfaz).
# Los rangos de los enteros son de cordura: evitan valores absurdos o inseguros
# (p. ej. una retención de auditoría por debajo del mínimo de 90 días de CIS 8.10).
REGISTRO: tuple[Ajuste, ...] = (
    # Sesión y comportamiento
    Ajuste("session_idle_minutes", GRUPO_SESION, "Inactividad máxima (min)",
           "Minutos de inactividad antes de cerrar la sesión automáticamente.", 1, 1440),
    Ajuste("session_max_hours", GRUPO_SESION, "Vida máxima de sesión (h)",
           "Duración máxima absoluta de una sesión, aunque haya actividad.", 1, 168),
    Ajuste("activity_throttle_seconds", GRUPO_SESION, "Amortiguación de actividad (s)",
           "Intervalo mínimo entre escrituras de «última actividad» de sesión.", 0, 3600),
    # Política de cuentas
    Ajuste("password_min_length", GRUPO_CUENTAS, "Longitud mínima de contraseña",
           "Caracteres mínimos exigidos a las contraseñas de usuario (mínimo 8).", 8, 128),
    Ajuste("max_failed_attempts", GRUPO_CUENTAS, "Intentos fallidos antes de bloquear",
           "Número de inicios de sesión fallidos que bloquean la cuenta.", 1, 50),
    Ajuste("lockout_minutes", GRUPO_CUENTAS, "Duración del bloqueo (min)",
           "Minutos que permanece bloqueada una cuenta tras superar los intentos.", 1, 1440),
    # Límites de tasa
    Ajuste("login_rate_limit", GRUPO_TASA, "Límite de inicios de sesión",
           "Máximo de intentos de inicio de sesión por IP en la ventana.", 1, 1000),
    Ajuste("login_rate_window_minutes", GRUPO_TASA, "Ventana de inicio de sesión (min)",
           "Minutos de la ventana del límite de inicio de sesión.", 1, 1440),
    Ajuste("reveal_rate_limit", GRUPO_TASA, "Límite de revelados/copiados",
           "Máximo de contraseñas reveladas o copiadas por usuario en la ventana "
           "(anti-exfiltración).", 1, 1000),
    Ajuste("reveal_rate_window_minutes", GRUPO_TASA, "Ventana de revelados (min)",
           "Minutos de la ventana del límite anti-exfiltración.", 1, 1440),
    # Inventario y auditoría
    Ajuste("rotation_max_days", GRUPO_INVENTARIO, "Rotación: días antes de alertar",
           "Días sin rotar una credencial antes de marcarla como vencida.", 1, 3650),
    Ajuste("password_history_max", GRUPO_INVENTARIO, "Historial de contraseñas",
           "Cuántas contraseñas anteriores se conservan por credencial.", 0, 100),
    Ajuste("audit_retention_days", GRUPO_INVENTARIO, "Retención de auditoría (días)",
           "Días que se conserva la bitácora (mínimo 90 por CIS 8.10).", 90, 36500),
    # Notificaciones por correo
    Ajuste("notify_enabled", GRUPO_CORREO, "Notificaciones activas",
           "Activa el envío de alertas de seguridad por correo."),
    Ajuste("smtp_host", GRUPO_CORREO, "Servidor SMTP",
           "Host del servidor de correo saliente (p. ej. smtp.empresa.local)."),
    Ajuste("smtp_port", GRUPO_CORREO, "Puerto SMTP",
           "Puerto del servidor SMTP (habitualmente 587 con STARTTLS).", 1, 65535),
    Ajuste("smtp_user", GRUPO_CORREO, "Usuario SMTP",
           "Usuario de autenticación del servidor SMTP (opcional)."),
    Ajuste("smtp_password", GRUPO_CORREO, "Contraseña SMTP",
           "Contraseña de autenticación SMTP. Se guarda cifrada y nunca se muestra."),
    Ajuste("smtp_from", GRUPO_CORREO, "Remitente (From)",
           "Dirección remitente de las alertas (si se omite, se usa el usuario SMTP)."),
    Ajuste("smtp_tls", GRUPO_CORREO, "Usar STARTTLS",
           "Cifra la conexión SMTP con STARTTLS (recomendado)."),
    Ajuste("notify_to", GRUPO_CORREO, "Destinatarios",
           "Correos que reciben las alertas, separados por comas."),
    Ajuste("totp_issuer", GRUPO_CORREO, "Nombre / emisor",
           "Nombre del emisor mostrado en las apps TOTP y prefijo del asunto de los correos."),
)

_POR_CLAVE: dict[str, Ajuste] = {a.clave: a for a in REGISTRO}

_GRUPOS_ORDEN = (GRUPO_SESION, GRUPO_CUENTAS, GRUPO_TASA, GRUPO_INVENTARIO, GRUPO_CORREO)

# Refresco del singleton desde la BD: como máximo una lectura por este intervalo
# y por proceso. Además, solo se RE-APLICA cuando la configuración en BD cambió
# de verdad (control de versión), de modo que los valores que no tienen override
# en BD conservan lo que haya en el singleton (importante para no pisar ajustes
# fijados directamente, p. ej. en pruebas).
_TTL_SEGUNDOS = 10.0
_ultimo_refresco = 0.0
_version_aplicada: tuple | None = None
_lock = threading.Lock()


class ErrorAjuste(ValueError):
    """Valor inválido para un ajuste (mensaje apto para mostrar al usuario)."""


# ---------------------------------------------------------------------------
# Parseo, serialización y validación
# ---------------------------------------------------------------------------

_VERDADEROS = {"1", "true", "yes", "si", "sí", "on"}


def _parsear(ajuste: Ajuste, valor) -> object:
    """Convierte y valida un valor entrante (str o nativo). Lanza ErrorAjuste."""
    tipo = ajuste.tipo
    if tipo == "entero":
        try:
            n = int(str(valor).strip())
        except (TypeError, ValueError):
            raise ErrorAjuste(f"«{ajuste.etiqueta}» debe ser un número entero.") from None
        if ajuste.minimo is not None and n < ajuste.minimo:
            raise ErrorAjuste(f"«{ajuste.etiqueta}» no puede ser menor que {ajuste.minimo}.")
        if ajuste.maximo is not None and n > ajuste.maximo:
            raise ErrorAjuste(f"«{ajuste.etiqueta}» no puede ser mayor que {ajuste.maximo}.")
        return n
    if tipo == "booleano":
        if isinstance(valor, bool):
            return valor
        return str(valor).strip().lower() in _VERDADEROS
    # texto y secreto
    return str(valor).strip()


def _serializar(ajuste: Ajuste, valor: object) -> str:
    """Representación en texto para la columna ``valor`` (secretos cifrados)."""
    if ajuste.tipo == "booleano":
        return "true" if valor else "false"
    if ajuste.es_secreto:
        return cifrar(str(valor)).decode("ascii")
    return str(valor)


def _deserializar(ajuste: Ajuste, texto: str) -> object:
    """Valor nativo a partir del texto almacenado (descifra secretos)."""
    if ajuste.tipo == "entero":
        return int(texto)
    if ajuste.tipo == "booleano":
        return texto.strip().lower() in _VERDADEROS
    if ajuste.es_secreto:
        if not texto:
            return ""
        return descifrar(texto.encode("ascii"))
    return texto


# ---------------------------------------------------------------------------
# Lectura de overrides y cálculo de valores efectivos
# ---------------------------------------------------------------------------


def _overrides(db: Session) -> dict[str, str]:
    """Texto crudo de los overrides guardados, por clave (solo claves válidas)."""
    filas = db.scalars(select(Configuracion)).all()
    return {f.clave: f.valor for f in filas if f.clave in _POR_CLAVE}


def valores_efectivos(db: Session) -> dict[str, object]:
    """Valores efectivos: base (entorno/defecto) con los overrides aplicados."""
    valores = base_overridables()
    crudos = _overrides(db)
    for clave, texto in crudos.items():
        ajuste = _POR_CLAVE[clave]
        try:
            valores[clave] = _deserializar(ajuste, texto)
        except Exception:  # noqa: BLE001 — un override corrupto no debe romper la app
            logger.warning("Override de configuración ilegible para «%s»; se usa el valor base.", clave)
    return valores


def aplicar(db: Session, settings=None) -> None:
    """Aplica los valores efectivos sobre el singleton de ``Settings``.

    Idempotente: parte siempre de la base y superpone los overrides vigentes, de
    modo que también refleja los ajustes restablecidos (override eliminado).
    """
    destino = settings if settings is not None else get_settings()
    for clave, valor in valores_efectivos(db).items():
        setattr(destino, clave, valor)


def _version(db: Session) -> tuple:
    """Huella barata del estado de la tabla ``configuracion`` (nº filas + máx fecha).

    Cambia cuando se crea, modifica o borra cualquier override; sirve para
    re-aplicar solo cuando la configuración realmente cambió.
    """
    n = db.scalar(select(func.count(Configuracion.id))) or 0
    ultima = db.scalar(select(func.max(Configuracion.actualizado_en)))
    return (n, ultima.isoformat() if ultima is not None else "")


def _aplicar_y_marcar(db: Session) -> None:
    global _version_aplicada
    aplicar(db)
    _version_aplicada = _version(db)


# ---------------------------------------------------------------------------
# Inicialización y refresco periódico (propagación entre workers)
# ---------------------------------------------------------------------------


def inicializar(db: Session) -> None:
    """Aplica la configuración persistida al arrancar el proceso (worker)."""
    global _ultimo_refresco
    _aplicar_y_marcar(db)
    _ultimo_refresco = time.monotonic()


def refrescar_singleton() -> None:
    """Refresca el singleton desde la BD si transcurrió el TTL y la config cambió.

    Pensado para invocarse por petición desde un middleware: la mayoría de las
    veces solo compara un reloj monótono y no toca la BD; cuando toca, solo
    RE-APLICA si la versión de la configuración cambió respecto a la última
    aplicada (no pisa valores sin override). Nunca propaga errores.
    """
    global _ultimo_refresco
    if (time.monotonic() - _ultimo_refresco) < _TTL_SEGUNDOS:
        return
    with _lock:
        if (time.monotonic() - _ultimo_refresco) < _TTL_SEGUNDOS:
            return
        from app.database import sesion_efimera

        db = None
        try:
            db = sesion_efimera()
            if _version(db) != _version_aplicada:
                _aplicar_y_marcar(db)
            _ultimo_refresco = time.monotonic()
        except Exception:  # noqa: BLE001 — el refresco es de mejor esfuerzo
            logger.exception("No se pudo refrescar la configuración desde la base de datos.")
        finally:
            if db is not None:
                db.close()


def reiniciar_cache() -> None:
    """Reinicia el estado de refresco (uso en pruebas)."""
    global _ultimo_refresco, _version_aplicada
    _ultimo_refresco = 0.0
    _version_aplicada = None


# ---------------------------------------------------------------------------
# Mutación (guardar / restablecer) — solo administradores
# ---------------------------------------------------------------------------


def guardar(db: Session, cambios: dict[str, object], usuario: Usuario, request=None) -> list[str]:
    """Valida y persiste un lote de overrides; audita y aplica al instante.

    Devuelve la lista de claves efectivamente modificadas. Lanza ``ErrorAjuste``
    (sin persistir nada) si algún valor es inválido: la validación es previa a
    cualquier escritura para que el lote sea atómico.
    """
    # 1) Validar todo antes de tocar la BD.
    parseados: dict[str, object] = {}
    for clave, valor in cambios.items():
        ajuste = _POR_CLAVE.get(clave)
        if ajuste is None:
            raise ErrorAjuste(f"Ajuste desconocido: {clave}.")
        # Un secreto vacío significa «no cambiar» (no se puede releer para comparar).
        if ajuste.es_secreto and (valor is None or str(valor) == ""):
            continue
        parseados[clave] = _parsear(ajuste, valor)

    # 2) Persistir solo los overrides REALES: si el valor coincide con la base
    #    (entorno/defecto) no se guarda fila (y si existía una, se elimina), de
    #    modo que la tabla solo contiene desviaciones deliberadas.
    existentes = {f.clave: f for f in db.scalars(select(Configuracion)).all()}
    modificadas: list[str] = []
    for clave, valor in parseados.items():
        ajuste = _POR_CLAVE[clave]
        fila = existentes.get(clave)
        es_base = valor == base_overridable(clave)
        if es_base:
            if fila is not None:  # el nuevo valor iguala la base: quitar override
                db.delete(fila)
                modificadas.append(clave)
            continue
        texto = _serializar(ajuste, valor)
        if fila is None:
            db.add(Configuracion(clave=clave, valor=texto, es_secreto=ajuste.es_secreto,
                                 actualizado_por_id=usuario.id))
            modificadas.append(clave)
        elif ajuste.es_secreto or fila.valor != texto:
            # Los secretos se reescriben siempre que lleguen (Fernet no es
            # comparable byte a byte); el resto solo si el texto cambió.
            fila.valor = texto
            fila.es_secreto = ajuste.es_secreto
            fila.actualizado_por_id = usuario.id
            modificadas.append(clave)

    if modificadas:
        db.flush()
        detalle = ", ".join(sorted(modificadas))
        audit.registrar(db, audit.CONFIGURACION_CAMBIADA, request=request, usuario=usuario,
                        objeto_tipo="configuracion",
                        detalle=f"Ajustes modificados: {detalle}")
        # Aplica sobre el singleton usando ESTA sesión (ve las filas ya
        # descargadas con flush). Otros workers lo recogen por el TTL del
        # middleware tras el commit. No se usa una sesión efímera aquí: no vería
        # los cambios aún sin confirmar y dejaría el singleton con datos viejos.
        aplicar(db)
    return modificadas


def restablecer(db: Session, clave: str, usuario: Usuario, request=None) -> bool:
    """Elimina el override de una clave (vuelve al valor base). Devuelve si cambió."""
    ajuste = _POR_CLAVE.get(clave)
    if ajuste is None:
        raise ErrorAjuste(f"Ajuste desconocido: {clave}.")
    fila = db.scalar(select(Configuracion).where(Configuracion.clave == clave))
    if fila is None:
        return False
    db.delete(fila)
    db.flush()
    audit.registrar(db, audit.CONFIGURACION_RESTABLECIDA, request=request, usuario=usuario,
                    objeto_tipo="configuracion", detalle=f"Ajuste restablecido al valor base: {clave}")
    aplicar(db)
    return True


# ---------------------------------------------------------------------------
# Presentación para la interfaz (nunca expone secretos en claro)
# ---------------------------------------------------------------------------


def _origen(db_tiene_override: bool, clave: str) -> str:
    if db_tiene_override:
        return "configurado"      # override guardado en la BD
    if config.env_definida(clave):
        return "entorno"          # fijado por variable de entorno
    return "defecto"              # valor por defecto del sistema


def snapshot(db: Session) -> list[dict]:
    """Ajustes agrupados para la interfaz, con valor efectivo y origen.

    Los secretos nunca devuelven su valor: solo ``configurado`` (bool) indica si
    hay uno guardado.
    """
    efectivos = valores_efectivos(db)
    con_override = set(_overrides(db))
    grupos: dict[str, list[dict]] = {g: [] for g in _GRUPOS_ORDEN}
    for ajuste in REGISTRO:
        item = {
            "clave": ajuste.clave,
            "etiqueta": ajuste.etiqueta,
            "ayuda": ajuste.ayuda,
            "tipo": ajuste.tipo,
            "minimo": ajuste.minimo,
            "maximo": ajuste.maximo,
            "origen": _origen(ajuste.clave in con_override, ajuste.clave),
        }
        if ajuste.es_secreto:
            item["configurado"] = bool(efectivos.get(ajuste.clave))
        else:
            item["valor"] = efectivos[ajuste.clave]
        grupos[ajuste.grupo].append(item)
    return [{"grupo": g, "ajustes": grupos[g]} for g in _GRUPOS_ORDEN]


def info_sistema(settings=None) -> list[dict]:
    """Parámetros de solo lectura (definidos por entorno o que exigen reinicio).

    Nunca incluye el valor de las claves criptográficas: solo su origen.
    """
    s = settings if settings is not None else get_settings()
    motor = "SQLite" if s.database_url.startswith("sqlite") else "MySQL/MariaDB"
    claves_por_entorno = bool(
        config._secreto_entorno("SECRET_KEY") and config._secreto_entorno("ENCRYPTION_KEY")
    )
    return [
        {"etiqueta": "Nombre de la aplicación", "valor": s.app_name},
        {"etiqueta": "Motor de base de datos", "valor": motor},
        {"etiqueta": "Cookies solo por HTTPS (Secure/HSTS)", "valor": "sí" if s.cookie_secure else "no"},
        {"etiqueta": "Tamaño máximo de petición (bytes)", "valor": s.max_request_bytes},
        {"etiqueta": "Proxies de confianza", "valor": s.trusted_proxies or "(ninguno)"},
        {"etiqueta": "Backend del limitador de tasa", "valor": s.rate_limit_backend},
        {"etiqueta": "Claves criptográficas por entorno", "valor": "sí" if claves_por_entorno else "autogeneradas"},
    ]


def valor_base_ui(clave: str) -> object:
    """Valor base de una clave (para la interfaz; secretos devuelven '')."""
    ajuste = _POR_CLAVE[clave]
    if ajuste.es_secreto:
        return ""
    return base_overridable(clave)
