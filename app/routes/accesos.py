"""Gestión de concesiones de acceso por activo (solo administradores).

Un administrador concede a un analista acceso a un activo concreto, con un
nivel (ver / ver+credenciales) y caducidad opcional. Conceder y revocar quedan
auditados. La revocación borra la concesión: la traza histórica vive en la
bitácora de auditoría.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, avisos
from app.database import get_db
from app.deps import requiere_permiso, verificar_csrf
from app.models import (
    ACTIVO_DISPOSITIVO,
    ACTIVO_FISICO,
    ACTIVO_HIPERVISOR,
    ACTIVO_VM,
    NIVEL_VER,
    NIVELES_CONCESION,
    ROL_ANALISTA,
    ConcesionAcceso,
    DispositivoRed,
    Hipervisor,
    MaquinaVirtual,
    ServidorFisico,
    Usuario,
    ahora_utc,
)

router = APIRouter()

GESTIONAR = Depends(requiere_permiso("accesos.gestionar"))

# tipo de activo → (modelo, prefijo de URL de detalle, columna FK en ConcesionAcceso)
_ACTIVOS = {
    ACTIVO_FISICO: (ServidorFisico, "/servidores", "servidor_fisico_id"),
    ACTIVO_HIPERVISOR: (Hipervisor, "/hipervisores", "hipervisor_id"),
    ACTIVO_VM: (MaquinaVirtual, "/vms", "maquina_virtual_id"),
    ACTIVO_DISPOSITIVO: (DispositivoRed, "/dispositivos", "dispositivo_red_id"),
}


def _resolver_activo(db: Session, tipo: str, activo_id: int):
    if tipo not in _ACTIVOS:
        raise HTTPException(status_code=400, detail="Tipo de activo inválido.")
    modelo, prefijo, columna = _ACTIVOS[tipo]
    instancia = db.get(modelo, activo_id)
    if instancia is None:
        raise HTTPException(status_code=404, detail="El activo indicado no existe.")
    return instancia, f"{prefijo}/{activo_id}", columna


@router.post("/accesos/conceder", dependencies=[Depends(verificar_csrf)])
def conceder(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[Usuario, GESTIONAR],
    usuario_id: Annotated[int, Form()] = 0,
    tipo: Annotated[str, Form()] = "",
    activo_id: Annotated[int, Form()] = 0,
    nivel: Annotated[str, Form()] = NIVEL_VER,
    expira_dias: Annotated[str, Form()] = "",
):
    instancia, url_volver, columna = _resolver_activo(db, tipo, activo_id)

    objetivo = db.get(Usuario, usuario_id)
    if objetivo is None or objetivo.rol != ROL_ANALISTA or not objetivo.activo:
        raise HTTPException(status_code=400, detail="El destinatario debe ser un analista activo.")
    if nivel not in NIVELES_CONCESION:
        raise HTTPException(status_code=400, detail="Nivel de acceso inválido.")

    expira_en = None
    if expira_dias.strip():
        if not expira_dias.strip().isdigit() or int(expira_dias) <= 0:
            raise HTTPException(status_code=400, detail="La caducidad debe ser un número de días positivo.")
        expira_en = ahora_utc() + timedelta(days=int(expira_dias))

    # Upsert: si ya hay una concesión para (usuario, activo), se actualiza.
    existente = db.scalar(
        select(ConcesionAcceso).where(
            ConcesionAcceso.usuario_id == usuario_id,
            getattr(ConcesionAcceso, columna) == activo_id,
        )
    )
    if existente is not None:
        existente.nivel = nivel
        existente.expira_en = expira_en
        existente.concedido_por_id = admin.id
        accion_detalle = "actualizada"
    else:
        db.add(ConcesionAcceso(
            usuario_id=usuario_id, nivel=nivel, expira_en=expira_en,
            concedido_por_id=admin.id,
            **{columna: activo_id},
        ))
        accion_detalle = "creada"

    caduca = f"; caduca {expira_en:%d/%m/%Y}" if expira_en else "; sin caducidad"
    audit.registrar(db, audit.ACCESO_CONCEDIDO, request=request, usuario=admin,
                    objeto_tipo=tipo, objeto_id=activo_id,
                    detalle=f"Concesión {accion_detalle} a {objetivo.username} sobre "
                            f"{instancia.nombre} (nivel {nivel}{caduca})")
    # El titular debe saber siempre qué acceso tiene: un cambio de permisos que no
    # reconozca es un indicio de uso indebido de una cuenta administrativa.
    avisos.aviso_concesion(db, objetivo, tipo, activo_id, concedida=True, nivel=nivel)
    return RedirectResponse(f"{url_volver}?msg={quote('Acceso concedido.')}", status_code=303)


@router.post("/accesos/{concesion_id}/revocar", dependencies=[Depends(verificar_csrf)])
def revocar(
    request: Request,
    concesion_id: int,
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[Usuario, GESTIONAR],
):
    concesion = db.get(ConcesionAcceso, concesion_id)
    if concesion is None:
        raise HTTPException(status_code=404, detail="La concesión no existe.")
    # Capturamos todo ANTES de borrar (después la fila queda inaccesible).
    tipo = concesion.tipo_activo
    activo_id = _id_activo(concesion)
    detalle = (f"Acceso de {concesion.usuario.username} sobre {concesion.nombre_activo} "
               f"(nivel {concesion.nivel}) revocado")
    _, url_volver, _ = _resolver_activo(db, tipo, activo_id)
    afectado = concesion.usuario
    db.delete(concesion)
    audit.registrar(db, audit.ACCESO_REVOCADO, request=request, usuario=admin,
                    objeto_tipo=tipo, objeto_id=activo_id, detalle=detalle)
    avisos.aviso_concesion(db, afectado, tipo, activo_id, concedida=False)
    return RedirectResponse(f"{url_volver}?msg={quote('Acceso revocado.')}", status_code=303)


def _id_activo(concesion: ConcesionAcceso) -> int:
    return (
        concesion.servidor_fisico_id
        or concesion.hipervisor_id
        or concesion.maquina_virtual_id
        or concesion.dispositivo_red_id  # type: ignore[return-value]
    )
