"""Importación masiva de inventario por CSV en JSON (admin/operador).

Replica ``app/routes/importer.py``: el archivo se procesa en memoria, nunca se
persiste, las contraseñas se cifran al guardarse y los errores por fila no
abortan el lote. Devuelve un resumen con conteos por tipo.
"""

from __future__ import annotations

import csv
import io
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from app import audit
from app.api_web.deps import requiere_permiso_json, verificar_csrf_json
from app.database import get_db
from app.importacion import ORDEN as _ORDEN
from app.importacion import procesar_fila as _procesar_fila
from app.models import Usuario
from app.rbac import tiene_permiso

router = APIRouter()

GESTIONAR = Depends(requiere_permiso_json("inventario.gestionar"))
CSRF = Depends(verificar_csrf_json)
IMPORTACION_REALIZADA = "importacion_realizada"



@router.post("/importar", dependencies=[CSRF])
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
        raise HTTPException(status_code=400, detail="El archivo no es UTF-8 válido.") from None

    filas = list(csv.DictReader(io.StringIO(texto)))

    def _clave_orden(par: tuple[int, dict]) -> int:
        return _ORDEN.get((par[1].get("tipo") or "").strip().lower(), 9)

    indexadas = sorted(enumerate(filas, start=2), key=_clave_orden)

    puede_restringir = tiene_permiso(usuario.rol, "inventario.restringir")
    creados = {"servidor": 0, "hipervisor": 0, "dispositivo": 0, "vm": 0, "credencial": 0}
    errores: list[str] = []
    for numero, fila in indexadas:
        try:
            with db.begin_nested():
                tipo_creado = _procesar_fila(db, fila, puede_restringir)
            creados[tipo_creado] += 1
        except Exception as exc:  # noqa: BLE001 (se informa por fila, no aborta)
            errores.append(f"Fila {numero}: {exc}")

    total_creados = sum(creados.values())
    audit.registrar(db, IMPORTACION_REALIZADA, request=request, usuario=usuario,
                    detalle=f"{total_creados} elemento(s) importado(s), {len(errores)} con error")
    db.commit()
    return {"creados": creados, "errores": errores, "total": len(filas)}
