"""Gestión de credenciales de acceso a los activos del inventario.

- La contraseña se cifra antes de tocar la base de datos y solo se descifra
  al revelarla explícitamente; cada revelado queda auditado con usuario e IP
  (CIS 3.11, 8.5 / ISO 27001 A.5.17, A.8.15).
- Los listados nunca incluyen la contraseña, ni siquiera enmascarada.
"""

from __future__ import annotations

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import audit
from app.database import get_db
from app.deps import render, requiere_permiso, verificar_csrf
from app.models import (
    ACTIVO_FISICO,
    ACTIVO_HIPERVISOR,
    ACTIVO_VM,
    Credencial,
    Hipervisor,
    MaquinaVirtual,
    ServidorFisico,
    Usuario,
)
from app.security.crypto import cifrar, descifrar

router = APIRouter()

GESTIONAR = Depends(requiere_permiso("credenciales.gestionar"))
REVELAR = Depends(requiere_permiso("credenciales.revelar"))

_MODELOS_ACTIVO = {
    ACTIVO_FISICO: (ServidorFisico, "servidor físico", "/servidores/{id}"),
    ACTIVO_HIPERVISOR: (Hipervisor, "hipervisor", "/hipervisores/{id}"),
    ACTIVO_VM: (MaquinaVirtual, "máquina virtual", "/vms/{id}"),
}

SERVICIOS_SUGERIDOS = ("SSH", "RDP", "iLO/IPMI", "Panel web", "Consola hipervisor", "Base de datos", "Otro")


def _resolver_activo(db: Session, tipo: str, activo_id: int):
    """Devuelve (instancia, etiqueta, url_detalle) o lanza 404/400."""
    if tipo not in _MODELOS_ACTIVO:
        raise HTTPException(status_code=400, detail="Tipo de activo inválido.")
    modelo, etiqueta, plantilla_url = _MODELOS_ACTIVO[tipo]
    activo = db.get(modelo, activo_id)
    if activo is None:
        raise HTTPException(status_code=404, detail=f"No existe el {etiqueta} indicado.")
    return activo, etiqueta, plantilla_url.format(id=activo_id)


def _ctx_form(usuario: Usuario, credencial: Credencial | None, tipo: str, activo, url_volver: str) -> dict:
    return {
        "usuario_actual": usuario,
        "credencial": credencial,
        "tipo_activo": tipo,
        "activo": activo,
        "url_volver": url_volver,
        "servicios": SERVICIOS_SUGERIDOS,
    }


@router.get("/credenciales/nueva")
def credencial_nueva_form(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
    activo: str = "",
    activo_id: int = 0,
):
    instancia, _, url_volver = _resolver_activo(db, activo, activo_id)
    return render(request, "credencial_form.html", _ctx_form(usuario, None, activo, instancia, url_volver))


@router.post("/credenciales/nueva", dependencies=[Depends(verificar_csrf)])
def credencial_crear(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
    activo: Annotated[str, Form()] = "",
    activo_id: Annotated[int, Form()] = 0,
    usuario_acceso: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
    servicio: Annotated[str, Form()] = "SSH",
    puerto: Annotated[str, Form()] = "",
    descripcion: Annotated[str, Form()] = "",
):
    instancia, etiqueta, url_volver = _resolver_activo(db, activo, activo_id)
    error = ""
    if not usuario_acceso.strip():
        error = "El usuario de acceso es obligatorio."
    elif not password:
        error = "La contraseña es obligatoria."
    puerto_num: int | None = None
    if puerto.strip():
        if not puerto.strip().isdigit() or not (1 <= int(puerto) <= 65535):
            error = "El puerto debe ser un número entre 1 y 65535."
        else:
            puerto_num = int(puerto)
    if error:
        return render(request, "credencial_form.html",
                      {**_ctx_form(usuario, None, activo, instancia, url_volver), "error": error},
                      status_code=400)

    credencial = Credencial(
        usuario_acceso=usuario_acceso.strip(),
        password_cifrada=cifrar(password),
        servicio=servicio.strip() or "SSH",
        puerto=puerto_num,
        descripcion=descripcion.strip(),
        creado_por_id=usuario.id,
        servidor_fisico_id=activo_id if activo == ACTIVO_FISICO else None,
        hipervisor_id=activo_id if activo == ACTIVO_HIPERVISOR else None,
        maquina_virtual_id=activo_id if activo == ACTIVO_VM else None,
    )
    db.add(credencial)
    db.flush()
    audit.registrar(db, audit.CREDENCIAL_CREADA, request=request, usuario=usuario,
                    objeto_tipo="credencial", objeto_id=credencial.id,
                    detalle=f"{usuario_acceso.strip()}@{instancia.nombre} ({etiqueta}, {credencial.servicio})")
    return RedirectResponse(f"{url_volver}?msg={quote('Credencial registrada.')}", status_code=303)


