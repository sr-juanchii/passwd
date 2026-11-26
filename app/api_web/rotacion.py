"""Gobernanza de rotación en JSON (`/api/web/rotacion`).

Traduce HTTP ↔ ``app/servicios/rotacion.py`` y nada más: ninguna regla del ciclo
vive aquí. Si una condición hay que comprobarla —quién puede autorizar, si el
motivo basta, si la ventana de emergencia venció— se comprueba en el servicio,
porque la interfaz clásica usa exactamente las mismas funciones.

El control de acceso por objeto sí se resuelve en la frontera, como en el resto
de la API: un operador no debe siquiera saber que existe una solicitud sobre un
activo restringido.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import access, audit, avisos
from app.api_web.deps import requiere_permiso_json, verificar_csrf_json
from app.database import get_db
from app.models import (
    ROT_TIPO_MANUAL,
    Credencial,
    RotacionCredencial,
    TrabajoRotacion,
    Usuario,
)
from app.servicios import patrones
from app.servicios import rotacion as servicio
from app.servicios.autenticacion import ErrorReautenticacion, reautenticar
from app.servicios.rotacion import ErrorRotacion

router = APIRouter()

VER = Depends(requiere_permiso_json("rotacion.ver"))
SOLICITAR = Depends(requiere_permiso_json("rotacion.solicitar"))
AUTORIZAR = Depends(requiere_permiso_json("rotacion.autorizar"))
REVISAR = Depends(requiere_permiso_json("rotacion.revisar"))
CSRF = Depends(verificar_csrf_json)


class SolicitudCrear(BaseModel):
    credencial_id: int = 0
    motivo: str = ""
    tipo: str = ROT_TIPO_MANUAL


class Reautenticacion(BaseModel):
    password: str = ""
    codigo: str = ""


class AutorizarLote(Reautenticacion):
    ids: list[int] = []


class MotivoCuerpo(BaseModel):
    motivo: str = ""


class NotaCuerpo(BaseModel):
    nota: str = ""


class AplicarManual(BaseModel):
    password: str = ""


class ResolverTrabajo(Reautenticacion):
    aplicada: bool = False


def _error(exc: ErrorRotacion | ErrorReautenticacion) -> HTTPException:
    return HTTPException(status_code=exc.codigo, detail=exc.mensaje)


def _serializar(rotacion: RotacionCredencial) -> dict:
    """Vista de una rotación. Nunca incluye contraseñas: no las tiene."""
    return {
        "id": rotacion.id,
        "credencial_id": rotacion.credencial_id,
        "activo_nombre": rotacion.activo_nombre,
        "usuario_acceso": rotacion.usuario_acceso,
        "servicio": rotacion.servicio,
        "estado": rotacion.estado,
        "tipo": rotacion.tipo,
        "motivo": rotacion.motivo,
        "solicitado_por": rotacion.solicitado_por_username,
        "solicitado_en": rotacion.solicitado_en.isoformat(),
        "dias_al_solicitar": rotacion.dias_al_solicitar,
        "dias_al_autorizar": rotacion.dias_al_autorizar,
        "temprana": rotacion.temprana,
        "autorizado_por": rotacion.autorizado_por_username,
        "autorizado_en": rotacion.autorizado_en.isoformat() if rotacion.autorizado_en else None,
        "reautenticado": rotacion.reautenticado,
        "emergencia_sin_segundo_par": rotacion.emergencia_sin_segundo_par,
        "revision_pendiente": rotacion.revision_pendiente,
        "revisada_en": rotacion.revisada_en.isoformat() if rotacion.revisada_en else None,
        "nota_revision": rotacion.nota_revision,
        "motivo_rechazo": rotacion.motivo_rechazo,
        "fecha_programada": (rotacion.fecha_programada.isoformat()
                             if rotacion.fecha_programada else None),
        "confirmado_en": rotacion.confirmado_en.isoformat() if rotacion.confirmado_en else None,
        "dias_al_rotar": rotacion.dias_al_rotar,
        "desvio_dias": rotacion.desvio_dias,
        "resultado": rotacion.resultado,
        "via": rotacion.via,
        "verificacion": rotacion.verificacion,
        "detalle_error": rotacion.detalle_error,
        "agente_nombre": rotacion.agente_nombre,
    }


def _serializar_trabajo(trabajo: TrabajoRotacion | None) -> dict | None:
    """Estado del trabajo de un agente. Jamás sus secretos."""
    if trabajo is None:
        return None
    return {
        "id": trabajo.id,
        "rotacion_id": trabajo.rotacion_id,
        "credencial_id": trabajo.credencial_id,
        "estado": trabajo.estado,
        "agente": trabajo.agente.nombre,
        "activo_nombre": trabajo.credencial.nombre_activo,
        "usuario_acceso": trabajo.credencial.usuario_acceso,
        "ventana_expira_en": trabajo.ventana_expira_en.isoformat(),
        "entregado_en": trabajo.entregado_en.isoformat() if trabajo.entregado_en else None,
        "intentos": trabajo.intentos,
        "sin_confirmar": servicio.sin_confirmar(trabajo),
    }


def _credencial_visible(db: Session, usuario: Usuario, credencial_id: int) -> Credencial:
    credencial = db.get(Credencial, credencial_id)
    if credencial is None or not access.puede_ver_credencial(db, usuario, credencial):
        # Mismo 404 en ambos casos: un activo restringido es inexistente para
        # quien no lo alcanza, y distinguirlo lo convertiría en un oráculo.
        raise HTTPException(status_code=404, detail="La credencial no existe.")
    return credencial


def _rotacion_visible(db: Session, usuario: Usuario, rotacion_id: int) -> RotacionCredencial:
    rotacion = db.get(RotacionCredencial, rotacion_id)
    if rotacion is None:
        raise HTTPException(status_code=404, detail="La solicitud no existe.")
    if rotacion.credencial_id is not None:
        credencial = db.get(Credencial, rotacion.credencial_id)
        if credencial is not None and not access.puede_ver_credencial(db, usuario, credencial):
            raise HTTPException(status_code=404, detail="La solicitud no existe.")
    return rotacion


def _filtrar_visibles(
    db: Session, usuario: Usuario, rotaciones: list[RotacionCredencial]
) -> list[RotacionCredencial]:
    visibles = []
    for rotacion in rotaciones:
        if rotacion.credencial_id is None:
            visibles.append(rotacion)
            continue
        credencial = db.get(Credencial, rotacion.credencial_id)
        if credencial is None or access.puede_ver_credencial(db, usuario, credencial):
            visibles.append(rotacion)
    return visibles


# ---------------------------------------------------------------------------
# Consulta
# ---------------------------------------------------------------------------


@router.get("/rotacion/panel")
def panel(
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, VER],
):
    """Lo que hay sobre la mesa: por autorizar, por ejecutar y por revisar."""
    # Expiración perezosa: con ventanas de minutos, el barrido periódico llega tarde.
    servicio.expirar_trabajos(db)
    sin_confirmar = servicio.trabajos_sin_confirmar(db)
    return {
        "sin_confirmar": [
            _serializar_trabajo(t) for t in sin_confirmar
            if access.puede_ver_credencial(db, usuario, t.credencial)
        ],
        "pendientes_de_autorizar": [
            _serializar(r) for r in _filtrar_visibles(db, usuario, servicio.pendientes_de_autorizar(db))
        ],
        "pendientes_de_ejecutar": [
            _serializar(r) for r in _filtrar_visibles(db, usuario, servicio.pendientes_de_ejecutar(db))
        ],
        "revisiones_pendientes": [
            _serializar(r) for r in _filtrar_visibles(db, usuario, servicio.revisiones_pendientes(db))
        ],
        # Un logger.warning que nadie lee no cumple lo que promete el manual: la
        # condición se ve también aquí, donde se toman las decisiones.
        "gobernanza": {
            "administradores_activos": servicio.administradores_activos(db),
            "minimo_administradores": servicio.MIN_ADMINISTRADORES,
            "dos_pares_posible": servicio.dos_pares_posible(db),
        },
        "politica": {
            "intervalo_dias": servicio.intervalo_dias(),
            "umbral_temprana_dias": servicio.umbral_temprana(),
            "motivo_min": servicio.MOTIVO_MIN,
            "motivo_reforzado_min": servicio.MOTIVO_REFORZADO_MIN,
        },
        "patrones": patrones.resumen(db),
    }


@router.get("/rotacion/credenciales/{credencial_id}")
def historial_de_credencial(
    credencial_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, VER],
):
    """Línea de tiempo de gobernanza de una credencial."""
    credencial = _credencial_visible(db, usuario, credencial_id)
    servicio.expirar_trabajos(db)
    abierta = servicio.solicitud_abierta(db, credencial.id)
    return {
        "credencial_id": credencial.id,
        "activo_nombre": credencial.nombre_activo,
        "usuario_acceso": credencial.usuario_acceso,
        "via_rotacion": credencial.via_rotacion,
        "usada_por": credencial.usada_por,
        "dias_sin_rotar": credencial.dias_sin_rotar,
        "fecha_programada": servicio.fecha_programada(credencial).isoformat(),
        "temprana_si_se_rota_ahora": servicio.es_temprana(credencial),
        "solicitud_abierta": _serializar(abierta) if abierta is not None else None,
        "trabajo_en_curso": (_serializar_trabajo(servicio.trabajo_de(db, abierta))
                             if abierta is not None else None),
        "historial": [_serializar(r) for r in servicio.linea_de_tiempo(db, credencial.id)],
    }


# ---------------------------------------------------------------------------
# El ciclo
# ---------------------------------------------------------------------------


@router.post("/rotacion/solicitudes", dependencies=[CSRF])
def crear_solicitud(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, SOLICITAR],
    cuerpo: SolicitudCrear,
):
    credencial = _credencial_visible(db, usuario, cuerpo.credencial_id)
    try:
        rotacion = servicio.solicitar(
            db, credencial=credencial, usuario=usuario,
            motivo=cuerpo.motivo, tipo=cuerpo.tipo, request=request,
        )
    except ErrorRotacion as exc:
        raise _error(exc) from exc
    avisos.aviso_rotacion_solicitada(db, rotacion)
    return _serializar(rotacion)


@router.post("/rotacion/solicitudes/{rotacion_id}/autorizar", dependencies=[CSRF])
def autorizar_solicitud(
    request: Request,
    rotacion_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, AUTORIZAR],
    cuerpo: Reautenticacion,
):
    """Autoriza una rotación. Exige contraseña + código de aplicación autenticadora."""
    rotacion = _rotacion_visible(db, usuario, rotacion_id)
    try:
        reautenticar(db, usuario, cuerpo.password, cuerpo.codigo)
    except ErrorReautenticacion as exc:
        audit.registrar(
            db, audit.ACCESO_DENEGADO, request=request, usuario=usuario,
            objeto_tipo="rotacion", objeto_id=rotacion_id,
            detalle="Reautenticación fallida al autorizar una rotación", exito=False,
        )
        db.commit()
        raise _error(exc) from exc
    try:
        servicio.autorizar(db, rotacion=rotacion, usuario=usuario, request=request)
    except ErrorRotacion as exc:
        raise _error(exc) from exc
    avisos.aviso_rotacion_decidida(db, rotacion, autorizada=True)
    if rotacion.emergencia_sin_segundo_par:
        avisos.aviso_emergencia_sin_par(db, rotacion)
    return _serializar(rotacion)


@router.post("/rotacion/solicitudes/autorizar-lote", dependencies=[CSRF])
def autorizar_lote(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, AUTORIZAR],
    cuerpo: AutorizarLote,
):
    """Autoriza varias solicitudes con una sola reautenticación.

    El lote ahorra clics, no controles: cada solicitud se autoriza por separado,
    con su propio asiento en el libro mayor y su propio evento de auditoría, y
    las que incumplen una regla —la propia, por ejemplo— se rechazan una a una
    sin tumbar el resto.
    """
    if not cuerpo.ids:
        raise HTTPException(status_code=400, detail="Indique al menos una solicitud.")
    try:
        reautenticar(db, usuario, cuerpo.password, cuerpo.codigo)
    except ErrorReautenticacion as exc:
        audit.registrar(
            db, audit.ACCESO_DENEGADO, request=request, usuario=usuario,
            detalle="Reautenticación fallida al autorizar rotaciones en lote", exito=False,
        )
        db.commit()
        raise _error(exc) from exc

    autorizadas: list[dict] = []
    rechazadas: list[dict] = []
    for rotacion_id in cuerpo.ids[:100]:
        rotacion = db.get(RotacionCredencial, rotacion_id)
        if rotacion is None:
            rechazadas.append({"id": rotacion_id, "motivo": "La solicitud no existe."})
            continue
        if rotacion.credencial_id is not None:
            credencial = db.get(Credencial, rotacion.credencial_id)
            if credencial is not None and not access.puede_ver_credencial(db, usuario, credencial):
                rechazadas.append({"id": rotacion_id, "motivo": "La solicitud no existe."})
                continue
        try:
            servicio.autorizar(db, rotacion=rotacion, usuario=usuario, request=request)
        except ErrorRotacion as exc:
            rechazadas.append({"id": rotacion_id, "motivo": exc.mensaje})
            continue
        avisos.aviso_rotacion_decidida(db, rotacion, autorizada=True)
        if rotacion.emergencia_sin_segundo_par:
            avisos.aviso_emergencia_sin_par(db, rotacion)
        autorizadas.append(_serializar(rotacion))
    return {"autorizadas": autorizadas, "rechazadas": rechazadas}


@router.post("/rotacion/solicitudes/{rotacion_id}/rechazar", dependencies=[CSRF])
def rechazar_solicitud(
    request: Request,
    rotacion_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, AUTORIZAR],
    cuerpo: MotivoCuerpo,
):
    rotacion = _rotacion_visible(db, usuario, rotacion_id)
    try:
        servicio.rechazar(db, rotacion=rotacion, usuario=usuario,
                          motivo=cuerpo.motivo, request=request)
    except ErrorRotacion as exc:
        raise _error(exc) from exc
    avisos.aviso_rotacion_decidida(db, rotacion, autorizada=False)
    return _serializar(rotacion)


@router.post("/rotacion/solicitudes/{rotacion_id}/cancelar", dependencies=[CSRF])
def cancelar_solicitud(
    request: Request,
    rotacion_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, SOLICITAR],
):
    rotacion = _rotacion_visible(db, usuario, rotacion_id)
    try:
        servicio.cancelar(db, rotacion=rotacion, usuario=usuario, request=request)
    except ErrorRotacion as exc:
        raise _error(exc) from exc
    return _serializar(rotacion)


@router.post("/rotacion/solicitudes/{rotacion_id}/aplicar-manual", dependencies=[CSRF])
def aplicar_manual(
    request: Request,
    rotacion_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, SOLICITAR],
    cuerpo: AplicarManual,
):
    """Registra la contraseña que quedó aplicada a mano en el activo.

    Es el único camino por el que cambia una contraseña del inventario en esta
    versión, y necesita una autorización vigente.
    """
    rotacion = _rotacion_visible(db, usuario, rotacion_id)
    if rotacion.credencial_id is not None:
        _credencial_visible(db, usuario, rotacion.credencial_id)
    try:
        servicio.registrar_rotacion_manual(
            db, rotacion=rotacion, password=cuerpo.password, usuario=usuario, request=request,
        )
    except ErrorRotacion as exc:
        raise _error(exc) from exc
    credencial = rotacion.credencial
    if credencial is not None:
        avisos.aviso_credencial_compartida_actualizada(db, credencial, usuario, password_cambiada=True)
    avisos.aviso_rotacion_aplicada(db, rotacion)
    return _serializar(rotacion)


@router.post("/rotacion/solicitudes/{rotacion_id}/revisar", dependencies=[CSRF])
def revisar_emergencia(
    request: Request,
    rotacion_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, REVISAR],
    cuerpo: NotaCuerpo,
):
    """Cierra la revisión obligatoria de una emergencia autorizada sin segundo par."""
    rotacion = _rotacion_visible(db, usuario, rotacion_id)
    try:
        servicio.marcar_revisada(db, rotacion=rotacion, usuario=usuario,
                                 nota=cuerpo.nota, request=request)
    except ErrorRotacion as exc:
        raise _error(exc) from exc
    return _serializar(rotacion)


# ---------------------------------------------------------------------------
# Ejecución por agente (v1.4.0)
# ---------------------------------------------------------------------------


@router.post("/rotacion/solicitudes/{rotacion_id}/despachar", dependencies=[CSRF])
def despachar_solicitud(
    request: Request,
    rotacion_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, SOLICITAR],
):
    """Vuelve a despachar al agente una rotación ya autorizada.

    No añade autoridad: dos personas ya decidieron. Sirve cuando el despacho
    automático no salió (agente sin contacto, trabajo vencido sin recoger).
    """
    rotacion = _rotacion_visible(db, usuario, rotacion_id)
    try:
        servicio.despachar(db, rotacion=rotacion, usuario=usuario, request=request)
    except ErrorRotacion as exc:
        raise _error(exc) from exc
    return _serializar(rotacion)


@router.post("/rotacion/trabajos/{trabajo_id}/resolver", dependencies=[CSRF])
def resolver_trabajo(
    request: Request,
    trabajo_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, AUTORIZAR],
    cuerpo: ResolverTrabajo,
):
    """Una persona dice qué contraseña quedó en el activo tras un «sin confirmar».

    Puede escribir una contraseña en el inventario, así que pide lo mismo que
    autorizar una rotación: contraseña y código de aplicación autenticadora.
    """
    trabajo = db.get(TrabajoRotacion, trabajo_id)
    if trabajo is None or not access.puede_ver_credencial(db, usuario, trabajo.credencial):
        raise HTTPException(status_code=404, detail="El trabajo no existe.")
    try:
        reautenticar(db, usuario, cuerpo.password, cuerpo.codigo)
    except ErrorReautenticacion as exc:
        audit.registrar(
            db, audit.ACCESO_DENEGADO, request=request, usuario=usuario,
            objeto_tipo="trabajo", objeto_id=trabajo_id,
            detalle="Reautenticación fallida al resolver una rotación sin confirmar", exito=False,
        )
        db.commit()
        raise _error(exc) from exc
    try:
        servicio.resolver_sin_confirmar(db, trabajo=trabajo, aplicada=cuerpo.aplicada,
                                        usuario=usuario, request=request)
    except ErrorRotacion as exc:
        raise _error(exc) from exc
    return _serializar(trabajo.rotacion)
