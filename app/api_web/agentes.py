"""Panel de agentes de rotación en JSON (`/api/web/agentes`, v1.4.0).

Traduce HTTP ↔ ``app/servicios/agentes.py``. Las reglas —qué activos admiten
agente, cuándo caduca una identidad, qué pasa al revocar— viven en el servicio.
Aquí se resuelven, como en el resto de la API, el permiso, el CSRF, el control
de acceso por objeto y la **reautenticación**: dar de alta un agente o reemitir
su token de instalación crea una identidad de máquina que podrá recibir
contraseñas de ese servidor, y una sesión de administrador robada no debe
bastar para plantar una. Revocar no la pide: protege.

Ninguna respuesta lleva el hash de un token ni la clave privada de nadie; el
token de instalación se devuelve **una vez**, en la respuesta que lo crea.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import access, audit
from app.api_web.deps import requiere_permiso_json, verificar_csrf_json
from app.database import get_db
from app.models import (
    VIA_ROTACION_AGENTE,
    VIA_ROTACION_MANUAL,
    Agente,
    Credencial,
    Usuario,
)
from app.servicios import agentes as servicio
from app.servicios import rotacion as servicio_rotacion
from app.servicios.agentes import ErrorAgente
from app.servicios.autenticacion import ErrorReautenticacion, reautenticar

router = APIRouter()

VER = Depends(requiere_permiso_json("agentes.ver"))
GESTIONAR = Depends(requiere_permiso_json("agentes.gestionar"))
CSRF = Depends(verificar_csrf_json)


class Reautenticacion(BaseModel):
    password: str = ""
    codigo: str = ""


class AltaAgente(Reautenticacion):
    tipo_activo: str = Field(default="", max_length=20)
    activo_id: int = 0
    nombre: str = Field(default="", max_length=120)


class ViaCuerpo(BaseModel):
    via: str = ""


def _error(exc: ErrorAgente | ErrorReautenticacion) -> HTTPException:
    return HTTPException(status_code=exc.codigo, detail=exc.mensaje)


def _fecha(valor) -> str | None:
    return valor.isoformat() if valor else None


def _serializar(db: Session, agente: Agente) -> dict:
    admitida, en_gracia = servicio.version_admitida(db, agente)
    trabajo = servicio_rotacion.trabajo_activo_de(db, agente)
    telemetria = servicio.ultima_telemetria(db, agente)
    return {
        "id": agente.id,
        "nombre": agente.nombre,
        "estado": agente.estado,
        "cobertura": servicio.cobertura(agente),
        "activo": {"tipo": agente.tipo_activo, "id": agente.activo_id,
                   "nombre": servicio.nombre_activo(agente)},
        "nombre_host": agente.nombre_host,
        "version_agente": agente.version_agente,
        "version_admitida": admitida,
        "version_en_gracia": en_gracia,
        "ultimo_contacto_en": _fecha(agente.ultimo_contacto_en),
        "ip_ultimo_contacto": agente.ip_ultimo_contacto,
        "token_expira_en": _fecha(agente.token_expira_en),
        "enrolado_en": _fecha(agente.enrolado_en),
        "enrolamiento_expira_en": _fecha(agente.enrolamiento_expira_en),
        "clave_huella": agente.clave_huella,
        "rotacion_habilitada": agente.rotacion_habilitada,
        "creado_en": _fecha(agente.creado_en),
        "revocado_en": _fecha(agente.revocado_en),
        "trabajo_en_curso": None if trabajo is None else {
            "id": trabajo.id, "estado": trabajo.estado, "rotacion_id": trabajo.rotacion_id,
            "usuario_acceso": trabajo.credencial.usuario_acceso,
            "ventana_expira_en": _fecha(trabajo.ventana_expira_en),
            "sin_confirmar": servicio_rotacion.sin_confirmar(trabajo),
        },
        "telemetria": None if telemetria is None else {
            "fecha": _fecha(telemetria.fecha), "cpu_pct": telemetria.cpu_pct,
            "ram_pct": telemetria.ram_pct, "disco_pct": telemetria.disco_pct,
            "uptime_s": telemetria.uptime_s, "sistema_operativo": telemetria.sistema_operativo,
            "kernel": telemetria.kernel, "recortada": telemetria.recortada,
        },
    }


def _agente_visible(db: Session, usuario: Usuario, agente_id: int) -> Agente:
    agente = db.get(Agente, agente_id)
    if agente is None or not access.puede_ver_activo(db, usuario, agente.tipo_activo, agente.activo_id):
        # El mismo 404 en los dos casos: un activo restringido no existe para quien no lo alcanza.
        raise HTTPException(status_code=404, detail="El agente no existe.")
    return agente


def _reautenticar(db: Session, request: Request, usuario: Usuario, cuerpo: Reautenticacion,
                  que: str) -> None:
    try:
        reautenticar(db, usuario, cuerpo.password, cuerpo.codigo)
    except ErrorReautenticacion as exc:
        audit.registrar(db, audit.ACCESO_DENEGADO, request=request, usuario=usuario,
                        objeto_tipo="agente", detalle=f"Reautenticación fallida al {que}", exito=False)
        db.commit()  # la evidencia del intento sobrevive al rollback de la petición
        raise _error(exc) from exc


# ---------------------------------------------------------------------------
# Consulta
# ---------------------------------------------------------------------------


@router.get("/agentes")
def listar(
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, VER],
    revocados: bool = False,
):
    """Agentes con su cobertura. Los revocados solo si se piden: son historia."""
    servicio_rotacion.expirar_trabajos(db)
    consulta = select(Agente).order_by(Agente.nombre)
    filas = [a for a in db.scalars(consulta).all()
             if (revocados or not a.revocado)
             and access.puede_ver_activo(db, usuario, a.tipo_activo, a.activo_id)]
    return {
        "habilitados": servicio.habilitados(),
        "agentes": [_serializar(db, a) for a in filas],
    }


@router.get("/agentes/activo/{tipo}/{activo_id}")
def cobertura_de_activo(
    tipo: str,
    activo_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, VER],
):
    """Insignia de cobertura de un activo, para su ficha."""
    if tipo not in servicio.MODELOS_ACTIVO:
        # Los dispositivos de red no admiten agente: siempre sin cobertura.
        return {"cobertura": servicio.COBERTURA_SIN_AGENTE, "admite_agente": False,
                "habilitados": servicio.habilitados(), "agente": None}
    modelo, _etiqueta = servicio.MODELOS_ACTIVO[tipo]
    if db.get(modelo, activo_id) is None or not access.puede_ver_activo(db, usuario, tipo, activo_id):
        raise HTTPException(status_code=404, detail="El activo no existe.")
    agente = servicio.agente_vigente_de(db, tipo, activo_id)
    return {
        "cobertura": servicio.cobertura(agente),
        "admite_agente": True,
        # Con el interruptor apagado no se puede dar de alta ninguno: la ficha lo dice
        # en vez de ofrecer un formulario que fallaría al enviarlo.
        "habilitados": servicio.habilitados(),
        "agente": _serializar(db, agente) if agente is not None else None,
    }


# ---------------------------------------------------------------------------
# Gestión
# ---------------------------------------------------------------------------


@router.post("/agentes", dependencies=[CSRF])
def dar_de_alta(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
    cuerpo: AltaAgente,
):
    """Da de alta el agente de un activo. El token de instalación se ve **una vez**."""
    _reautenticar(db, request, usuario, cuerpo, "dar de alta un agente")
    try:
        agente, token = servicio.alta(db, tipo_activo=cuerpo.tipo_activo, activo_id=cuerpo.activo_id,
                                      nombre=cuerpo.nombre, usuario=usuario, request=request)
    except ErrorAgente as exc:
        raise _error(exc) from exc
    return {"agente": _serializar(db, agente), "token_enrolamiento": token,
            "token_expira_en": _fecha(agente.enrolamiento_expira_en)}


@router.post("/agentes/{agente_id}/enrolamiento", dependencies=[CSRF])
def reemitir_enrolamiento(
    request: Request,
    agente_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
    cuerpo: Reautenticacion,
):
    """Nuevo token de instalación; anula la identidad vigente del agente."""
    agente = _agente_visible(db, usuario, agente_id)
    _reautenticar(db, request, usuario, cuerpo, "reemitir el token de instalación de un agente")
    try:
        token = servicio.reemitir_enrolamiento(db, agente=agente, usuario=usuario, request=request)
    except ErrorAgente as exc:
        raise _error(exc) from exc
    return {"agente": _serializar(db, agente), "token_enrolamiento": token,
            "token_expira_en": _fecha(agente.enrolamiento_expira_en)}


@router.post("/agentes/{agente_id}/revocar", dependencies=[CSRF])
def revocar(
    request: Request,
    agente_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
):
    agente = _agente_visible(db, usuario, agente_id)
    try:
        servicio.revocar(db, agente=agente, usuario=usuario, request=request)
    except ErrorAgente as exc:
        raise _error(exc) from exc
    return {"agente": _serializar(db, agente)}


@router.post("/agentes/credenciales/{credencial_id}/via", dependencies=[CSRF])
def cambiar_via(
    request: Request,
    credencial_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
    cuerpo: ViaCuerpo,
):
    """Decide si la credencial se rota por el agente de su activo o a mano."""
    credencial = db.get(Credencial, credencial_id)
    if credencial is None or not access.puede_ver_credencial(db, usuario, credencial):
        raise HTTPException(status_code=404, detail="La credencial no existe.")
    try:
        if cuerpo.via == VIA_ROTACION_AGENTE:
            servicio.usar_agente(db, credencial=credencial, usuario=usuario, request=request)
        elif cuerpo.via == VIA_ROTACION_MANUAL:
            servicio.usar_manual(db, credencial=credencial, usuario=usuario, request=request)
        else:
            raise HTTPException(status_code=400, detail="La vía debe ser «agente» o «manual».")
    except ErrorAgente as exc:
        raise _error(exc) from exc
    return {"credencial_id": credencial.id, "via_rotacion": credencial.via_rotacion}
