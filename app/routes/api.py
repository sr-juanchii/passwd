"""API REST de **solo lectura** autenticada por token (para SIEM/automatización).

Independiente de la interfaz web: se autentica con `Authorization: Bearer
<token>` (sin cookies ni CSRF) y nunca expone secretos (contraseñas, notas).
Pensada para exportar la bitácora a un SIEM y consultar el inventario de forma
programática. Debe usarse siempre sobre TLS.
"""

from __future__ import annotations

import hashlib
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import (
    Hipervisor,
    MaquinaVirtual,
    RegistroAuditoria,
    ServidorFisico,
    TokenApi,
    ahora_utc,
)
from app.security import ratelimit

router = APIRouter(prefix="/api/v1")

MAX_LIMIT = 500


def token_api(request: Request, db: Annotated[Session, Depends(get_db)]) -> TokenApi:
    """Autentica por Bearer token. 401 si falta o es inválido; limita por token."""
    cabecera = request.headers.get("authorization", "")
    if not cabecera.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token de API requerido.",
                            headers={"WWW-Authenticate": "Bearer"})
    valor = cabecera[7:].strip()
    token_hash = hashlib.sha256(valor.encode("ascii")).hexdigest()
    token = db.scalar(select(TokenApi).where(TokenApi.token_hash == token_hash, TokenApi.activo.is_(True)))
    if token is None:
        raise HTTPException(status_code=401, detail="Token inválido o revocado.",
                            headers={"WWW-Authenticate": "Bearer"})
    settings = get_settings()
    if not ratelimit.permitir_intento(
        f"api:{token.id}", limite=settings.login_rate_limit * 4,
        ventana_minutos=settings.login_rate_window_minutes, db=db,
    ):
        raise HTTPException(status_code=429, detail="Límite de peticiones de API alcanzado.")
    token.ultimo_uso = ahora_utc()
    return token


TOKEN = Depends(token_api)


@router.get("/auditoria")
def api_auditoria(
    db: Annotated[Session, Depends(get_db)],
    token: Annotated[TokenApi, TOKEN],
    desde_id: int = 0,
    accion: str = "",
    limit: int = 100,
):
    """Eventos de auditoría en JSON para ingestión incremental por SIEM.

    Usar `desde_id` (mayor id ya ingerido) para paginar de forma incremental.
    """
    limit = max(1, min(limit, MAX_LIMIT))
    consulta = select(RegistroAuditoria).where(RegistroAuditoria.id > desde_id)
    if accion.strip():
        consulta = consulta.where(RegistroAuditoria.accion == accion.strip())
    registros = db.scalars(consulta.order_by(RegistroAuditoria.id).limit(limit)).all()
    return {
        "eventos": [
            {
                "id": r.id, "fecha": r.fecha.isoformat(), "usuario": r.username,
                "accion": r.accion, "objeto_tipo": r.objeto_tipo, "objeto_id": r.objeto_id,
                "detalle": r.detalle, "direccion_ip": r.direccion_ip, "exito": r.exito,
            }
            for r in registros
        ],
        "ultimo_id": registros[-1].id if registros else desde_id,
    }


@router.get("/inventario")
def api_inventario(
    db: Annotated[Session, Depends(get_db)],
    token: Annotated[TokenApi, TOKEN],
):
    """Inventario en JSON (sin credenciales ni notas: nunca expone secretos)."""
    servidores = db.scalars(select(ServidorFisico).order_by(ServidorFisico.nombre)).all()
    hipervisores = db.scalars(select(Hipervisor).order_by(Hipervisor.nombre)).all()
    vms = db.scalars(select(MaquinaVirtual).order_by(MaquinaVirtual.nombre)).all()

    def _srv(s: ServidorFisico) -> dict:
        return {"id": s.id, "nombre": s.nombre, "estado": s.estado,
                "sistema_operativo": s.sistema_operativo, "ip_gestion": s.ip_gestion,
                "etiquetas": s.lista_etiquetas}

    def _hv(h: Hipervisor) -> dict:
        return {"id": h.id, "nombre": h.nombre, "plataforma": h.plataforma, "version": h.version,
                "estado": h.estado, "ip_gestion": h.ip_gestion, "marca_modelo": h.marca_modelo,
                "ubicacion": h.ubicacion, "ram": h.ram, "cpu": h.cpu,
                "almacenamiento": h.almacenamiento, "numero_serie": h.numero_serie,
                "garantia_hasta": h.garantia_hasta, "proveedor": h.proveedor,
                "etiquetas": h.lista_etiquetas}

    return {
        "servidores_fisicos": [_srv(s) for s in servidores],
        "hipervisores": [_hv(h) for h in hipervisores],
        "maquinas_virtuales": [{"id": v.id, "nombre": v.nombre, "estado": v.estado,
                                "sistema_operativo": v.sistema_operativo, "ip": v.ip,
                                "hipervisor_id": v.hipervisor_id} for v in vms],
    }
