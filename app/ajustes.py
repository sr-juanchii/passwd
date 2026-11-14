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
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from types import SimpleNamespace

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit, config
from app.config import (
    OVERRIDABLES,
    SMTP_SIN_CIFRADO,
    SMTP_SSL,
    SMTP_STARTTLS,
    base_overridable,
    base_overridables,
    get_settings,
)
from app.models import Configuracion, Usuario
from app.security.crypto import cifrar, descifrar

logger = logging.getLogger("passwd.ajustes")

# Grupos para presentar los ajustes en la interfaz. Cada grupo responde a UNA
# función de la aplicación, de modo que cada opción esté donde se la busca.
GRUPO_SESION = "Sesión"
GRUPO_CUENTAS = "Cuentas y contraseñas"
GRUPO_MFA = "Verificación en dos pasos"
GRUPO_SMTP = "Servidor de correo (SMTP)"
GRUPO_AVISOS = "Notificaciones"
GRUPO_TASA = "Límites anti-abuso"
GRUPO_INVENTARIO = "Inventario y auditoría"

_DESCRIPCION_GRUPO = {
    GRUPO_SESION: "Cuánto dura una sesión abierta y cuándo se cierra sola.",
    GRUPO_CUENTAS: "Requisitos de las contraseñas de usuario y bloqueo por intentos fallidos.",
    GRUPO_MFA: "Métodos con los que los usuarios confirman su identidad al entrar.",
    GRUPO_SMTP: "Conexión con el servidor que envía el correo. De él dependen el código por "
                "correo, las contraseñas temporales, las alertas y los avisos.",
    GRUPO_AVISOS: "Qué correos envía la aplicación y a quién.",
    GRUPO_TASA: "Topes que frenan los intentos automatizados y la extracción masiva.",
    GRUPO_INVENTARIO: "Rotación e historial de credenciales y conservación de la bitácora.",
}

_RE_HOST = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9]([A-Za-z0-9.\-]*[A-Za-z0-9])?$|^\[[0-9A-Fa-f:.]+\]$")
_RE_CORREO = re.compile(r"^[^@\s<>,;\"']+@[A-Za-z0-9]([A-Za-z0-9.\-]*[A-Za-z0-9])?$")
_LARGO_MAX_TEXTO = 255


def _validar_host(valor: str) -> str | None:
    if valor and not _RE_HOST.match(valor):
        return "debe ser un nombre de host o una IP, sin «smtp://» ni puerto"
    return None


def _validar_correo(valor: str) -> str | None:
    if valor and not _RE_CORREO.match(valor):
        return "debe ser una dirección de correo válida"
    return None


def _validar_lista_correos(valor: str) -> str | None:
    for direccion in (d.strip() for d in valor.split(",")):
        if direccion and not _RE_CORREO.match(direccion):
            return f"contiene una dirección no válida: «{direccion}»"
    return None


def _validar_emisor(valor: str) -> str | None:
    if not valor:
        return "no puede quedar vacío"
    if len(valor) > 64 or any(c in valor for c in "[]:\r\n"):
        return "admite hasta 64 caracteres, sin corchetes, dos puntos ni saltos de línea"
    return None


@dataclass(frozen=True)
class Ajuste:
    """Metadatos de presentación y validación de un ajuste editable."""

    clave: str
    grupo: str
    etiqueta: str
    ayuda: str
    minimo: int | None = None
    maximo: int | None = None
    # Para el tipo «opcion»: pares (valor, etiqueta) admitidos.
    opciones: tuple[tuple[str, str], ...] = ()
    # Validación de formato de un texto: devuelve el motivo del rechazo o None.
    validador: Callable[[str], str | None] | None = None
    # Ajustes de los que depende: este solo surte efecto si TODOS están activos
    # (booleano en verdadero o texto no vacío). La interfaz lo deshabilita y
    # explica por qué mientras no se cumpla.
    depende_de: tuple[str, ...] = ()
    unidad: str = ""

    @property
    def tipo(self) -> str:
        return OVERRIDABLES[self.clave][1]

    @property
    def es_secreto(self) -> bool:
        return OVERRIDABLES[self.clave][1] == "secreto"


_SEGURIDAD_SMTP = (
    (SMTP_STARTTLS, "STARTTLS (puerto 587 habitual)"),
    (SMTP_SSL, "SSL/TLS implícito (puerto 465 habitual)"),
    (SMTP_SIN_CIFRADO, "Sin cifrado (solo relés internos)"),
)

