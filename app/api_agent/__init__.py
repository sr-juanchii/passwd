"""API de los agentes de rotación (`/api/agent`, v1.4.0).

Es la única superficie que habla con los agentes. Se autentica con la identidad
de cada agente (``Authorization: Bearer``), sin cookies ni CSRF, y **solo
traduce HTTP ↔ servicio**: las reglas viven en ``app/servicios/agentes.py`` y
``app/servicios/rotacion.py``. Contrato normativo en docs/contrato-agente.md y
referencia de cada ruta en docs/referencia-api-agent.md.

Con ``agentes_enabled`` apagado, todo el prefijo responde 404: la superficie no
existe hasta que alguien decide activarla.

**Qué se audita.** Todo cambio de estado (enrolamiento, renovación de identidad,
entrega de un trabajo, su resultado, la telemetría no) y **todo rechazo**. El
latido rutinario y la consulta sin trabajo no dejan asiento: quedan como
«último contacto» del agente. Auditar cada latido llenaría la bitácora de
«sigue vivo» y escondería lo que importa. Los rechazos no autenticados se
acotan por IP, para que nadie pueda llenar la bitácora a base de peticiones.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import audit
from app.database import get_db
from app.models import Agente, ahora_utc
from app.security import ratelimit
from app.servicios import agentes
from app.servicios import rotacion as servicio_rotacion
from app.servicios.agentes import ErrorAgente
from app.servicios.rotacion import ErrorRotacion

# Peticiones por agente en 5 minutos. Un agente sano hace unas pocas por ciclo de
# latido (saludo, trabajo, telemetría); el margen cubre reintentos y un trabajo.
LIMITE_AGENTE = 120
# Peticiones por IP en 5 minutos, antes de autenticar: frena el barrido de tokens
# y acota cuántos rechazos puede escribir en la bitácora una sola dirección.
LIMITE_IP = 300
# Intentos de enrolamiento por IP en 15 minutos: fuerza bruta del token de un uso.
LIMITE_ENROLAR = 10
VENTANA_MIN = 5
VENTANA_ENROLAR_MIN = 15
# Topes de cuerpo, muy por debajo del global de la aplicación: el servidor
# rechaza lo que excede en vez de ampliar el límite (§4.4). Ninguna petición del
# protocolo se acerca a 4 KiB (la mayor, un resultado con su detalle, ronda 2,5);
# la telemetría lleva la lista de discos y tiene el suyo.
MAX_BYTES_PETICION = 4 * 1024
MAX_BYTES_TELEMETRIA = 16 * 1024


def _interruptor() -> None:
    if not agentes.habilitados():
        raise HTTPException(status_code=404, detail="Not Found")


def _ip(request: Request) -> str:
    return (request.client.host if request.client else "")[:45]


async def _tope_de_cuerpo(request: Request, db: Annotated[Session, Depends(get_db)]) -> None:
    """Rechaza con 413 el cuerpo que excede el tope de su ruta, antes de autenticar.

    El rechazo cuenta para el límite por dirección: si no, mandar cuerpos
    enormes sería otra forma de llenar la bitácora.
    """
    telemetria = request.url.path.endswith("/telemetria")
    tope = MAX_BYTES_TELEMETRIA if telemetria else MAX_BYTES_PETICION
    if len(await request.body()) > tope:
        _limite_ip(db, request)
        que = "La telemetría" if telemetria else "La petición"
        raise _rechazar(db, request, 413, f"{que} excede {tope} bytes"
                        + (": recórtela en el agente." if telemetria else "."))


router = APIRouter(prefix="/api/agent", tags=["agente"],
                   dependencies=[Depends(_interruptor), Depends(_tope_de_cuerpo)])


def _rechazar(db: Session, request: Request, codigo: int, mensaje: str, *,
              sujeto: str = "agente:desconocido", objeto_id: int | str = "") -> HTTPException:
    """Audita el rechazo, lo confirma y devuelve la excepción que hay que lanzar.

    Se confirma aquí porque ``get_db`` deshace la transacción ante cualquier
    error, y se perdería justo la evidencia del intento. Un 429 repetido solo se
    audita una vez por ventana y dirección: de lo contrario, superar el límite
    sería la forma de llenar la bitácora.
    """
    auditar = codigo != 429 or ratelimit.permitir_intento(
        f"agente-429:{_ip(request)}", limite=1, ventana_minutos=VENTANA_MIN, db=db)
    if auditar:
        audit.registrar(
            db, audit.AGENTE_ACCESO_RECHAZADO, request=request, username=sujeto,
            objeto_tipo="agente", objeto_id=objeto_id, exito=False,
            detalle=f"{codigo} {request.method} {request.url.path}: {mensaje}"[:2000],
        )
        db.commit()
    cabeceras = {"WWW-Authenticate": "Bearer"} if codigo == 401 else None
    return HTTPException(status_code=codigo, detail=mensaje, headers=cabeceras)


def _limite_ip(db: Session, request: Request) -> None:
    if not ratelimit.permitir_intento(f"agente-ip:{_ip(request)}", limite=LIMITE_IP,
                                      ventana_minutos=VENTANA_MIN, db=db):
        raise _rechazar(db, request, 429, "Demasiadas peticiones desde esta dirección.")


def agente_autenticado(request: Request, db: Annotated[Session, Depends(get_db)]) -> Agente:
    """Identidad del agente que llama. 401 si falta, no vale o caducó."""
    _limite_ip(db, request)
    cabecera = request.headers.get("authorization", "")
    if not cabecera.startswith("Bearer "):
        raise _rechazar(db, request, 401, "Falta la identidad del agente.")
    resultado = agentes.autenticar(db, cabecera[7:].strip())
    if resultado is None:
        raise _rechazar(db, request, 401, "Identidad de agente no válida, revocada o caducada.")
    agente, con_anterior = resultado
    if not ratelimit.permitir_intento(f"agente:{agente.id}", limite=LIMITE_AGENTE,
                                      ventana_minutos=VENTANA_MIN, db=db):
        raise _rechazar(db, request, 429, "Demasiadas peticiones de este agente.",
                        sujeto=agentes.sujeto(agente), objeto_id=agente.id)
    request.state.con_token_anterior = con_anterior
    return agente


AGENTE = Annotated[Agente, Depends(agente_autenticado)]
BD = Annotated[Session, Depends(get_db)]


def _fecha(valor) -> str | None:
    return valor.isoformat(timespec="seconds") if valor else None


def _error_de_servicio(db: Session, request: Request, exc: ErrorAgente | ErrorRotacion,
                       agente: Agente | None = None) -> HTTPException:
    sujeto = agentes.sujeto(agente) if agente is not None else "agente:desconocido"
    return _rechazar(db, request, exc.codigo, exc.mensaje, sujeto=sujeto,
                     objeto_id=agente.id if agente is not None else "")


# ---------------------------------------------------------------------------
# Enrolamiento e identidad
# ---------------------------------------------------------------------------


class EnrolarCuerpo(BaseModel):
    token_enrolamiento: str = Field(default="", max_length=200)
    clave_publica: str = Field(default="", max_length=100)
    nombre_host: str = Field(default="", max_length=255)
    version: str = Field(default="", max_length=40)


@router.post("/enrolar")
def enrolar(request: Request, db: BD, cuerpo: EnrolarCuerpo):
    """Canjea el token de un solo uso por la identidad del agente (una vez)."""
    _limite_ip(db, request)
    if not ratelimit.permitir_intento(f"agente-enrolar:{_ip(request)}", limite=LIMITE_ENROLAR,
                                      ventana_minutos=VENTANA_ENROLAR_MIN, db=db):
        raise _rechazar(db, request, 429, "Demasiados intentos de enrolamiento desde esta dirección.")
    try:
        agente, token = agentes.enrolar(
            db, token_enrolamiento=cuerpo.token_enrolamiento, clave_publica=cuerpo.clave_publica,
            nombre_host=cuerpo.nombre_host, version=cuerpo.version, ip=_ip(request), request=request,
        )
    except ErrorAgente as exc:
        raise _error_de_servicio(db, request, exc) from exc
    return {
        "agente_id": agente.id,
        "nombre": agente.nombre,
        "token": token,
        "token_expira_en": _fecha(agente.token_expira_en),
        "intervalo_min": agentes.saludo_intervalo_min(),
    }


class SaludoCuerpo(BaseModel):
    version: str = Field(default="", max_length=40)


@router.post("/saludo")
def saludo(request: Request, db: BD, agente: AGENTE, cuerpo: SaludoCuerpo):
    """Latido. POST y no GET: renueva la identidad y registra el contacto."""
    datos = agentes.saludo(
        db, agente=agente, ip=_ip(request), version=cuerpo.version,
        con_token_anterior=getattr(request.state, "con_token_anterior", False), request=request,
    )
    return {
        "token_nuevo": datos["token_nuevo"],
        "token_expira_en": _fecha(datos["token_expira_en"]),
        "intervalo_min": datos["intervalo_min"],
        "version_minima": datos["version_minima"],
        "version_admitida": datos["version_admitida"],
        "version_en_gracia": datos["version_en_gracia"],
    }


# ---------------------------------------------------------------------------
# Trabajos
# ---------------------------------------------------------------------------


@router.get("/trabajos/pendiente")
def trabajo_pendiente(request: Request, db: BD, agente: AGENTE):
    """El trabajo del agente, sellado a su clave; 204 si no hay ninguno."""
    agente.ultimo_contacto_en = ahora_utc()
    agente.ip_ultimo_contacto = _ip(request)
    entrega = servicio_rotacion.entregar(db, agente=agente, request=request)
    if entrega is None:
        return Response(status_code=204)
    trabajo, sobre = entrega
    return {"trabajo_id": trabajo.id, "expira_en": _fecha(trabajo.ventana_expira_en), "sobre": sobre}


class ResultadoCuerpo(BaseModel):
    estado: str = Field(default="", max_length=20)
    verificacion: str = Field(default="local", max_length=20)
    detalle: str = Field(default="", max_length=2000)


@router.post("/trabajos/{trabajo_id}/resultado")
def resultado(trabajo_id: int, request: Request, db: BD, agente: AGENTE, cuerpo: ResultadoCuerpo):
    try:
        trabajo = servicio_rotacion.registrar_resultado(
            db, agente=agente, trabajo_id=trabajo_id, estado=cuerpo.estado,
            verificacion=cuerpo.verificacion, detalle=cuerpo.detalle, request=request,
        )
    except ErrorRotacion as exc:
        raise _error_de_servicio(db, request, exc, agente) from exc
    return {"trabajo_id": trabajo.id, "estado": trabajo.estado}


# ---------------------------------------------------------------------------
# Telemetría
# ---------------------------------------------------------------------------


class Disco(BaseModel):
    montaje: str = Field(default="", max_length=255)
    # Holgado a propósito: el agente recorta a 120 y el servicio vuelve a acotar.
    # Un tope más estricto aquí que en el agente rechazaría la telemetría ENTERA
    # por un nombre de sistema de archivos largo.
    sistema_archivos: str = Field(default="", max_length=255)
    total_bytes: int | None = None
    usado_pct: int | None = None


class TelemetriaCuerpo(BaseModel):
    cpu_pct: int | None = None
    ram_pct: int | None = None
    disco_pct: int | None = None
    uptime_s: int | None = None
    sistema_operativo: str = Field(default="", max_length=255)
    kernel: str = Field(default="", max_length=255)
    cpu_modelo: str = Field(default="", max_length=255)
    ram_total: int | None = None
    discos: list[Disco] = Field(default_factory=list, max_length=256)
    recortada: bool = False


@router.post("/telemetria", status_code=204)
def telemetria(request: Request, db: BD, agente: AGENTE, cuerpo: TelemetriaCuerpo):
    agentes.registrar_telemetria(
        db, agente=agente, ip=_ip(request), cpu_pct=cuerpo.cpu_pct, ram_pct=cuerpo.ram_pct,
        disco_pct=cuerpo.disco_pct, uptime_s=cuerpo.uptime_s,
        sistema_operativo=cuerpo.sistema_operativo, kernel=cuerpo.kernel,
        cpu_modelo=cuerpo.cpu_modelo, ram_total=cuerpo.ram_total,
        discos=[d.model_dump() for d in cuerpo.discos], recortada=cuerpo.recortada,
    )
    return Response(status_code=204)


__all__ = ["router"]
