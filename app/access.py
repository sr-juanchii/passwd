"""Control de acceso por objeto (concesiones por activo y restricciones).

Complementa el RBAC estático (`app/rbac.py`) con dos mecanismos por objeto:

1. **Concesiones** (rol ``analista``): default-deny; solo ve/usa los activos
   que un administrador le concede explícitamente, con nivel y caducidad.
2. **Restricciones** (``restringido=True``, lo fija solo el administrador con
   el permiso ``inventario.restringir``): el activo queda oculto para los
   OPERADORES, que lo tratan como inexistente (404 en toda operación, fuera
   de listados, búsqueda y export). El AUDITOR sí ve que el activo existe
   (su función es la supervisión del inventario completo), pero —como
   siempre— no puede revelar ninguna contraseña.

Reglas (least privilege):

    rol         ver activo                     revelar/copiar credenciales
    ---------   ----------------------------   ----------------------------
    admin       todos                          todas
    operador    todos salvo restringidos       todas salvo restringidas
    auditor     todos (restringidos incl.)     ninguna
    analista    solo concedidos                solo si la concesión es 'ver_credenciales'

Ninguna concesión hereda hacia los hijos: conceder un servidor físico no da
acceso a sus hipervisores ni a sus máquinas virtuales (se conceden aparte).
La **restricción sí hereda hacia abajo** (deny-hereda): restringir un
hipervisor restringe también sus máquinas virtuales. Una concesión explícita
de un administrador a un analista prevalece sobre la restricción: es una
decisión deliberada del propio administrador.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    ACTIVO_DISPOSITIVO,
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
    DispositivoRed,
    Hipervisor,
    MaquinaVirtual,
    ServidorFisico,
    Usuario,
    ahora_utc,
)

# Roles con visibilidad total del inventario (sin necesidad de concesiones).
# Para el operador esa visibilidad excluye los activos restringidos; el
# auditor los ve (supervisión completa) aunque nunca revela contraseñas.
ROLES_ACCESO_TOTAL = (ROL_ADMIN, ROL_OPERADOR, ROL_AUDITOR)

# Modelos de nivel superior que llevan la marca `restringido`.
_MODELOS_RESTRINGIBLES = {
    ACTIVO_FISICO: ServidorFisico,
    ACTIVO_HIPERVISOR: Hipervisor,
    ACTIVO_DISPOSITIVO: DispositivoRed,
}


def activo_restringido(db: Session, tipo: str, activo_id: int) -> bool:
    """¿Está el activo restringido a administradores?

    Las máquinas virtuales heredan la restricción de su hipervisor (deny
    hereda hacia abajo, al contrario que las concesiones).
    """
    if tipo == ACTIVO_VM:
        vm = db.get(MaquinaVirtual, activo_id)
        if vm is None:
            return False
        hipervisor = db.get(Hipervisor, vm.hipervisor_id)
        return bool(hipervisor is not None and hipervisor.restringido)
    modelo = _MODELOS_RESTRINGIBLES.get(tipo)
    if modelo is None:
        return False
    activo = db.get(modelo, activo_id)
    return bool(activo is not None and activo.restringido)


def _columna_activo(tipo: str):
    return {
        ACTIVO_FISICO: ConcesionAcceso.servidor_fisico_id,
        ACTIVO_HIPERVISOR: ConcesionAcceso.hipervisor_id,
        ACTIVO_VM: ConcesionAcceso.maquina_virtual_id,
        ACTIVO_DISPOSITIVO: ConcesionAcceso.dispositivo_red_id,
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
    if usuario.rol in (ROL_ADMIN, ROL_AUDITOR):
        return True
    if usuario.rol == ROL_OPERADOR:
        return not activo_restringido(db, tipo, activo_id)
    if usuario.rol == ROL_ANALISTA:
        return concesion_vigente(db, usuario.id, tipo, activo_id) is not None
    return False


def puede_revelar_en_activo(db: Session, usuario: Usuario, tipo: str, activo_id: int) -> bool:
    """¿Puede el usuario revelar/copiar credenciales de este activo?"""
    if usuario.rol == ROL_ADMIN:
        return True
    if usuario.rol == ROL_OPERADOR:
        return not activo_restringido(db, tipo, activo_id)
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
    if credencial.dispositivo_red_id is not None:
        return ACTIVO_DISPOSITIVO, credencial.dispositivo_red_id
    return ACTIVO_VM, credencial.maquina_virtual_id  # type: ignore[return-value]


def puede_ver_credencial(db: Session, usuario: Usuario, credencial: Credencial) -> bool:
    tipo, activo_id = _tipo_y_id_de_credencial(credencial)
    return puede_ver_activo(db, usuario, tipo, activo_id)


def puede_revelar_credencial(db: Session, usuario: Usuario, credencial: Credencial) -> bool:
    tipo, activo_id = _tipo_y_id_de_credencial(credencial)
    return puede_revelar_en_activo(db, usuario, tipo, activo_id)


def ids_activos_concedidos(db: Session, usuario: Usuario, tipo: str) -> list[int] | None:
    """IDs de activos del tipo que el usuario puede ver, o ``None`` si ve todos.

    Pensado para filtrar consultas EN SQL antes de aplicar un ``LIMIT`` (p. ej.
    la búsqueda global): ``None`` significa «sin filtro» (administrador y
    auditor, u operador sin activos restringidos); una lista —posiblemente
    vacía— restringe a lo visible: las concesiones vigentes del analista, o
    el inventario sin los activos restringidos para el operador.
    """
    if usuario.rol in (ROL_ADMIN, ROL_AUDITOR):
        return None
    if usuario.rol == ROL_OPERADOR:
        return _ids_visibles_sin_restringidos(db, tipo)
    if usuario.rol != ROL_ANALISTA:
        return []
    columna = _columna_activo(tipo)
    concesiones = db.scalars(
        select(ConcesionAcceso).where(
            ConcesionAcceso.usuario_id == usuario.id,
            columna.is_not(None),
        )
    ).all()
    return [getattr(c, columna.key) for c in concesiones if c.esta_vigente()]


def _ids_visibles_sin_restringidos(db: Session, tipo: str) -> list[int] | None:
    """IDs no restringidos del tipo, o ``None`` si no hay nada restringido.

    Devolver ``None`` en el caso común (sin restricciones) evita construir
    listas de IDs innecesarias en cada búsqueda.
    """
    if tipo == ACTIVO_VM:
        restringidos = db.scalars(
            select(Hipervisor.id).where(Hipervisor.restringido.is_(True))
        ).all()
        if not restringidos:
            return None
        return list(db.scalars(
            select(MaquinaVirtual.id).where(MaquinaVirtual.hipervisor_id.not_in(restringidos))
        ).all())
    modelo = _MODELOS_RESTRINGIBLES[tipo]
    hay_restringidos = db.scalar(
        select(func.count(modelo.id)).where(modelo.restringido.is_(True))
    ) or 0
    if not hay_restringidos:
        return None
    return list(db.scalars(select(modelo.id).where(modelo.restringido.is_(False))).all())


def concesiones_vigentes_de_usuario(db: Session, usuario_id: int) -> list[ConcesionAcceso]:
    """Concesiones no expiradas de un usuario (para su panel).

    Precarga los cuatro activos posibles (``selectinload``) para que leer
    ``nombre_activo``/``tipo_activo`` por fila no dispare una consulta por
    concesión (evita el N+1 en el panel del analista).
    """
    concesiones = db.scalars(
        select(ConcesionAcceso)
        .where(ConcesionAcceso.usuario_id == usuario_id)
        .options(
            selectinload(ConcesionAcceso.servidor_fisico),
            selectinload(ConcesionAcceso.hipervisor),
            selectinload(ConcesionAcceso.maquina_virtual),
            selectinload(ConcesionAcceso.dispositivo_red),
        )
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