# Registro ORDENADO de ajustes editables (define también el orden en la interfaz).
# Los rangos de los enteros son de cordura: evitan valores absurdos o inseguros
# (p. ej. una retención de auditoría por debajo del mínimo de 90 días de CIS 8.10).
REGISTRO: tuple[Ajuste, ...] = (
    # --- Sesión ---
    Ajuste("session_idle_minutes", GRUPO_SESION, "Cierre por inactividad",
           "Tiempo sin actividad tras el cual la sesión se cierra. Poco antes se avisa al "
           "usuario y puede extenderla.", 1, 1440, unidad="min"),
    Ajuste("session_max_hours", GRUPO_SESION, "Duración máxima de la sesión",
           "Tope absoluto: pasado este tiempo hay que iniciar sesión de nuevo aunque haya "
           "actividad. Se aplica a las sesiones que se abran a partir de ahora.", 1, 168, unidad="h"),
    # --- Cuentas y contraseñas ---
    Ajuste("password_min_length", GRUPO_CUENTAS, "Longitud mínima de contraseña",
           "Caracteres mínimos exigidos a las contraseñas de los usuarios de la aplicación.",
           8, 128, unidad="caracteres"),
    Ajuste("max_failed_attempts", GRUPO_CUENTAS, "Intentos fallidos antes de bloquear",
           "Fallos seguidos de contraseña o de código de verificación que bloquean la cuenta.", 1, 50),
    Ajuste("lockout_minutes", GRUPO_CUENTAS, "Duración del bloqueo",
           "Tiempo que permanece bloqueada una cuenta tras superar los intentos.", 1, 1440, unidad="min"),
    # --- Verificación en dos pasos ---
    Ajuste("totp_issuer", GRUPO_MFA, "Nombre de la aplicación",
           "Nombre con el que esta instalación aparece en las aplicaciones autenticadoras y "
           "en el asunto de los correos. Cambiarlo no afecta a los usuarios ya enrolados.",
           validador=_validar_emisor),
    Ajuste("email_otp_primary_enabled", GRUPO_MFA, "Permitir el correo como método principal",
           "Los usuarios pueden elegir recibir un código por correo en lugar de usar una "
           "aplicación autenticadora. Es más cómodo pero menos seguro: depende del buzón.",
           depende_de=("smtp_enabled",)),
    Ajuste("mfa_totp_required_admin", GRUPO_MFA, "Exigir aplicación autenticadora a los administradores",
           "Las cuentas de administrador no pueden usar el correo como método principal.",
           depende_de=("smtp_enabled", "email_otp_primary_enabled")),
    Ajuste("email_otp_enabled", GRUPO_MFA, "Permitir el correo como respaldo",
           "Quien usa aplicación autenticadora puede pedir un código por correo si no tiene el "
           "teléfono a mano. Cada uso se audita y alerta a los administradores.",
           depende_de=("smtp_enabled",)),
    Ajuste("email_otp_ttl_minutes", GRUPO_MFA, "Validez del código por correo",
           "Tiempo durante el cual sirve un código enviado por correo.", 1, 60, unidad="min",
           depende_de=("smtp_enabled",)),
    # --- Servidor de correo ---
    Ajuste("smtp_enabled", GRUPO_SMTP, "Servicio de correo activo",
           "Interruptor del envío de correo. Apagado, la aplicación no envía nada: ni códigos "
           "de verificación, ni contraseñas temporales, ni alertas, ni avisos."),
    Ajuste("smtp_host", GRUPO_SMTP, "Servidor",
           "Nombre o IP del servidor de correo saliente (p. ej. smtp.empresa.local).",
           validador=_validar_host, depende_de=("smtp_enabled",)),
    Ajuste("smtp_port", GRUPO_SMTP, "Puerto",
           "587 con STARTTLS, 465 con SSL/TLS, 25 para relés internos.", 1, 65535,
           depende_de=("smtp_enabled",)),
    Ajuste("smtp_security", GRUPO_SMTP, "Seguridad de la conexión",
           "Cómo se cifra la conexión con el servidor. Debe corresponder al puerto.",
           opciones=_SEGURIDAD_SMTP, depende_de=("smtp_enabled",)),
    Ajuste("smtp_user", GRUPO_SMTP, "Usuario",
           "Usuario con el que la aplicación se autentica en el servidor. Déjelo vacío si el "
           "servidor no exige autenticación.", depende_de=("smtp_enabled",)),
    Ajuste("smtp_password", GRUPO_SMTP, "Contraseña",
           "Contraseña del usuario SMTP. Se guarda cifrada y nunca se muestra.",
           depende_de=("smtp_enabled", "smtp_user")),
    Ajuste("smtp_from", GRUPO_SMTP, "Remitente",
           "Dirección que figura como remitente de los correos. Si se deja vacía se usa el "
           "usuario SMTP (que entonces debe ser una dirección de correo).",
           validador=_validar_correo, depende_de=("smtp_enabled",)),
    # --- Notificaciones ---
    Ajuste("notify_enabled", GRUPO_AVISOS, "Alertas de seguridad a administradores",
           "Avisa a los destinatarios indicados de cuentas bloqueadas, posibles extracciones "
           "masivas, altas de usuarios y accesos por el método de respaldo.",
           depende_de=("smtp_enabled",)),
    Ajuste("notify_to", GRUPO_AVISOS, "Destinatarios de las alertas",
           "Direcciones que reciben las alertas de seguridad, separadas por comas.",
           validador=_validar_lista_correos, depende_de=("smtp_enabled", "notify_enabled")),
    Ajuste("notify_users_enabled", GRUPO_AVISOS, "Avisos a los usuarios",
           "Cada usuario recibe en su correo los inicios de sesión, la actividad sensible, los "
           "cambios en sus permisos y los cambios en credenciales que comparte.",
           depende_de=("smtp_enabled",)),
    Ajuste("rotation_warning_days", GRUPO_AVISOS, "Preaviso de rotación",
           "Antelación con la que se avisa a quienes usan una credencial de que debe rotarse.",
           1, 365, unidad="días", depende_de=("smtp_enabled", "notify_users_enabled")),
    # --- Límites anti-abuso ---
    Ajuste("login_rate_limit", GRUPO_TASA, "Intentos de acceso por ventana",
           "Máximo de intentos por origen en la ventana. Se aplica al inicio de sesión, a la "
           "verificación en dos pasos y a la recuperación de contraseña.", 1, 1000),
    Ajuste("login_rate_window_minutes", GRUPO_TASA, "Ventana de los intentos de acceso",
           "Duración de la ventana del límite anterior.", 1, 1440, unidad="min"),
    Ajuste("reveal_rate_limit", GRUPO_TASA, "Contraseñas reveladas por ventana",
           "Máximo de contraseñas que un usuario puede revelar o copiar en la ventana. "
           "Superarlo alerta de una posible extracción masiva.", 1, 1000),
    Ajuste("reveal_rate_window_minutes", GRUPO_TASA, "Ventana de los revelados",
           "Duración de la ventana del límite anterior.", 1, 1440, unidad="min"),
    # --- Inventario y auditoría ---
    Ajuste("rotation_max_days", GRUPO_INVENTARIO, "Vigencia de las contraseñas",
           "Días tras los cuales una credencial sin rotar se marca como vencida.",
           1, 3650, unidad="días"),
    Ajuste("password_history_max", GRUPO_INVENTARIO, "Historial de contraseñas",
           "Contraseñas anteriores que se conservan de cada credencial (0 = ninguna).", 0, 100),
    Ajuste("audit_retention_days", GRUPO_INVENTARIO, "Conservación de la auditoría",
           "Tiempo que se conserva la bitácora; los registros más antiguos se eliminan "
           "automáticamente cada día (mínimo 90 por CIS 8.10).", 90, 36500, unidad="días"),
)

