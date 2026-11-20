"""Gestión de credenciales en la interfaz clásica (HTML).

Este módulo **solo traduce HTTP ↔ servicio**: formularios, redirecciones y
re-renderizado del formulario con el error. Las reglas —cifrado, control de
acceso por objeto, límite anti-exfiltración, auditoría y la exigencia de una
rotación autorizada para cambiar una contraseña— viven en
``app/servicios/credenciales.py``, compartidas con la API JSON.

Esa compartición es el punto. Hasta la 1.3.0 la entrega de una contraseña en
claro estaba escrita dos veces, aquí y en ``app/api_web/credentials.py``, y
mantenerlas sincronizadas a mano es lo que falló en la 1.2.0.

Esta interfaz **se retira en la 2.0** (rotura R1 de ``docs/plan-v2.0.md``).
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
from app.models import Credencial, Usuario
from app.servicios import credenciales as servicio
from app.servicios.credenciales import SERVICIOS_SUGERIDOS, ErrorCredencial

router = APIRouter()

GESTIONAR = Depends(requiere_permiso("credenciales.gestionar"))
REVELAR = Depends(requiere_permiso("credenciales.revelar"))

SIN_CACHE = {"Cache-Control": "no-store"}

# URL de la ficha del activo, a la que vuelve cada formulario. Es asunto de esta
# interfaz y no del caso de uso, de modo que no vive en el servicio.
_URL_ACTIVO = {
    "fisico": "/servidores/{id}",
    "hipervisor": "/hipervisores/{id}",
    "vm": "/vms/{id}",
    "dispositivo": "/dispositivos/{id}",
}


def _error(exc: ErrorCredencial) -> HTTPException:
    return HTTPException(status_code=exc.codigo, detail=exc.mensaje)


def _url_volver(tipo: str, activo_id: int) -> str:
    plantilla = _URL_ACTIVO.get(tipo)
    if plantilla is None:
        raise HTTPException(status_code=400, detail="Tipo de activo inválido.")
    return plantilla.format(id=activo_id)


def _ctx_form(usuario: Usuario, credencial: Credencial | None, tipo: str, activo, url_volver: str) -> dict:
    return {
        "usuario_actual": usuario,
        "credencial": credencial,
        "tipo_activo": tipo,
        "activo": activo,
        "url_volver": url_volver,
        "servicios": SERVICIOS_SUGERIDOS,
    }


def _puerto_de_formulario(texto: str) -> int | None:
    """El formulario manda texto; el servicio valida el rango."""
    limpio = texto.strip()
    if not limpio:
        return None
    if not limpio.isdigit():
        raise ErrorCredencial("El puerto debe ser un número entre 1 y 65535.")
    return int(limpio)


def _sesion_id(request: Request) -> int | None:
    sesion = getattr(request.state, "sesion", None)
    return sesion.id if sesion is not None else None


@router.get("/credenciales/nueva")
def credencial_nueva_form(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
    activo: str = "",
    activo_id: int = 0,
):
    try:
        instancia, _etiqueta = servicio.resolver_activo(db, activo, activo_id)
        servicio.exigir_ver_activo(db, usuario, activo, activo_id)
    except ErrorCredencial as exc:
        raise _error(exc) from exc
    return render(request, "credencial_form.html",
                  _ctx_form(usuario, None, activo, instancia, _url_volver(activo, activo_id)))


@router.post("/credenciales/nueva", dependencies=[Depends(verificar_csrf)])
def credencial_crear(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
    activo: Annotated[str, Form()] = "",
    activo_id: Annotated[int, Form()] = 0,
    usuario_acceso: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
    servicio_form: Annotated[str, Form(alias="servicio")] = "SSH",
    puerto: Annotated[str, Form()] = "",
    descripcion: Annotated[str, Form()] = "",
    usada_por: Annotated[str, Form()] = "",
):
    try:
        instancia, _etiqueta = servicio.resolver_activo(db, activo, activo_id)
        servicio.exigir_ver_activo(db, usuario, activo, activo_id)
    except ErrorCredencial as exc:
        raise _error(exc) from exc

    url_volver = _url_volver(activo, activo_id)
    try:
        servicio.crear(
            db, usuario=usuario, tipo_activo=activo, activo_id=activo_id,
            usuario_acceso=usuario_acceso, password=password, servicio=servicio_form,
            puerto=_puerto_de_formulario(puerto), descripcion=descripcion,
            usada_por=usada_por, request=request,
        )
    except ErrorCredencial as exc:
        # Un dato mal puesto vuelve al formulario con su mensaje; un problema de
        # autorización es un error HTTP y no una corrección que el usuario pueda
        # hacer en el formulario.
        if exc.codigo != 400:
            raise _error(exc) from exc
        return render(request, "credencial_form.html",
                      {**_ctx_form(usuario, None, activo, instancia, url_volver),
                       "error": exc.mensaje},
                      status_code=400)
    return RedirectResponse(f"{url_volver}?msg={quote('Credencial registrada.')}", status_code=303)


@router.get("/credenciales/{credencial_id}/editar")
def credencial_editar_form(
    request: Request,
    credencial_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
):
    try:
        credencial = servicio.obtener_gestionable(db, usuario, credencial_id)
        tipo, activo_id = servicio.activo_de(credencial)
        instancia, _etiqueta = servicio.resolver_activo(db, tipo, activo_id)
    except ErrorCredencial as exc:
        raise _error(exc) from exc
    return render(request, "credencial_form.html",
                  {**_ctx_form(usuario, credencial, tipo, instancia, _url_volver(tipo, activo_id)),
                   "historial": credencial.historial})


@router.post("/credenciales/{credencial_id}/editar", dependencies=[Depends(verificar_csrf)])
def credencial_editar(
    request: Request,
    credencial_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
    usuario_acceso: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
    servicio_form: Annotated[str, Form(alias="servicio")] = "SSH",
    puerto: Annotated[str, Form()] = "",
    descripcion: Annotated[str, Form()] = "",
    usada_por: Annotated[str, Form()] = "",
):
    try:
        credencial = servicio.obtener_gestionable(db, usuario, credencial_id)
        tipo, activo_id = servicio.activo_de(credencial)
        instancia, _etiqueta = servicio.resolver_activo(db, tipo, activo_id)
    except ErrorCredencial as exc:
        raise _error(exc) from exc

    url_volver = _url_volver(tipo, activo_id)
    try:
        servicio.actualizar(
            db, usuario=usuario, credencial_id=credencial_id,
            usuario_acceso=usuario_acceso, password=password, servicio=servicio_form,
            puerto=_puerto_de_formulario(puerto), descripcion=descripcion,
            usada_por=usada_por, request=request,
        )
    except ErrorCredencial as exc:
        # Incluye el 409 de «hace falta una rotación autorizada»: se explica en
        # el propio formulario, que es donde el operador está mirando.
        if exc.codigo not in (400, 409):
            raise _error(exc) from exc
        return render(request, "credencial_form.html",
                      {**_ctx_form(usuario, credencial, tipo, instancia, url_volver),
                       "historial": credencial.historial, "error": exc.mensaje},
                      status_code=exc.codigo)
    return RedirectResponse(f"{url_volver}?msg={quote('Credencial actualizada.')}", status_code=303)


@router.post("/credenciales/{credencial_id}/eliminar", dependencies=[Depends(verificar_csrf)])
def credencial_eliminar(
    request: Request,
    credencial_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
):
    try:
        credencial = servicio.obtener_gestionable(db, usuario, credencial_id)
        tipo, activo_id = servicio.activo_de(credencial)
        servicio.eliminar(db, usuario=usuario, credencial_id=credencial_id, request=request)
    except ErrorCredencial as exc:
        raise _error(exc) from exc
    return RedirectResponse(f"{_url_volver(tipo, activo_id)}?msg={quote('Credencial eliminada.')}",
                            status_code=303)


@router.post("/credenciales/{credencial_id}/revelar", dependencies=[Depends(verificar_csrf)])
def credencial_revelar(
    request: Request,
    credencial_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, REVELAR],
):
    """Muestra la contraseña en pantalla; queda registrado en auditoría."""
    return _entregar(request, db, usuario, credencial_id, audit.CREDENCIAL_REVELADA)


@router.post("/credenciales/{credencial_id}/copiar", dependencies=[Depends(verificar_csrf)])
def credencial_copiar(
    request: Request,
    credencial_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, REVELAR],
):
    """Entrega la contraseña para copiarla al portapapeles sin mostrarla.

    Reduce la exposición visual (*shoulder surfing*); se audita con una acción
    propia para distinguirla del revelado en pantalla.
    """
    return _entregar(request, db, usuario, credencial_id, audit.CREDENCIAL_COPIADA)


def _entregar(
    request: Request, db: Session, usuario: Usuario, credencial_id: int, accion: str
) -> JSONResponse:
    try:
        datos = servicio.entregar_password(
            db, usuario=usuario, credencial_id=credencial_id, accion=accion,
            request=request, sesion_id=_sesion_id(request),
        )
    except ErrorCredencial as exc:
        raise _error(exc) from exc
    return JSONResponse(datos, headers=SIN_CACHE)


@router.post("/credenciales/{credencial_id}/historial/{historial_id}/revelar",
             dependencies=[Depends(verificar_csrf)])
def historial_revelar(
    request: Request,
    credencial_id: int,
    historial_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
):
    """Revela una contraseña anterior (solo gestores; auditado y limitado)."""
    try:
        datos = servicio.revelar_historial(
            db, usuario=usuario, credencial_id=credencial_id,
            historial_id=historial_id, request=request,
        )
    except ErrorCredencial as exc:
        raise _error(exc) from exc
    return JSONResponse(datos, headers=SIN_CACHE)
