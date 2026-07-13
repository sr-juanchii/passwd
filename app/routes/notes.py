"""Notas seguras cifradas por activo.

Texto sensible que no encaja en los campos estructurados (instrucciones de
acceso VPN, tokens, pasos de recuperación…). Se cifra en reposo con Fernet,
igual que las credenciales: editar requiere gestionar el inventario y revelar
requiere permiso de credenciales (gateado por el acceso por objeto del
analista), siempre auditado y bajo el límite anti-exfiltración.
"""

from __future__ import annotations

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import access, audit
from app.config import get_settings
from app.database import get_db
from app.deps import render, requiere_permiso, verificar_csrf
from app.models import (
    ACTIVO_FISICO,
    ACTIVO_HIPERVISOR,
    ACTIVO_VM,
    ROL_ANALISTA,
    Hipervisor,
    MaquinaVirtual,
    ServidorFisico,
    Usuario,
)
from app.security import ratelimit
from app.security.crypto import cifrar, descifrar

router = APIRouter()

GESTIONAR = Depends(requiere_permiso("inventario.gestionar"))
REVELAR = Depends(requiere_permiso("credenciales.revelar"))

_ACTIVOS = {
    ACTIVO_FISICO: (ServidorFisico, "/servidores"),
    ACTIVO_HIPERVISOR: (Hipervisor, "/hipervisores"),
    ACTIVO_VM: (MaquinaVirtual, "/vms"),
}


def _resolver(db: Session, tipo: str, activo_id: int):
    if tipo not in _ACTIVOS:
        raise HTTPException(status_code=400, detail="Tipo de activo inválido.")
    modelo, prefijo = _ACTIVOS[tipo]
    activo = db.get(modelo, activo_id)
    if activo is None:
        raise HTTPException(status_code=404, detail="El activo no existe.")
    return activo, f"{prefijo}/{activo_id}"


@router.get("/activos/{tipo}/{activo_id}/notas")
def notas_form(
    request: Request,
    tipo: str,
    activo_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
):
    activo, url_volver = _resolver(db, tipo, activo_id)
    contenido = descifrar(activo.notas_cifradas) if activo.notas_cifradas else ""
    return render(request, "notas_form.html", {
        "usuario_actual": usuario, "activo": activo, "tipo_activo": tipo,
        "url_volver": url_volver, "contenido": contenido,
    })


@router.post("/activos/{tipo}/{activo_id}/notas", dependencies=[Depends(verificar_csrf)])
def notas_guardar(
    request: Request,
    tipo: str,
    activo_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
    contenido: Annotated[str, Form()] = "",
):
    activo, url_volver = _resolver(db, tipo, activo_id)
    activo.notas_cifradas = cifrar(contenido) if contenido.strip() else None
    audit.registrar(db, audit.NOTA_ACTUALIZADA, request=request, usuario=usuario,
                    objeto_tipo=tipo, objeto_id=activo_id,
                    detalle=f"Notas {'actualizadas' if contenido.strip() else 'borradas'} en {activo.nombre}")
    return RedirectResponse(f"{url_volver}?msg={quote('Notas guardadas.')}", status_code=303)


@router.post("/activos/{tipo}/{activo_id}/notas/revelar", dependencies=[Depends(verificar_csrf)])
def notas_revelar(
    request: Request,
    tipo: str,
    activo_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, REVELAR],
):
    activo, _ = _resolver(db, tipo, activo_id)

    # Mismo control por objeto que las credenciales: el analista necesita el
    # nivel 'ver_credenciales' sobre el activo.
    if not access.puede_ver_activo(db, usuario, tipo, activo_id):
        raise HTTPException(status_code=404, detail="El activo no existe.")
    if not access.puede_revelar_en_activo(db, usuario, tipo, activo_id):
        audit.registrar(db, audit.ACCESO_DENEGADO, request=request, usuario=usuario,
                        objeto_tipo=tipo, objeto_id=activo_id,
                        detalle="Sin nivel para revelar notas.", exito=False)
        db.commit()
        raise HTTPException(status_code=403, detail="No tiene permiso para ver estas notas.")

    settings = get_settings()
    if not ratelimit.permitir_intento(
        f"revelar:{usuario.id}", limite=settings.reveal_rate_limit,
        ventana_minutos=settings.reveal_rate_window_minutes, db=db,
    ):
        audit.registrar(db, audit.REVELADO_TASA_EXCEDIDA, request=request, usuario=usuario,
                        objeto_tipo=tipo, objeto_id=activo_id, detalle="Notas.", exito=False)
        db.commit()
        raise HTTPException(status_code=429, detail="Límite de accesos alcanzado; espere unos minutos.")

    via = " (vía concesión)" if usuario.rol == ROL_ANALISTA else ""
    audit.registrar(db, audit.NOTA_REVELADA, request=request, usuario=usuario,
                    objeto_tipo=tipo, objeto_id=activo_id, detalle=f"{activo.nombre}{via}")
    contenido = descifrar(activo.notas_cifradas) if activo.notas_cifradas else ""
    return JSONResponse({"notas": contenido}, headers={"Cache-Control": "no-store"})