_POR_CLAVE: dict[str, Ajuste] = {a.clave: a for a in REGISTRO}

_GRUPOS_ORDEN = (GRUPO_SESION, GRUPO_CUENTAS, GRUPO_MFA, GRUPO_SMTP, GRUPO_AVISOS,
                 GRUPO_TASA, GRUPO_INVENTARIO)

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
    if tipo == "opcion":
        texto = str(valor).strip().lower()
        if texto not in {v for v, _ in ajuste.opciones}:
            raise ErrorAjuste(f"«{ajuste.etiqueta}» no admite el valor indicado.")
        return texto
    # texto y secreto
    texto = str(valor).strip()
    if len(texto) > _LARGO_MAX_TEXTO:
        raise ErrorAjuste(f"«{ajuste.etiqueta}» admite como máximo {_LARGO_MAX_TEXTO} caracteres.")
    if tipo == "texto" and ajuste.validador is not None:
        motivo = ajuste.validador(texto)
        if motivo:
            raise ErrorAjuste(f"«{ajuste.etiqueta}» {motivo}.")
    return texto


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


_MARCA_MIGRACION_CORREO = "_migracion.correo_v2"


def migrar_ajustes_de_correo(db: Session) -> bool:
    """Adapta UNA sola vez los ajustes de correo guardados al modelo actual.

    Antes ``notify_enabled`` era el interruptor de todo el correo y el cifrado
    era el booleano ``smtp_tls``. Ahora el servicio se enciende con
    ``smtp_enabled`` y el cifrado es ``smtp_security``. Para que una instalación
    que ya enviaba correo siga haciéndolo tras actualizar:

    * si había un override ``notify_enabled`` activo, se activa ``smtp_enabled``;
    * un override ``smtp_tls`` se traduce a ``smtp_security`` y se elimina.

    Una fila marcadora impide repetirlo (si no, apagar después el servicio desde
    la consola se desharía en el siguiente arranque). Devuelve si cambió algo.
    """
    filas = {f.clave: f for f in db.scalars(select(Configuracion)).all()}
    if _MARCA_MIGRACION_CORREO in filas:
        return False
    cambios = False
    notify = filas.get("notify_enabled")
    if ("smtp_enabled" not in filas and notify is not None
            and notify.valor.strip().lower() in _VERDADEROS
            and not base_overridable("smtp_enabled")):
        db.add(Configuracion(clave="smtp_enabled", valor="true", es_secreto=False))
        cambios = True
    tls = filas.get("smtp_tls")
    if tls is not None:
        seguridad = SMTP_STARTTLS if tls.valor.strip().lower() in _VERDADEROS else SMTP_SIN_CIFRADO
        if "smtp_security" not in filas and seguridad != base_overridable("smtp_security"):
            db.add(Configuracion(clave="smtp_security", valor=seguridad, es_secreto=False))
        db.delete(tls)
        cambios = True
    db.add(Configuracion(clave=_MARCA_MIGRACION_CORREO, valor="1", es_secreto=False))
    db.commit()
    if cambios:
        logger.info("Ajustes de correo migrados al modelo actual (smtp_enabled / smtp_security).")
    return cambios


