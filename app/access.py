"""Control de acceso por objeto (concesiones por activo).

Complementa el RBAC estático (`app/rbac.py`): mientras aquel decide qué tipo de
operación permite un rol, este decide —para el rol ``analista``— sobre qué
activos concretos puede operar, según las concesiones vigentes que un
administrador le haya otorgado.

Reglas (least privilege, default-deny para el analista):

    rol         ver activo            revelar/copiar credenciales
    ---------   -------------------   ----------------------------
    admin       todos                 todas
    operador    todos                 todas
    auditor     todos                 ninguna
    analista    solo concedidos       solo si la concesión es 'ver_credenciales'

Ninguna concesión hereda hacia los hijos: conceder un servidor físico no da
acceso a sus hipervisores ni a sus máquinas virtuales (se conceden aparte).
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    ACTIVO_FISICO,
    ACTIVO_HIPERVISOR,
    ACTIVO_VM,
    NIVEL_VER_CREDENCIALES,
    ROL_ADMIN,
    ROL_ANALISTA,
    ROL_AUDITOR,
    ROL_OPERADOR,
    ConcesionAcceso,
    Credencial,
    Usuario,
    ahora_utc,
)

# Roles con visibilidad total del inventario (sin necesidad de concesiones).
ROLES_ACCESO_TOTAL = (ROL_ADMIN, ROL_OPERADOR, ROL_AUDITOR)


def _columna_activo(tipo: str):
    return {
        ACTIVO_FISICO: ConcesionAcceso.servidor_fisico_id,
        ACTIVO_HIPERVISOR: ConcesionAcceso.hipervisor_id,
        ACTIVO_VM: ConcesionAcceso.maquina_virtual_id,
    }[tipo]


def concesion_vigente(db: Session, usuario_id: int, tipo: str, activo_id: int) -> ConcesionAcceso | None:
    """Devuelve la concesión vigente del usuario sobre el activo, o None."""
    columna = _columna_activo(tipo)
    concesion = db.scalar(
        select(ConcesionAcceso).where(
            ConcesionAcceso.usuario_id == usuario_id,
            columna == activo_id,
        )
    )
    if concesion is None:
        return None
    if concesion.expira_en is None or concesion.expira_en > ahora_utc():
        return concesion
    return None


def puede_ver_activo(db: Session, usuario: Usuario, tipo: str, activo_id: int) -> bool:
    """¿Puede el usuario ver el activo (metadatos y lista de credenciales)?"""
    if usuario.rol in ROLES_ACCESO_TOTAL:
        return True
    if usuario.rol == ROL_ANALISTA:
        return concesion_vigente(db, usuario.id, tipo, activo_id) is not None
    return False


def puede_revelar_en_activo(db: Session, usuario: Usuario, tipo: str, activo_id: int) -> bool:
    """¿Puede el usuario revelar/copiar credenciales de este activo?"""
    if usuario.rol in (ROL_ADMIN, ROL_OPERADOR):
        return True
    if usuario.rol == ROL_AUDITOR:
        return False
    if usuario.rol == ROL_ANALISTA:
        concesion = concesion_vigente(db, usuario.id, tipo, activo_id)
        return concesion is not None and concesion.nivel == NIVEL_VER_CREDENCIALES
    return False


def _tipo_y_id_de_credencial(credencial: Credencial) -> tuple[str, int]:
    if credencial.servidor_fisico_id is not None:
        return ACTIVO_FISICO, credencial.servidor_fisico_id
    if credencial.hipervisor_id is not None:
        return ACTIVO_HIPERVISOR, credencial.hipervisor_id
    return ACTIVO_VM, credencial.maquina_virtual_id  # type: ignore[return-value]


def puede_ver_credencial(db: Session, usuario: Usuario, credencial: Credencial) -> bool:
    tipo, activo_id = _tipo_y_id_de_credencial(credencial)
    return puede_ver_activo(db, usuario, tipo, activo_id)


def puede_revelar_credencial(db: Session, usuario: Usuario, credencial: Credencial) -> bool:
    tipo, activo_id = _tipo_y_id_de_credencial(credencial)
    return puede_revelar_en_activo(db, usuario, tipo, activo_id)


def concesiones_vigentes_de_usuario(db: Session, usuario_id: int) -> list[ConcesionAcceso]:
    """Concesiones no expiradas de un usuario (para su panel)."""
    concesiones = db.scalars(
        select(ConcesionAcceso).where(ConcesionAcceso.usuario_id == usuario_id)
    ).all()
    return [c for c in concesiones if c.esta_vigente()]


def concesiones_de_activo(db: Session, tipo: str, activo_id: int) -> list[ConcesionAcceso]:
    """Concesiones existentes sobre un activo (para el panel de gestión del admin)."""
    columna = _columna_activo(tipo)
    return list(
        db.scalars(
            select(ConcesionAcceso).where(columna == activo_id).order_by(ConcesionAcceso.creado_en)
        ).all()
    )


def analistas_activos(db: Session) -> list[Usuario]:
    """Analistas activos, para el selector del panel de concesión del admin."""
    return list(
        db.scalars(
            select(Usuario)
            .where(Usuario.rol == ROL_ANALISTA, Usuario.activo.is_(True))
            .order_by(func.lower(Usuario.username))
        ).all()
    )
