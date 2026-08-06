"""Gestión de credenciales en JSON: CRUD, revelado, copiado e historial.

Reutiliza el cifrado Fernet, el control de acceso por objeto, el límite
anti-exfiltración y la auditoría exactos de ``app/routes/credentials.py``. Los
listados nunca incluyen la contraseña; solo los endpoints de revelado/copiado
la entregan, con cabecera ``Cache-Control: no-store``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import access, audit, avisos
from app.api_web.deps import requiere_permiso_json, verificar_csrf_json
from app.config import get_settings
from app.database import get_db
from app.models import (
    ACTIVO_DISPOSITIVO,
    ACTIVO_FISICO,
    ACTIVO_HIPERVISOR,
    ACTIVO_VM,
    ROL_ANALISTA,
    Credencial,
    DispositivoRed,
    Hipervisor,
    HistorialCredencial,
    MaquinaVirtual,
    ServidorFisico,
    Usuario,
    ahora_utc,
)
from app.notifications import enviar_alerta
from app.security import ratelimit
from app.security.crypto import cifrar, descifrar

router = APIRouter()

GESTIONAR = Depends(requiere_permiso_json("credenciales.gestionar"))
REVELAR = Depends(requiere_permiso_json("credenciales.revelar"))
CSRF = Depends(verificar_csrf_json)

_MODELOS_ACTIVO = {
    ACTIVO_FISICO: (ServidorFisico, "servidor físico"),
    ACTIVO_HIPERVISOR: (Hipervisor, "hipervisor"),
    ACTIVO_VM: (MaquinaVirtual, "máquina virtual"),
    ACTIVO_DISPOSITIVO: (DispositivoRed, "dispositivo de red"),
}


class CredencialCrear(BaseModel):
    activo: str = ""
    activo_id: int = 0
    usuario_acceso: str = ""
    password: str = ""
    servicio: str = "SSH"
    puerto: int | None = None
    descripcion: str = ""


class CredencialEditar(BaseModel):
    usuario_acceso: str = ""
    password: str = ""  # "" = conservar la actual
    servicio: str = "SSH"
    puerto: int | None = None
    descripcion: str = ""


def _podar_historial(db: Session, credencial_id: int) -> None:
    maximo = get_settings().password_history_max
    entradas = db.scalars(
        select(HistorialCredencial)
        .where(HistorialCredencial.credencial_id == credencial_id)
        .order_by(HistorialCredencial.rotada_en.desc(), HistorialCredencial.id.desc())
    ).all()
    for sobrante in entradas[maximo:]:
        db.delete(sobrante)


def _resolver_activo(db: Session, tipo: str, activo_id: int):
    if tipo not in _MODELOS_ACTIVO:
        raise HTTPException(status_code=400, detail="Tipo de activo inválido.")
    modelo, etiqueta = _MODELOS_ACTIVO[tipo]
    activo = db.get(modelo, activo_id)
    if activo is None:
        raise HTTPException(status_code=404, detail=f"No existe el {etiqueta} indicado.")
    return activo, etiqueta


def _exigir_ver(db: Session, usuario: Usuario, tipo: str, activo_id: int) -> None:
    """Gestionar una credencial exige poder ver su activo (respeta la restricción)."""
    if not access.puede_ver_activo(db, usuario, tipo, activo_id):
        raise HTTPException(status_code=404, detail="El recurso solicitado no existe.")


def _obtener_credencial(db: Session, credencial_id: int) -> Credencial:
    credencial = db.get(Credencial, credencial_id)
    if credencial is None:
        raise HTTPException(status_code=404, detail="La credencial no existe.")
    return credencial


def _validar_puerto(puerto: int | None) -> None:
    if puerto is not None and not (1 <= puerto <= 65535):
        raise HTTPException(status_code=400, detail="El puerto debe ser un número entre 1 y 65535.")


@router.post("/credenciales", dependencies=[CSRF])
def credencial_crear(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
    cuerpo: CredencialCrear,
):
    instancia, etiqueta = _resolver_activo(db, cuerpo.activo, cuerpo.activo_id)
    _exigir_ver(db, usuario, cuerpo.activo, cuerpo.activo_id)
    if not cuerpo.usuario_acceso.strip():
        raise HTTPException(status_code=400, detail="El usuario de acceso es obligatorio.")
    if not cuerpo.password:
        raise HTTPException(status_code=400, detail="La contraseña es obligatoria.")
    _validar_puerto(cuerpo.puerto)

    credencial = Credencial(
        usuario_acceso=cuerpo.usuario_acceso.strip(),
        password_cifrada=cifrar(cuerpo.password),
        servicio=cuerpo.servicio.strip() or "SSH",
        puerto=cuerpo.puerto,
        descripcion=cuerpo.descripcion.strip(),
        creado_por_id=usuario.id,
        servidor_fisico_id=cuerpo.activo_id if cuerpo.activo == ACTIVO_FISICO else None,
        hipervisor_id=cuerpo.activo_id if cuerpo.activo == ACTIVO_HIPERVISOR else None,
        maquina_virtual_id=cuerpo.activo_id if cuerpo.activo == ACTIVO_VM else None,
        dispositivo_red_id=cuerpo.activo_id if cuerpo.activo == ACTIVO_DISPOSITIVO else None,
    )
    db.add(credencial)
    db.flush()
    audit.registrar(db, audit.CREDENCIAL_CREADA, request=request, usuario=usuario,
                    objeto_tipo="credencial", objeto_id=credencial.id,
                    detalle=f"{cuerpo.usuario_acceso.strip()}@{instancia.nombre} "
                            f"({etiqueta}, {credencial.servicio})")
    return {"id": credencial.id}


@router.get("/credenciales/{credencial_id}")
def credencial_editar_datos(
    request: Request,
    credencial_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
):
    credencial = _obtener_credencial(db, credencial_id)
    tipo = credencial.tipo_activo
    activo_id = (credencial.servidor_fisico_id or credencial.hipervisor_id
                 or credencial.maquina_virtual_id or credencial.dispositivo_red_id)
    _exigir_ver(db, usuario, tipo, activo_id)
    return {
        "id": credencial.id,
        "usuario_acceso": credencial.usuario_acceso,
        "servicio": credencial.servicio,
        "puerto": credencial.puerto,
        "descripcion": credencial.descripcion,
        "tipo_activo": tipo,
        "activo_id": activo_id,
        "activo_nombre": credencial.nombre_activo,
        "dias_sin_rotar": credencial.dias_sin_rotar,
        "historial": [
            {
                "id": h.id,
                "rotada_en": h.rotada_en.isoformat(),
                "rotada_por": h.rotada_por.username if h.rotada_por else None,
            }
            for h in credencial.historial
        ],
    }


@router.put("/credenciales/{credencial_id}", dependencies=[CSRF])
def credencial_editar(
    request: Request,
    credencial_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
    cuerpo: CredencialEditar,
):
    credencial = _obtener_credencial(db, credencial_id)
    tipo = credencial.tipo_activo
    activo_id = (credencial.servidor_fisico_id or credencial.hipervisor_id
                 or credencial.maquina_virtual_id or credencial.dispositivo_red_id)
    _exigir_ver(db, usuario, tipo, activo_id)
    instancia, _ = _resolver_activo(db, tipo, activo_id)

    if not cuerpo.usuario_acceso.strip():
        raise HTTPException(status_code=400, detail="El usuario de acceso es obligatorio.")
    _validar_puerto(cuerpo.puerto)

    credencial.usuario_acceso = cuerpo.usuario_acceso.strip()
    credencial.servicio = cuerpo.servicio.strip() or "SSH"
    credencial.puerto = cuerpo.puerto
    credencial.descripcion = cuerpo.descripcion.strip()
    rotada = bool(cuerpo.password)
    if rotada:  # contraseña en blanco = conservar la actual
        db.add(HistorialCredencial(
            credencial_id=credencial.id, password_cifrada=credencial.password_cifrada,
            rotada_por_id=usuario.id,
        ))
        credencial.password_cifrada = cifrar(cuerpo.password)
        credencial.password_rotada_en = ahora_utc()
        _podar_historial(db, credencial.id)
    audit.registrar(db, audit.CREDENCIAL_ACTUALIZADA, request=request, usuario=usuario,
                    objeto_tipo="credencial", objeto_id=credencial.id,
                    detalle=f"{credencial.usuario_acceso}@{instancia.nombre}"
                            + (" — contraseña rotada" if rotada else ""))
    # Auditoría de credenciales compartidas: se avisa a los DEMÁS usuarios con
    # acceso a este activo de que hubo una modificación. El correo comunica solo
    # EL HECHO —activo, servicio, quién y cuándo—, nunca la contraseña nueva ni la
    # anterior: quien la necesite la revela en la aplicación, donde el acceso se
    # comprueba, se limita por tasa y queda en la bitácora.
    avisos.aviso_credencial_compartida_actualizada(
        db, credencial, usuario, password_cambiada=rotada
    )
    return {"id": credencial.id}


@router.delete("/credenciales/{credencial_id}", dependencies=[CSRF])
def credencial_eliminar(
    request: Request,
    credencial_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
):
    credencial = _obtener_credencial(db, credencial_id)
    _exigir_ver(db, usuario, credencial.tipo_activo,
                credencial.servidor_fisico_id or credencial.hipervisor_id
                or credencial.maquina_virtual_id or credencial.dispositivo_red_id)
    detalle = f"{credencial.usuario_acceso}@{credencial.nombre_activo} ({credencial.servicio})"
    db.delete(credencial)
    audit.registrar(db, audit.CREDENCIAL_ELIMINADA, request=request, usuario=usuario,
                    objeto_tipo="credencial", objeto_id=credencial_id, detalle=detalle)
    return {"ok": True}


def _entregar_password(
    request: Request,
    db: Session,
    usuario: Usuario,
    credencial_id: int,
    accion: str,
) -> JSONResponse:
    """Entrega la contraseña en claro aplicando límite anti-exfiltración y auditoría."""
    credencial = db.get(Credencial, credencial_id)
    if credencial is None:
        raise HTTPException(status_code=404, detail="La credencial no existe.")

    if not access.puede_ver_credencial(db, usuario, credencial):
        audit.registrar(db, audit.ACCESO_DENEGADO, request=request, usuario=usuario,
                        objeto_tipo="credencial", objeto_id=credencial_id,
                        detalle="Acceso a credencial sin concesión vigente.", exito=False)
        db.commit()
        raise HTTPException(status_code=404, detail="La credencial no existe.")
    if not access.puede_revelar_credencial(db, usuario, credencial):
        audit.registrar(db, audit.ACCESO_DENEGADO, request=request, usuario=usuario,
                        objeto_tipo="credencial", objeto_id=credencial_id,
                        detalle="Concesión sin nivel para revelar/copiar credenciales.", exito=False)
        db.commit()
        raise HTTPException(status_code=403, detail="No tiene permiso para usar esta credencial.")

    settings = get_settings()
    if not ratelimit.permitir_intento(
        f"revelar:{usuario.id}",
        limite=settings.reveal_rate_limit,
        ventana_minutos=settings.reveal_rate_window_minutes,
        db=db,
    ):
        audit.registrar(db, audit.REVELADO_TASA_EXCEDIDA, request=request, usuario=usuario,
                        objeto_tipo="credencial", objeto_id=credencial_id,
                        detalle=f"Límite de {settings.reveal_rate_limit} accesos "
                                f"en {settings.reveal_rate_window_minutes} min superado.",
                        exito=False)
        db.commit()  # conservar la evidencia pese al error que sigue
        enviar_alerta(
            "Posible exfiltración de credenciales",
            f"El usuario «{usuario.username}» superó el límite de accesos a contraseñas "
            f"({settings.reveal_rate_limit} en {settings.reveal_rate_window_minutes} min).",
        )
        raise HTTPException(status_code=429,
                            detail="Límite de accesos a contraseñas alcanzado; espere unos minutos.")

    via = " (vía concesión)" if usuario.rol == ROL_ANALISTA else ""
    audit.registrar(db, accion, request=request, usuario=usuario,
                    objeto_tipo="credencial", objeto_id=credencial.id,
                    detalle=f"{credencial.usuario_acceso}@{credencial.nombre_activo} "
                            f"({credencial.servicio}){via}")
    _avisar_revelado(request, db, usuario, credencial)
    return JSONResponse(
        {"usuario": credencial.usuario_acceso, "password": descifrar(credencial.password_cifrada)},
        headers={"Cache-Control": "no-store"},
    )


@router.post("/credenciales/{credencial_id}/revelar", dependencies=[CSRF])
def credencial_revelar(
    request: Request,
    credencial_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, REVELAR],
):
    return _entregar_password(request, db, usuario, credencial_id, audit.CREDENCIAL_REVELADA)


@router.post("/credenciales/{credencial_id}/copiar", dependencies=[CSRF])
def credencial_copiar(
    request: Request,
    credencial_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, REVELAR],
):
    return _entregar_password(request, db, usuario, credencial_id, audit.CREDENCIAL_COPIADA)


@router.post("/credenciales/{credencial_id}/historial/{historial_id}/revelar", dependencies=[CSRF])
def historial_revelar(
    request: Request,
    credencial_id: int,
    historial_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
):
    entrada = db.get(HistorialCredencial, historial_id)
    if entrada is None or entrada.credencial_id != credencial_id:
        raise HTTPException(status_code=404, detail="La entrada de historial no existe.")
    credencial = db.get(Credencial, credencial_id)
    if credencial is None or not access.puede_revelar_credencial(db, usuario, credencial):
        raise HTTPException(status_code=404, detail="La entrada de historial no existe.")

    settings = get_settings()
    if not ratelimit.permitir_intento(
        f"revelar:{usuario.id}", limite=settings.reveal_rate_limit,
        ventana_minutos=settings.reveal_rate_window_minutes, db=db,
    ):
        audit.registrar(db, audit.REVELADO_TASA_EXCEDIDA, request=request, usuario=usuario,
                        objeto_tipo="historial_credencial", objeto_id=historial_id, exito=False)
        db.commit()
        raise HTTPException(status_code=429, detail="Límite de accesos alcanzado; espere unos minutos.")

    audit.registrar(db, audit.HISTORIAL_REVELADO, request=request, usuario=usuario,
                    objeto_tipo="credencial", objeto_id=credencial_id,
                    detalle=f"Contraseña anterior del {entrada.rotada_en:%d/%m/%Y %H:%M}")
    return JSONResponse({"password": descifrar(entrada.password_cifrada)},
                        headers={"Cache-Control": "no-store"})


def _avisar_revelado(request, db, usuario, credencial) -> None:
    """Aviso al titular de que reveló una credencial en su sesión (mejor esfuerzo).

    Deduplicado por sesión y categoría en ``avisos``: el primer revelado de la
    sesión genera un correo, los siguientes no. Así el aviso conserva su valor de
    detección sin convertir el trabajo normal en decenas de mensajes.
    """
    sesion = getattr(request.state, "sesion", None)
    if sesion is None:
        return
    avisos.aviso_actividad_sensible(
        db, usuario, sesion.id, "revelado",
        f"reveló o copió una contraseña del inventario "
        f"({credencial.usuario_acceso}@{credencial.nombre_activo})",
    )
