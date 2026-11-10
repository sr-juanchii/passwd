"""Importación masiva de inventario desde CSV (admin/operador).

Pensado para la migración inicial desde una hoja de cálculo existente. El
archivo se procesa **en memoria** (nunca se persiste en disco) y las
contraseñas se cifran al guardarse; se recomienda destruir el CSV de origen
tras la importación, pues contiene secretos en claro.

Formato (una fila por activo o credencial; columna `tipo` discrimina):

    tipo            columnas usadas
    -------------   ---------------------------------------------------------
    servidor        nombre, sistema_operativo, ip, descripcion, estado, etiquetas
                    (+ hardware opcional: marca_modelo, ubicacion, ram, cpu,
                    almacenamiento, numero_serie, garantia_hasta, proveedor)
    hipervisor      nombre, plataforma, version, ip, descripcion, estado,
                    etiquetas (+ los mismos campos de hardware opcionales);
                    es un activo de nivel superior, no requiere padre
    vm              nombre, padre(=nombre del hipervisor), sistema_operativo,
                    ip, descripcion, estado, etiquetas
    dispositivo     nombre, tipo_dispositivo(switch|router|firewall|
                    access_point|balanceador|otro), marca_modelo, version,
                    ip, ubicacion, puertos, descripcion, estado, etiquetas
                    (+ numero_serie, garantia_hasta, proveedor); activo de
                    nivel superior, no requiere padre
    credencial      activo_tipo(servidor|hipervisor|vm|dispositivo),
                    padre(=nombre activo), usuario_acceso, password,
                    servicio, puerto, descripcion

Las filas se procesan por orden de dependencia; los errores por fila no abortan
el resto (se informan al final).
"""

from __future__ import annotations

import csv
import io
from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app import audit
from app.database import get_db
from app.deps import render, requiere_permiso, verificar_csrf
from app.exporter import LimiteExportacion, exportar_auditado, plantilla_csv
from app.importacion import ORDEN as _ORDEN
from app.importacion import procesar_fila as _procesar_fila
from app.models import Usuario
from app.rbac import tiene_permiso

router = APIRouter()

GESTIONAR = Depends(requiere_permiso("inventario.gestionar"))
EXPORTAR = Depends(requiere_permiso("inventario.exportar"))
IMPORTACION_REALIZADA = "importacion_realizada"


def _csv_descarga(texto: str, nombre: str) -> Response:
    return Response(
        content=texto,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{nombre}"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/importar")
def importar_form(request: Request, usuario: Annotated[Usuario, GESTIONAR]):
    return render(request, "importar.html", {"usuario_actual": usuario})


@router.get("/plantilla.csv")
def plantilla_descargar(usuario: Annotated[Usuario, GESTIONAR]):
    """Plantilla CSV de ejemplo (sin secretos) para arrancar una importación."""
    return _csv_descarga(plantilla_csv(), "plantilla-passwd.csv")


@router.post("/exportar", dependencies=[Depends(verificar_csrf)])
def exportar(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, EXPORTAR],
):
    """Export EN CLARO del inventario para migración (CSV round-trip con importar).

    El operador no exporta los activos restringidos a administradores.
    """
    try:
        texto = exportar_auditado(db, request, usuario)
    except LimiteExportacion as exc:
        return render(request, "importar.html",
                      {"usuario_actual": usuario, "error": str(exc)}, status_code=429)
    return _csv_descarga(texto, "inventario-passwd.csv")


@router.post("/importar", dependencies=[Depends(verificar_csrf)])
def importar(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, GESTIONAR],
    archivo: Annotated[UploadFile, File()],
):
    contenido = archivo.file.read()  # en memoria; nunca se persiste
    try:
        texto = contenido.decode("utf-8-sig")
    except UnicodeDecodeError:
        return render(request, "importar.html",
                      {"usuario_actual": usuario, "error": "El archivo no es UTF-8 válido."}, status_code=400)

    filas = list(csv.DictReader(io.StringIO(texto)))

    def _clave_orden(par: tuple[int, dict]) -> int:
        return _ORDEN.get((par[1].get("tipo") or "").strip().lower(), 9)

    # Orden de dependencia: servidores → hipervisores → dispositivos → VMs →
    # credenciales, conservando el número de fila original para los mensajes.
    indexadas = sorted(enumerate(filas, start=2), key=_clave_orden)

    puede_restringir = tiene_permiso(usuario.rol, "inventario.restringir")
    creados = 0
    errores: list[str] = []
    for numero, fila in indexadas:
        try:
            with db.begin_nested():
                _procesar_fila(db, fila, puede_restringir)
            creados += 1
        except Exception as exc:  # noqa: BLE001 (se informa por fila, no aborta)
            errores.append(f"Fila {numero}: {exc}")

    audit.registrar(db, IMPORTACION_REALIZADA, request=request, usuario=usuario,
                    detalle=f"{creados} elemento(s) importado(s), {len(errores)} con error")
    return render(request, "importar.html", {
        "usuario_actual": usuario, "creados": creados, "errores": errores,
        "total": len(filas),
    })
