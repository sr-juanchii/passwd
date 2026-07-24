"""Configuración del sistema en tiempo de ejecución (solo administradores).

Permite a un administrador ajustar parámetros operativos (sesión, política de
cuentas, límites de tasa, rotación/auditoría y notificaciones por correo) sin
reiniciar ni redeplegar. Los cambios se guardan en la tabla ``configuracion``,
se aplican al instante y quedan auditados. Ver ``app/ajustes.py``.
"""

from __future__ import annotations

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app import ajustes, audit, notifications
from app.ajustes import REGISTRO, ErrorAjuste
from app.database import get_db
from app.deps import render, requiere_permiso, verificar_csrf
from app.models import Usuario

router = APIRouter()

GESTIONAR = Depends(requiere_permiso("configuracion.gestionar"))


@router.get("/configuracion")
def configuracion_form(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
    msg: str = "",
    error: str = "",
):
    return render(request, "configuracion.html", {
        "usuario_actual": usuario,
        "grupos": ajustes.snapshot(db),
        "info_sistema": ajustes.info_sistema(),
        "msg": msg,
        "error": error,
    })


@router.post("/configuracion", dependencies=[Depends(verificar_csrf)])
async def configuracion_guardar(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
):
    formulario = await request.form()
    # Se construye el lote desde el REGISTRO (no desde el formulario) para tratar
    # bien las casillas: una casilla no marcada no se envía → booleano en falso.
    cambios: dict[str, object] = {}
    for ajuste in REGISTRO:
        if ajuste.tipo == "booleano":
            cambios[ajuste.clave] = formulario.get(ajuste.clave) is not None
        elif ajuste.es_secreto:
            valor = str(formulario.get(ajuste.clave) or "")
            if valor:  # un secreto vacío significa «no cambiar»
                cambios[ajuste.clave] = valor
        else:
            cambios[ajuste.clave] = str(formulario.get(ajuste.clave, ""))
    try:
        modificadas = ajustes.guardar(db, cambios, usuario, request=request)
    except ErrorAjuste as exc:
        return RedirectResponse(f"/configuracion?error={quote(str(exc))}", status_code=303)
    msg = f"{len(modificadas)} ajuste(s) actualizado(s)." if modificadas else "Sin cambios."
    return RedirectResponse(f"/configuracion?msg={quote(msg)}", status_code=303)


@router.post("/configuracion/restablecer", dependencies=[Depends(verificar_csrf)])
async def configuracion_restablecer(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
):
    formulario = await request.form()
    clave = str(formulario.get("clave", ""))
    try:
        cambiado = ajustes.restablecer(db, clave, usuario, request=request)
    except ErrorAjuste as exc:
        return RedirectResponse(f"/configuracion?error={quote(str(exc))}", status_code=303)
    msg = "Ajuste restablecido al valor base." if cambiado else "El ajuste ya usaba el valor base."
    return RedirectResponse(f"/configuracion?msg={quote(msg)}", status_code=303)


@router.post("/configuracion/probar-correo", dependencies=[Depends(verificar_csrf)])
async def configuracion_probar_correo(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
):
    formulario = await request.form()
    destinatario = str(formulario.get("destinatario", ""))
    try:
        enviados = notifications.enviar_prueba(destinatario)
    except notifications.ErrorCorreo as exc:
        audit.registrar(db, audit.CORREO_PRUEBA, request=request, usuario=usuario,
                        detalle=f"Prueba de correo fallida: {exc}", exito=False)
        return RedirectResponse(f"/configuracion?error={quote(str(exc))}", status_code=303)
    audit.registrar(db, audit.CORREO_PRUEBA, request=request, usuario=usuario,
                    detalle=f"Correo de prueba enviado a {len(enviados)} destinatario(s).")
    return RedirectResponse(
        f"/configuracion?msg={quote('Correo de prueba enviado correctamente.')}", status_code=303
    )
