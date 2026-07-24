"""Registro de auditoría (CIS v8.1 control 8 / ISO 27001 A.8.15).

Toda autenticación, gestión de cuentas, cambio de inventario y —en especial—
cada visualización de una contraseña queda registrada con usuario, IP,
agente y resultado. La bitácora solo se escribe desde aquí y nunca contiene
secretos en claro.
"""

from __future__ import annotations

import hashlib
from datetime import timedelta

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RegistroAuditoria, Usuario, ahora_utc

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


def _hash(reg: RegistroAuditoria) -> str:
    return hashlib.sha256(_material(reg).encode("utf-8")).hexdigest()


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
    )
    db.add(reg)
    db.flush()  # asigna el id, necesario para el hash
    reg.hash_registro = _hash(reg)
    db.flush()


def verificar_cadena(db: Session) -> dict:
    """Recorre la bitácora y verifica el encadenamiento por hash.

    Detecta alteración de contenido (el hash recomputado no coincide) y
    eliminación/reordenación de filas (el ``hash_anterior`` no apunta al
    ``hash_registro`` del registro encadenado previo). Las filas sin hash
    (anteriores a la Fase 7 o restauradas de un respaldo) se omiten.

    Devuelve ``{"ok": True, "verificados": N}`` o
    ``{"ok": False, "id_roto": id, "motivo": ...}``.
    """
    registros = db.scalars(select(RegistroAuditoria).order_by(RegistroAuditoria.id)).all()
    ultimo = None
    verificados = 0
    for reg in registros:
        if not reg.hash_registro:
            continue  # registro sin encadenar (legado/restaurado)
        if _hash(reg) != reg.hash_registro:
            return {"ok": False, "id_roto": reg.id, "motivo": "contenido alterado"}
        if ultimo is not None and reg.hash_anterior != ultimo.hash_registro:
            return {"ok": False, "id_roto": reg.id, "motivo": "eslabón roto (fila eliminada o reordenada)"}
        ultimo = reg
        verificados += 1
    return {"ok": True, "verificados": verificados}


def purgar_antiguos(db: Session, dias_retencion: int) -> int:
    """Aplica la política de retención (CIS 8.10; mínimo recomendado 90 días)."""
    dias = max(dias_retencion, 90)
    limite = ahora_utc() - timedelta(days=dias)
    antiguos = db.scalars(select(RegistroAuditoria).where(RegistroAuditoria.fecha < limite)).all()
    for registro in antiguos:
        db.delete(registro)
    return len(antiguos)