def inicializar(db: Session) -> None:
    """Aplica la configuración persistida al arrancar el proceso (worker)."""
    global _ultimo_refresco
    try:
        migrar_ajustes_de_correo(db)
    except Exception:  # noqa: BLE001 — p. ej. otro worker la aplicó a la vez
        db.rollback()
        logger.warning("No se pudo migrar los ajustes de correo; se continúa con los valores actuales.")
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

    actuales = valores_efectivos(db)
    # Un secreto idéntico al vigente no es un cambio: ni se reescribe ni se audita.
    for clave in [c for c, v in parseados.items() if _POR_CLAVE[c].es_secreto and v == actuales.get(c)]:
        del parseados[clave]
    _validar_conjunto({**actuales, **parseados}, set(parseados))

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


def _validar_conjunto(valores: dict[str, object], cambiadas: set[str]) -> None:
    """Coherencia ENTRE ajustes del estado resultante. Lanza ``ErrorAjuste``.

    Cada regla solo se comprueba si el lote toca alguno de los ajustes que
    relaciona: una instalación con un dato antiguo incompleto puede seguir
    guardando ajustes que no tienen que ver con él.
    """
    def toca(*claves: str) -> bool:
        return bool(cambiadas.intersection(claves))

    if toca("session_idle_minutes", "session_max_hours"):
        if int(valores["session_idle_minutes"]) > int(valores["session_max_hours"]) * 60:  # type: ignore[call-overload]
            raise ErrorAjuste(
                "El cierre por inactividad no puede superar la duración máxima de la sesión.")

    if toca("smtp_enabled", "smtp_host", "smtp_from", "smtp_user") and valores["smtp_enabled"]:
        if not valores["smtp_host"]:
            raise ErrorAjuste("Para activar el servicio de correo indique el servidor SMTP.")
        remitente = str(valores["smtp_from"] or valores["smtp_user"] or "")
        if not remitente:
            raise ErrorAjuste("Indique el remitente de los correos (o un usuario SMTP que lo sea).")
        if _validar_correo(remitente):
            raise ErrorAjuste(
                "El remitente debe ser una dirección de correo: rellene «Remitente» "
                "(el usuario SMTP indicado no es una dirección).")

    if toca("notify_enabled", "notify_to") and valores["notify_enabled"] and not valores["notify_to"]:
        raise ErrorAjuste(
            "Indique al menos un destinatario para las alertas de seguridad a administradores.")


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
            "unidad": ajuste.unidad,
            "opciones": [{"valor": v, "etiqueta": e} for v, e in ajuste.opciones],
            "depende_de": [
                {"clave": c, "etiqueta": _POR_CLAVE[c].etiqueta} for c in ajuste.depende_de
            ],
            "origen": _origen(ajuste.clave in con_override, ajuste.clave),
        }
        if ajuste.es_secreto:
            item["configurado"] = bool(efectivos.get(ajuste.clave))
        else:
            item["valor"] = efectivos[ajuste.clave]
        grupos[ajuste.grupo].append(item)
    return [{"grupo": g, "descripcion": _DESCRIPCION_GRUPO[g], "ajustes": grupos[g]}
            for g in _GRUPOS_ORDEN]


