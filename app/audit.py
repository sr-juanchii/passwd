"""Registro de auditoría (CIS v8.1 control 8 / ISO 27001 A.8.15).

Toda autenticación, gestión de cuentas, cambio de inventario y —en especial—
cada visualización de una contraseña queda registrada con usuario, IP,
agente y resultado. La bitácora solo se escribe desde aquí y nunca contiene
secretos en claro.

**Encadenamiento firmado (desde la 1.3.0).** Cada registro encadena con el
anterior y se firma con **HMAC-SHA256** y la clave ``PASSWD_AUDIT_KEY``, que
vive fuera de la base de datos. Hasta la 1.2.0 el encadenamiento era un SHA-256
sin clave: cualquiera con acceso de escritura a la base podía recalcular la
cadena entera y reescribir quién hizo qué sin dejar rastro. Ese material previo
se conserva como **tramo heredado** y se sigue verificando con su algoritmo;
``verificar_cadena`` informa del punto de corte entre ambos tramos.

Esto importa especialmente para la gobernanza de rotación: el libro mayor solo
prueba quién aprobó una rotación si la bitácora que lo acompaña no se puede
rehacer desde la base de datos.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import timedelta

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import RegistroAuditoria, Usuario, ahora_utc

# Algoritmo del tramo firmado. Las filas con ``hash_algoritmo`` vacío pertenecen
# al tramo heredado (SHA-256 sin clave) o se restauraron de un respaldo.
ALGORITMO_HMAC = "hmac-sha256"

# Acciones normalizadas
LOGIN_OK = "login_correcto"
LOGIN_FALLIDO = "login_fallido"
LOGIN_BLOQUEADO = "login_cuenta_bloqueada"
LOGIN_TASA_EXCEDIDA = "login_tasa_excedida"
MFA_OK = "mfa_correcto"
MFA_FALLIDO = "mfa_fallido"
MFA_ENROLADO = "mfa_enrolado"
MFA_REINICIADO = "mfa_reiniciado"
MFA_RECUPERACION = "mfa_codigo_recuperacion_usado"
MFA_OTP_CORREO_SOLICITADO = "mfa_otp_correo_solicitado"
MFA_OTP_CORREO_USADO = "mfa_otp_correo_usado"
MFA_METODO_CAMBIADO = "mfa_metodo_cambiado"
MFA_CODIGOS_REGENERADOS = "mfa_codigos_regenerados"
LOGOUT = "cierre_sesion"
PASSWORD_CAMBIADA = "password_cambiada"  # noqa: S105 — nombre de acción, no es una contraseña
RECUPERACION_INICIADA = "recuperacion_iniciada"  # noqa: S105 — nombre de acción, no es una contraseña
RECUPERACION_VERIFICADA = "recuperacion_verificada"  # noqa: S105 — nombre de acción, no es una contraseña
RECUPERACION_COMPLETADA = "recuperacion_completada"  # noqa: S105 — nombre de acción, no es una contraseña
RECUPERACION_FALLIDA = "recuperacion_fallida"  # noqa: S105 — nombre de acción, no es una contraseña
CUENTA_BLOQUEADA = "cuenta_bloqueada"

USUARIO_CREADO = "usuario_creado"
USUARIO_ACTUALIZADO = "usuario_actualizado"
USUARIO_DESACTIVADO = "usuario_desactivado"
USUARIO_REACTIVADO = "usuario_reactivado"

ACTIVO_CREADO = "activo_creado"
ACTIVO_ACTUALIZADO = "activo_actualizado"
ACTIVO_ELIMINADO = "activo_eliminado"
ACTIVO_RESTRICCION_CAMBIADA = "activo_restriccion_cambiada"

CREDENCIAL_CREADA = "credencial_creada"
CREDENCIAL_ACTUALIZADA = "credencial_actualizada"
CREDENCIAL_ELIMINADA = "credencial_eliminada"
CREDENCIAL_REVELADA = "credencial_revelada"
CREDENCIAL_COPIADA = "credencial_copiada"
REVELADO_TASA_EXCEDIDA = "revelado_tasa_excedido"

NOTA_ACTUALIZADA = "nota_actualizada"
NOTA_REVELADA = "nota_revelada"

HISTORIAL_REVELADO = "historial_revelado"

ACCESO_DENEGADO = "acceso_denegado"

ACCESO_CONCEDIDO = "acceso_concedido"
ACCESO_REVOCADO = "acceso_revocado"

AUDITORIA_EXPORTADA = "auditoria_exportada"

TOKEN_CREADO = "token_api_creado"  # noqa: S105 — nombre de acción, no es un secreto
TOKEN_REVOCADO = "token_api_revocado"  # noqa: S105 — nombre de acción, no es un secreto

RESPALDO_CREADO = "respaldo_creado"
RESPALDO_RESTAURADO = "respaldo_restaurado"

IMPORTACION_REALIZADA = "importacion_realizada"
INVENTARIO_EXPORTADO = "inventario_exportado"

VAULT_CREADA = "vault_entrada_creada"
VAULT_ACTUALIZADA = "vault_entrada_actualizada"
VAULT_ELIMINADA = "vault_entrada_eliminada"
VAULT_REVELADA = "vault_entrada_revelada"
VAULT_COPIADA = "vault_entrada_copiada"

# Gobernanza de rotación (v1.3.0)
ROTACION_SOLICITADA = "rotacion_solicitada"
ROTACION_AUTORIZADA = "rotacion_autorizada"
ROTACION_RECHAZADA = "rotacion_rechazada"
ROTACION_CANCELADA = "rotacion_cancelada"
ROTACION_APLICADA = "rotacion_aplicada"
ROTACION_MANUAL_REGISTRADA = "rotacion_manual_registrada"
ROTACION_EMERGENCIA_SIN_PAR = "rotacion_emergencia_sin_par"
ROTACION_EMERGENCIA_REVISADA = "rotacion_emergencia_revisada"
ROTACION_ESCRITURA_DENEGADA = "rotacion_escritura_denegada"

CONFIGURACION_CAMBIADA = "configuracion_cambiada"
CONFIGURACION_RESTABLECIDA = "configuracion_restablecida"
CORREO_PRUEBA = "correo_prueba_enviado"


def _material(reg: RegistroAuditoria) -> str:
    """Representación canónica y estable de un registro, para su hash.

    La fecha se normaliza a segundos enteros: MySQL almacena ``DATETIME`` con
    precisión de segundo (y redondea la parte fraccionaria al insertar), de modo
    que incluir microsegundos rompería la verificación cross-engine al releer.
    """
    fecha = reg.fecha.replace(microsecond=0).isoformat()
    return "|".join([
        str(reg.id), fecha, str(reg.usuario_id or ""),
        reg.username, reg.accion, reg.objeto_tipo, reg.objeto_id,
        reg.detalle, reg.direccion_ip, reg.agente_usuario,
        "1" if reg.exito else "0", reg.hash_anterior,
    ])


def _hash_heredado(reg: RegistroAuditoria) -> str:
    """Encadenamiento anterior a la 1.3.0: SHA-256 sin clave, público."""
    return hashlib.sha256(_material(reg).encode("utf-8")).hexdigest()


def _firma(reg: RegistroAuditoria) -> str:
    """Encadenamiento firmado: HMAC-SHA256 con la clave de bitácora."""
    clave = get_settings().audit_key.encode("utf-8")
    return hmac.new(clave, _material(reg).encode("utf-8"), hashlib.sha256).hexdigest()


def _recalcular(reg: RegistroAuditoria) -> str:
    """Rehace el valor de encadenamiento con el algoritmo que declara la fila."""
    if reg.hash_algoritmo == ALGORITMO_HMAC:
        return _firma(reg)
    return _hash_heredado(reg)


def _ultimo_hash(db: Session) -> str:
    reg = db.scalar(select(RegistroAuditoria).order_by(RegistroAuditoria.id.desc()).limit(1))
    return reg.hash_registro if reg else ""


def registrar(
    db: Session,
    accion: str,
    *,
    request: Request | None = None,
    usuario: Usuario | None = None,
    username: str = "",
    objeto_tipo: str = "",
    objeto_id: int | str = "",
    detalle: str = "",
    exito: bool = True,
) -> None:
    ip = ""
    agente = ""
    if request is not None:
        ip = request.client.host if request.client else ""
        agente = request.headers.get("user-agent", "")
    reg = RegistroAuditoria(
        # Segundos enteros: evita que MySQL redondee la parte fraccionaria al
        # persistir y desincronice el hash respecto al valor releído.
        fecha=ahora_utc().replace(microsecond=0),
        usuario_id=usuario.id if usuario else None,
        username=(usuario.username if usuario else username)[:64],
        accion=accion,
        objeto_tipo=objeto_tipo,
        objeto_id=str(objeto_id),
        detalle=detalle[:2000],
        direccion_ip=ip[:45],
        agente_usuario=agente[:255],
        exito=exito,
        hash_anterior=_ultimo_hash(db),
        hash_algoritmo=ALGORITMO_HMAC,
    )
    db.add(reg)
    db.flush()  # asigna el id, necesario para el hash
    reg.hash_registro = _firma(reg)
    db.flush()


def verificar_cadena(db: Session) -> dict:
    """Recorre la bitácora y verifica el encadenamiento.

    Detecta alteración de contenido (el valor recomputado no coincide) y
    eliminación o reordenación de filas (el ``hash_anterior`` no apunta al
    ``hash_registro`` del registro encadenado previo). Las filas sin valor de
    encadenamiento (anteriores a la Fase 7 o restauradas de un respaldo) se
    omiten.

    La bitácora puede tener **dos tramos**: el heredado (SHA-256 sin clave,
    anterior a la 1.3.0) y el firmado (HMAC-SHA256). Cada fila se verifica con
    el algoritmo que declara, y el resultado informa del punto de corte.

    Una fila heredada que aparezca **después** del corte se trata como cadena
    rota: sería la forma de degradar la firma, reescribiendo registros con el
    algoritmo público para poder recalcularlos sin la clave.

    Devuelve ``{"ok": True, "verificados": N, "heredados": H, "firmados": F,
    "corte_id": id|None}`` o ``{"ok": False, "id_roto": id, "motivo": ...}``.
    """
    registros = db.scalars(select(RegistroAuditoria).order_by(RegistroAuditoria.id)).all()
    ultimo = None
    verificados = heredados = firmados = 0
    corte_id: int | None = None
    for reg in registros:
        if not reg.hash_registro:
            continue  # registro sin encadenar (legado/restaurado)
        firmado = reg.hash_algoritmo == ALGORITMO_HMAC
        if firmado:
            if corte_id is None:
                corte_id = reg.id
            firmados += 1
        else:
            if corte_id is not None:
                return {"ok": False, "id_roto": reg.id,
                        "motivo": "firma degradada (registro sin firmar después del tramo firmado)"}
            heredados += 1
        if _recalcular(reg) != reg.hash_registro:
            return {"ok": False, "id_roto": reg.id, "motivo": "contenido alterado"}
        if ultimo is not None and reg.hash_anterior != ultimo.hash_registro:
            return {"ok": False, "id_roto": reg.id, "motivo": "eslabón roto (fila eliminada o reordenada)"}
        ultimo = reg
        verificados += 1
    return {"ok": True, "verificados": verificados, "heredados": heredados,
            "firmados": firmados, "corte_id": corte_id}


def purgar_antiguos(db: Session, dias_retencion: int) -> int:
    """Aplica la política de retención (CIS 8.10; mínimo recomendado 90 días)."""
    dias = max(dias_retencion, 90)
    limite = ahora_utc() - timedelta(days=dias)
    antiguos = db.scalars(select(RegistroAuditoria).where(RegistroAuditoria.fecha < limite)).all()
    for registro in antiguos:
        db.delete(registro)
    return len(antiguos)
