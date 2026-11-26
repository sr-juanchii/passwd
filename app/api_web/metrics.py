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

from app import access, audit
from app.api_web.deps import requiere_permiso_json
from app.api_web.serializers import _iso, serializar_concesion
from app.config import get_settings
from app.database import get_db
from app.models import ConcesionAcceso, Credencial, RegistroAuditoria, Usuario, ahora_utc
from app.servicios import agentes as servicio_agentes
from app.servicios import patrones
from app.servicios import rotacion as servicio_rotacion

router = APIRouter()

VER = Depends(requiere_permiso_json("metricas.ver"))


def _agentes(db: Session, usuario: Usuario) -> dict | None:
    """Parque de agentes: cuántos hay en cada estado y cuáles piden atención.

    Solo con los agentes activados. Los recuentos y la lista respetan el control
    de acceso por objeto: un activo restringido no existe para quien no lo alcanza.
    """
    if not servicio_agentes.habilitados():
        return None
    servicio_rotacion.expirar_trabajos(db)
    visibles = [a for a in servicio_agentes.vigentes(db)
                if access.puede_ver_activo(db, usuario, a.tipo_activo, a.activo_id)]
    coberturas = {a.id: servicio_agentes.cobertura(a) for a in visibles}
    estados = (servicio_agentes.COBERTURA_CONECTADO, servicio_agentes.COBERTURA_SIN_CONTACTO,
               servicio_agentes.COBERTURA_CADUCADO, servicio_agentes.COBERTURA_PENDIENTE)
    return {
        "por_cobertura": {e: sum(1 for c in coberturas.values() if c == e) for e in estados},
        "atencion": [
            {"id": a.id, "nombre": a.nombre, "activo": servicio_agentes.nombre_activo(a),
             "tipo_activo": a.tipo_activo, "activo_id": a.activo_id,
             "cobertura": coberturas[a.id], "ultimo_contacto_en": _iso(a.ultimo_contacto_en)}
            for a in visibles if coberturas[a.id] in servicio_agentes.COBERTURAS_CALLADAS
        ],
        "sin_confirmar": sum(1 for t in servicio_rotacion.trabajos_sin_confirmar(db)
                             if access.puede_ver_credencial(db, usuario, t.credencial)),
    }


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
        # Gobernanza de rotación: qué espera decisión y qué señalan las reglas.
        "gobernanza_rotacion": {
            "pendientes_de_autorizar": len(servicio_rotacion.pendientes_de_autorizar(db)),
            "pendientes_de_ejecutar": len(servicio_rotacion.pendientes_de_ejecutar(db)),
            "revisiones_pendientes": len(servicio_rotacion.revisiones_pendientes(db)),
        },
        "patrones_rotacion": patrones.resumen(db),
        # Agentes de rotación (v1.4.0); null con los agentes apagados.
        "agentes": _agentes(db, usuario),
        "logins_fallidos_24h": logins_fallidos_24h,
        "logins_fallidos_7d": logins_fallidos_7d,
        "bloqueados": bloqueados,
        "sin_mfa": sin_mfa,
        "top_accesos": top_accesos,
        "concesiones_por_caducar": concesiones_por_caducar,
        "rotacion_max_dias": settings.rotation_max_days,
    }
