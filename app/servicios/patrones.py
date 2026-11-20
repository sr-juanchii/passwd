"""Reglas de patrón sobre el libro mayor de rotaciones (v1.3.0).

Reglas simples y explicables, sin aprendizaje automático: el valor aquí no está
en detectar lo sutil, sino en que un auditor pueda leer la regla, entender por
qué saltó y discutir el umbral.

**Modo observación.** Las reglas se entregan evaluándose y mostrándose en
métricas, pero **sin notificar**, y así se quedan hasta que los umbrales estén
calibrados con los datos reales de la instalación. En un inventario pequeño,
«concentración» y «fuera de horario» saltan constantemente, y una regla que
avisa de más acaba filtrada: se pierde la señal justo cuando hace falta. El
ajuste ``rotacion_patrones_modo_observacion`` gobierna ese paso.

Todas las ventanas se miden en UTC, que es como se almacenan las fechas. Una
zona horaria configurable para «fuera de horario» llega con la operación
desatendida, cuando haya rotaciones automáticas a las que aplicarla.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import ROT_CERRADA, RotacionCredencial, ahora_utc
from app.servicios.rotacion import umbral_temprana

# Ventana de análisis y umbrales por defecto.
VENTANA_DIAS = 30
TEMPRANAS_MIN = 3            # rotaciones tempranas en la ventana para señalar
CONCENTRACION_SOLICITANTE = 5  # solicitudes de una misma persona en 24 h
CONCENTRACION_CREDENCIAL = 3   # rotaciones sobre la misma credencial en 7 días
REVISION_VENCIDA_DIAS = 7      # emergencia sin revisar que ya lleva demasiado

# Horario laboral de referencia (UTC) para la regla de fuera de horario.
HORA_INICIO = 7
HORA_FIN = 20


def modo_observacion() -> bool:
    """¿Las reglas solo observan (no notifican)?"""
    return bool(get_settings().rotacion_patrones_modo_observacion)


def _senal(regla: str, etiqueta: str, descripcion: str, casos: int, severidad: str = "aviso") -> dict:
    return {"regla": regla, "etiqueta": etiqueta, "descripcion": descripcion,
            "casos": casos, "severidad": severidad}


def evaluar(db: Session) -> list[dict]:
    """Devuelve las señales activas. Lista vacía = nada que mirar."""
    ahora = ahora_utc()
    desde = ahora - timedelta(days=VENTANA_DIAS)
    senales: list[dict] = []

    cerradas = list(db.scalars(
        select(RotacionCredencial)
        .where(RotacionCredencial.estado == ROT_CERRADA,
               RotacionCredencial.confirmado_en.is_not(None),
               RotacionCredencial.confirmado_en >= desde)
    ).all())

    # 1. Rotaciones tempranas repetidas. Una contraseña que se cambia muy por
    #    debajo de su vigencia puede ser higiene; varias seguidas suelen ser otra
    #    cosa (una fuga que se intenta tapar, o un proceso mal entendido).
    umbral = umbral_temprana()
    tempranas = [r for r in cerradas if r.dias_al_rotar is not None and r.dias_al_rotar < umbral]
    if len(tempranas) >= TEMPRANAS_MIN:
        senales.append(_senal(
            "tempranas_repetidas", "Rotaciones tempranas repetidas",
            f"{len(tempranas)} rotación(es) por debajo de {umbral} día(s) de antigüedad "
            f"en los últimos {VENTANA_DIAS} días.",
            len(tempranas),
        ))

    # 2. Fuera de horario. No es sospechoso por sí solo —los cambios se hacen en
    #    ventanas de mantenimiento— pero sí es contexto cuando coincide con otra señal.
    fuera = [
        r for r in cerradas
        if r.confirmado_en.weekday() >= 5 or not (HORA_INICIO <= r.confirmado_en.hour < HORA_FIN)
    ]
    if fuera:
        senales.append(_senal(
            "fuera_de_horario", "Rotaciones fuera de horario",
            f"{len(fuera)} rotación(es) confirmadas en fin de semana o fuera de "
            f"{HORA_INICIO:02d}:00–{HORA_FIN:02d}:00 UTC.",
            len(fuera), severidad="informativo",
        ))

    # 3. Concentración: ráfagas del mismo solicitante o sobre la misma credencial.
    hace_un_dia = ahora - timedelta(days=1)
    rafagas = db.execute(
        select(RotacionCredencial.solicitado_por_username, func.count(RotacionCredencial.id))
        .where(RotacionCredencial.solicitado_en >= hace_un_dia)
        .group_by(RotacionCredencial.solicitado_por_username)
        .having(func.count(RotacionCredencial.id) >= CONCENTRACION_SOLICITANTE)
    ).all()
    if rafagas:
        detalle = ", ".join(f"{nombre} ({n})" for nombre, n in rafagas)
        senales.append(_senal(
            "concentracion_solicitante", "Ráfaga de solicitudes",
            f"En 24 h: {detalle}. Umbral: {CONCENTRACION_SOLICITANTE} solicitudes.",
            len(rafagas),
        ))

    hace_una_semana = ahora - timedelta(days=7)
    repetidas = db.execute(
        select(RotacionCredencial.credencial_id, func.count(RotacionCredencial.id))
        .where(RotacionCredencial.estado == ROT_CERRADA,
               RotacionCredencial.confirmado_en >= hace_una_semana,
               RotacionCredencial.credencial_id.is_not(None))
        .group_by(RotacionCredencial.credencial_id)
        .having(func.count(RotacionCredencial.id) >= CONCENTRACION_CREDENCIAL)
    ).all()
    if repetidas:
        senales.append(_senal(
            "concentracion_credencial", "Rotaciones repetidas sobre una credencial",
            f"{len(repetidas)} credencial(es) rotadas {CONCENTRACION_CREDENCIAL} veces o más "
            "en 7 días.",
            len(repetidas),
        ))

    # 4. Abuso de la vía de emergencia. La salida de un solo administrador existe
    #    para que la contención no ocurra fuera del sistema; si deja de ser
    #    excepcional, deja de ser una salida y pasa a ser el camino habitual.
    emergencias = [r for r in cerradas if r.emergencia_sin_segundo_par]
    maximo = max(get_settings().rotacion_emergencia_max_por_mes, 1)
    if len(emergencias) > maximo:
        senales.append(_senal(
            "abuso_emergencia", "Uso recurrente de la vía de emergencia",
            f"{len(emergencias)} rotación(es) autorizadas sin segundo par en "
            f"{VENTANA_DIAS} días (máximo admitido: {maximo}).",
            len(emergencias), severidad="grave",
        ))

    limite_revision = ahora - timedelta(days=REVISION_VENCIDA_DIAS)
    vencidas = db.scalar(
        select(func.count(RotacionCredencial.id))
        .where(RotacionCredencial.emergencia_sin_segundo_par.is_(True),
               RotacionCredencial.revisada_en.is_(None),
               RotacionCredencial.solicitado_en < limite_revision)
    ) or 0
    if vencidas:
        senales.append(_senal(
            "revision_emergencia_vencida", "Emergencias sin revisar",
            f"{vencidas} emergencia(s) autorizadas sin segundo par llevan más de "
            f"{REVISION_VENCIDA_DIAS} días sin que otro administrador las revise.",
            int(vencidas), severidad="grave",
        ))

    return senales


def resumen(db: Session) -> dict:
    """Señales activas más el estado del modo observación, para `/metricas`."""
    senales = evaluar(db)
    return {
        "modo_observacion": modo_observacion(),
        "ventana_dias": VENTANA_DIAS,
        "senales": senales,
    }