@router.get("/credenciales/{credencial_id}/editar")
def credencial_editar_form(
    request: Request,
    credencial_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
):
    credencial = db.get(Credencial, credencial_id)
    if credencial is None:
        raise HTTPException(status_code=404, detail="La credencial no existe.")
    tipo = credencial.tipo_activo
    activo_id = credencial.servidor_fisico_id or credencial.hipervisor_id or credencial.maquina_virtual_id
    instancia, _, url_volver = _resolver_activo(db, tipo, activo_id)
    return render(request, "credencial_form.html",
                  _ctx_form(usuario, credencial, tipo, instancia, url_volver))


@router.post("/credenciales/{credencial_id}/editar", dependencies=[Depends(verificar_csrf)])
def credencial_editar(
    request: Request,
    credencial_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
    usuario_acceso: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
    servicio: Annotated[str, Form()] = "SSH",
    puerto: Annotated[str, Form()] = "",
    descripcion: Annotated[str, Form()] = "",
):
    credencial = db.get(Credencial, credencial_id)
    if credencial is None:
        raise HTTPException(status_code=404, detail="La credencial no existe.")
    tipo = credencial.tipo_activo
    activo_id = credencial.servidor_fisico_id or credencial.hipervisor_id or credencial.maquina_virtual_id
    instancia, etiqueta, url_volver = _resolver_activo(db, tipo, activo_id)

    error = ""
    if not usuario_acceso.strip():
        error = "El usuario de acceso es obligatorio."
    puerto_num: int | None = None
    if puerto.strip():
        if not puerto.strip().isdigit() or not (1 <= int(puerto) <= 65535):
            error = "El puerto debe ser un número entre 1 y 65535."
        else:
            puerto_num = int(puerto)
    if error:
        return render(request, "credencial_form.html",
                      {**_ctx_form(usuario, credencial, tipo, instancia, url_volver), "error": error},
                      status_code=400)

    credencial.usuario_acceso = usuario_acceso.strip()
    credencial.servicio = servicio.strip() or "SSH"
    credencial.puerto = puerto_num
    credencial.descripcion = descripcion.strip()
    rotada = bool(password)
    if rotada:  # contraseña en blanco = conservar la actual
        credencial.password_cifrada = cifrar(password)
    audit.registrar(db, audit.CREDENCIAL_ACTUALIZADA, request=request, usuario=usuario,
                    objeto_tipo="credencial", objeto_id=credencial.id,
                    detalle=f"{credencial.usuario_acceso}@{instancia.nombre}"
                            + (" — contraseña rotada" if rotada else ""))
    return RedirectResponse(f"{url_volver}?msg={quote('Credencial actualizada.')}", status_code=303)


@router.post("/credenciales/{credencial_id}/eliminar", dependencies=[Depends(verificar_csrf)])
def credencial_eliminar(
    request: Request,
    credencial_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
):
    credencial = db.get(Credencial, credencial_id)
    if credencial is None:
        raise HTTPException(status_code=404, detail="La credencial no existe.")
    tipo = credencial.tipo_activo
    activo_id = credencial.servidor_fisico_id or credencial.hipervisor_id or credencial.maquina_virtual_id
    _, _, url_volver = _resolver_activo(db, tipo, activo_id)
    detalle = f"{credencial.usuario_acceso}@{credencial.nombre_activo} ({credencial.servicio})"
    db.delete(credencial)
    audit.registrar(db, audit.CREDENCIAL_ELIMINADA, request=request, usuario=usuario,
                    objeto_tipo="credencial", objeto_id=credencial_id, detalle=detalle)
    return RedirectResponse(f"{url_volver}?msg={quote('Credencial eliminada.')}", status_code=303)


@router.post("/credenciales/{credencial_id}/revelar", dependencies=[Depends(verificar_csrf)])
def credencial_revelar(
    request: Request,
    credencial_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, REVELAR],
):
    """Devuelve la contraseña en claro; el acceso queda registrado en auditoría."""
    credencial = db.get(Credencial, credencial_id)
    if credencial is None:
        raise HTTPException(status_code=404, detail="La credencial no existe.")
    audit.registrar(db, audit.CREDENCIAL_REVELADA, request=request, usuario=usuario,
                    objeto_tipo="credencial", objeto_id=credencial.id,
                    detalle=f"{credencial.usuario_acceso}@{credencial.nombre_activo} ({credencial.servicio})")
    return JSONResponse(
        {"usuario": credencial.usuario_acceso, "password": descifrar(credencial.password_cifrada)},
        headers={"Cache-Control": "no-store"},
    )
