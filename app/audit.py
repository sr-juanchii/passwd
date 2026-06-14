"""Registro de auditoría (CIS v8.1 control 8 / ISO 27001 A.8.15).

Toda autenticación, gestión de cuentas, cambio de inventario y —en especial—
cada visualización de una contraseña queda registrada con usuario, IP,
agente y resultado. La bitácora solo se escribe desde aquí y nunca contiene
secretos en claro.
"""

from __future__ import annotations

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
CUENTA_BLOQUEADA = "cuenta_bloqueada"

USUARIO_CREADO = "usuario_creado"
USUARIO_ACTUALIZADO = "usuario_actualizado"
USUARIO_DESACTIVADO = "usuario_desactivado"
USUARIO_REACTIVADO = "usuario_reactivado"

ACTIVO_CREADO = "activo_creado"
ACTIVO_ACTUALIZADO = "activo_actualizado"
ACTIVO_ELIMINADO = "activo_eliminado"

CREDENCIAL_CREADA = "credencial_creada"
CREDENCIAL_ACTUALIZADA = "credencial_actualizada"
CREDENCIAL_ELIMINADA = "credencial_eliminada"
CREDENCIAL_REVELADA = "credencial_revelada"
CREDENCIAL_COPIADA = "credencial_copiada"
REVELADO_TASA_EXCEDIDA = "revelado_tasa_excedido"

ACCESO_DENEGADO = "acceso_denegado"

RESPALDO_CREADO = "respaldo_creado"
RESPALDO_RESTAURADO = "respaldo_restaurado"


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
    db.add(
        RegistroAuditoria(
            usuario_id=usuario.id if usuario else None,
            username=(usuario.username if usuario else username)[:64],
            accion=accion,
            objeto_tipo=objeto_tipo,
            objeto_id=str(objeto_id),
            detalle=detalle[:2000],
            direccion_ip=ip[:45],
            agente_usuario=agente[:255],
            exito=exito,
        )
    )
    db.flush()


def purgar_antiguos(db: Session, dias_retencion: int) -> int:
    """Aplica la política de retención (CIS 8.10; mínimo recomendado 90 días)."""
    dias = max(dias_retencion, 90)
    limite = ahora_utc() - timedelta(days=dias)
    antiguos = db.scalars(select(RegistroAuditoria).where(RegistroAuditoria.fecha < limite)).all()
    for registro in antiguos:
        db.delete(registro)
    return len(antiguos)