# ---------------------------------------------------------------------------
# Correo: valores del formulario y estado de lo que depende de él
# ---------------------------------------------------------------------------

_CLAVES_SMTP = ("smtp_host", "smtp_port", "smtp_security", "smtp_user", "smtp_password", "smtp_from")


def ajustes_smtp_de_formulario(db: Session, valores: dict[str, object]) -> SimpleNamespace:
    """Parámetros SMTP para PROBAR sin guardar: los vigentes con los del formulario
    superpuestos. Una contraseña vacía significa «la guardada». Lanza ``ErrorAjuste``."""
    efectivos = valores_efectivos(db)
    resultado = {clave: efectivos[clave] for clave in _CLAVES_SMTP}
    for clave in _CLAVES_SMTP:
        if clave not in valores:
            continue
        ajuste = _POR_CLAVE[clave]
        if ajuste.es_secreto and (valores[clave] is None or str(valores[clave]) == ""):
            continue
        resultado[clave] = _parsear(ajuste, valores[clave])
    return SimpleNamespace(**resultado)


def estado_correo(settings=None) -> dict:
    """Qué funciones dependen del correo y cuáles están operativas ahora.

    Es el resumen que la consola muestra junto a la configuración SMTP para que
    cada interruptor se entienda por su efecto real."""
    s = settings if settings is not None else get_settings()
    operativo = bool(s.smtp_enabled and s.smtp_host)
    if not s.smtp_enabled:
        motivo = "El servicio de correo está apagado."
    elif not s.smtp_host:
        motivo = "Falta indicar el servidor SMTP."
    else:
        motivo = ""

    avisos: list[str] = []
    if operativo:
        if s.smtp_security == SMTP_SIN_CIFRADO:
            avisos.append(
                "La conexión no está cifrada: los correos (incluidos los códigos de verificación"
                + (" y la contraseña SMTP" if s.smtp_user else "") + ") viajan en claro.")
        if s.smtp_port == 465 and s.smtp_security != SMTP_SSL:
            avisos.append("El puerto 465 suele requerir «SSL/TLS implícito».")
        if s.smtp_port == 587 and s.smtp_security == SMTP_SSL:
            avisos.append("El puerto 587 suele requerir «STARTTLS».")
        if s.smtp_user and not s.smtp_password:
            avisos.append("Hay un usuario SMTP pero no una contraseña guardada.")

    def funcion(nombre: str, activa: bool, detalle: str) -> dict:
        return {"nombre": nombre, "activa": bool(operativo and activa),
                "detalle": detalle if operativo else motivo}

    destinatarios = [d for d in (x.strip() for x in s.notify_to.split(",")) if d]
    return {
        "operativo": operativo,
        "motivo": motivo,
        "avisos": avisos,
        "funciones": [
            funcion("Código por correo como método principal", s.email_otp_primary_enabled,
                    "Los usuarios pueden elegirlo al configurar su verificación en dos pasos."
                    if s.email_otp_primary_enabled else "Deshabilitado en «Verificación en dos pasos»."),
            funcion("Código por correo como respaldo", s.email_otp_enabled,
                    "Disponible para quien usa aplicación autenticadora."
                    if s.email_otp_enabled else "Deshabilitado en «Verificación en dos pasos»."),
            funcion("Envío de contraseñas temporales", True,
                    "Al restablecer una contraseña, la temporal llega al correo del usuario."),
            funcion("Alertas de seguridad a administradores",
                    s.notify_enabled and bool(destinatarios),
                    f"{len(destinatarios)} destinatario(s)." if s.notify_enabled and destinatarios
                    else ("Faltan destinatarios." if s.notify_enabled else "Desactivadas en «Notificaciones».")),
            funcion("Avisos a los usuarios", s.notify_users_enabled,
                    "Inicios de sesión, actividad sensible, permisos y rotación."
                    if s.notify_users_enabled else "Desactivados en «Notificaciones»."),
        ],
    }


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
