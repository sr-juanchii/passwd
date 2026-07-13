"""Export en claro del inventario para migración, en JSON (`/api/web`).

Devuelve un CSV descargable con las credenciales y su contraseña en claro, en el
formato del importador (round-trip). Restringido a ``inventario.exportar``,
auditado y con ``Cache-Control: no-store``. La plantilla de ejemplo no lleva
secretos y solo exige el permiso de gestión (ayuda para importar).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app import audit
from app.api_web.deps import requiere_permiso_json, verificar_csrf_json
from app.database import get_db
from app.exporter import exportar_csv, plantilla_csv
from app.models import Usuario

router = APIRouter()

EXPORTAR = Depends(requiere_permiso_json("inventario.exportar"))
GESTIONAR = Depends(requiere_permiso_json("inventario.gestionar"))
CSRF = Depends(verificar_csrf_json)


def _csv(texto: str, nombre: str) -> Response:
    return Response(
        content=texto,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{nombre}"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/exportar", dependencies=[CSRF])
def exportar(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, EXPORTAR],
):
    texto = exportar_csv(db)
    audit.registrar(db, audit.INVENTARIO_EXPORTADO, request=request, usuario=usuario,
                    detalle="Export en claro del inventario (CSV de migración).")
    return _csv(texto, "inventario-passwd.csv")


@router.get("/plantilla.csv")
def plantilla(usuario: Annotated[Usuario, GESTIONAR]):
    return _csv(plantilla_csv(), "plantilla-passwd.csv")
