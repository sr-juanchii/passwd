"""Panel de métricas de seguridad en JSON (roles admin y auditor).

Replica las consultas de ``app/routes/metrics.py`` pero devuelve los datos
estructurados que consume el frontend (listas y conteos), sin secretos.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.api_web.deps import requiere_permiso_json
from app.api_web.serializers import _iso, serializar_concesion
from app.config import get_settings
from app.database import get_db
from app.models import ConcesionAcceso, Credencial, RegistroAuditoria, Usuario, ahora_utc

router = APIRouter()

VER = Depends(requiere_permiso_json("metricas.ver"))


@router.get("/metricas")
def metricas(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, VER],
):
    ahora = ahora_utc()
    settings = get_settings()
    limite_rotacion = ahora - timedelta(days=settings.rotation_max_days)

    def contar(consulta) -> int:
        return db.scalar(consulta) or 0

    vencidas = db.scalars(
        select(Credencial)
        .where(Credencial.password_rotada_en < limite_rotacion)
        .order_by(Credencial.password_rotada_en)
        .limit(100)
    ).all()
    rotacion_vencida = [
        {
            "id": c.id,
            "activo": c.nombre_activo,
            "tipo": c.tipo_activo,
            "usuario_acceso": c.usuario_acceso,
            "dias": c.dias_sin_rotar,
        }
        for c in vencidas
    ]

    logins_fallidos_24h = contar(
        select(func.count(RegistroAuditoria.id)).where(
            RegistroAuditoria.accion == audit.LOGIN_FALLIDO,
            RegistroAuditoria.fecha >= ahora - timedelta(hours=24),
        )
    )
    logins_fallidos_7d = contar(
        select(func.count(RegistroAuditoria.id)).where(
            RegistroAuditoria.accion == audit.LOGIN_FALLIDO,
            RegistroAuditoria.fecha >= ahora - timedelta(days=7),
        )
    )

    bloqueados = [
        {"username": u.username, "bloqueado_hasta": _iso(u.bloqueado_hasta)}
        for u in db.scalars(
            select(Usuario).where(Usuario.bloqueado_hasta > ahora).order_by(Usuario.username)
        ).all()
    ]

    sin_mfa = [
        {"username": u.username, "rol": u.rol}
        for u in db.scalars(
            select(Usuario)
            .where(Usuario.activo.is_(True), Usuario.mfa_habilitado.is_(False))
            .order_by(Usuario.username)
        ).all()
    ]

    top_accesos = [
        {"username": fila.username, "accesos": fila.n}
        for fila in db.execute(
            select(RegistroAuditoria.username, func.count(RegistroAuditoria.id).label("n"))
            .where(
                RegistroAuditoria.accion.in_([audit.CREDENCIAL_REVELADA, audit.CREDENCIAL_COPIADA]),
                RegistroAuditoria.fecha >= ahora - timedelta(days=30),
            )
            .group_by(RegistroAuditoria.username)
            .order_by(func.count(RegistroAuditoria.id).desc())
            .limit(10)
        ).all()
    ]

    concesiones_por_caducar = [
        serializar_concesion(c)
        for c in db.scalars(
            select(ConcesionAcceso)
            .where(
                ConcesionAcceso.expira_en.is_not(None),
                ConcesionAcceso.expira_en > ahora,
                ConcesionAcceso.expira_en <= ahora + timedelta(days=7),
            )
            .order_by(ConcesionAcceso.expira_en)
        ).all()
    ]

    return {
        "rotacion_vencida": rotacion_vencida,
        "logins_fallidos_24h": logins_fallidos_24h,
        "logins_fallidos_7d": logins_fallidos_7d,
        "bloqueados": bloqueados,
        "sin_mfa": sin_mfa,
        "top_accesos": top_accesos,
        "concesiones_por_caducar": concesiones_por_caducar,
        "rotacion_max_dias": settings.rotation_max_days,
    }
