"""Panel de métricas de seguridad (roles admin y auditor).

Solo consultas de lectura sobre datos ya existentes; sin dependencias nuevas.
Da visibilidad proactiva del estado de seguridad (rotación, fallos de acceso,
cuentas sin MFA, concesiones por caducar, etc.).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.config import get_settings
from app.database import get_db
from app.deps import render, requiere_permiso
from app.models import (
    ConcesionAcceso,
    Credencial,
    RegistroAuditoria,
    Usuario,
    ahora_utc,
)

router = APIRouter()

VER = Depends(requiere_permiso("metricas.ver"))


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

    rotacion_vencida = contar(
        select(func.count(Credencial.id)).where(Credencial.password_rotada_en < limite_rotacion)
    )
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
    usuarios_bloqueados = contar(
        select(func.count(Usuario.id)).where(Usuario.bloqueado_hasta > ahora)
    )

    cuentas_sin_mfa = db.scalars(
        select(Usuario).where(Usuario.activo.is_(True), Usuario.mfa_habilitado.is_(False))
        .order_by(Usuario.username)
    ).all()

    # Top 10 de accesos a credenciales (revelar + copiar) por usuario, 30 días.
    top_revelados = db.execute(
        select(RegistroAuditoria.username, func.count(RegistroAuditoria.id).label("n"))
        .where(
            RegistroAuditoria.accion.in_([audit.CREDENCIAL_REVELADA, audit.CREDENCIAL_COPIADA]),
            RegistroAuditoria.fecha >= ahora - timedelta(days=30),
        )
        .group_by(RegistroAuditoria.username)
        .order_by(func.count(RegistroAuditoria.id).desc())
        .limit(10)
    ).all()

    concesiones_por_caducar = db.scalars(
        select(ConcesionAcceso).where(
            ConcesionAcceso.expira_en.is_not(None),
            ConcesionAcceso.expira_en > ahora,
            ConcesionAcceso.expira_en <= ahora + timedelta(days=7),
        ).order_by(ConcesionAcceso.expira_en)
    ).all()

    return render(request, "metricas.html", {
        "usuario_actual": usuario,
        "rotacion_vencida": rotacion_vencida,
        "rotacion_max_dias": settings.rotation_max_days,
        "logins_fallidos_24h": logins_fallidos_24h,
        "logins_fallidos_7d": logins_fallidos_7d,
        "usuarios_bloqueados": usuarios_bloqueados,
        "cuentas_sin_mfa": cuentas_sin_mfa,
        "top_revelados": top_revelados,
        "concesiones_por_caducar": concesiones_por_caducar,
    })
