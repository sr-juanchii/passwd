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
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.api_web.deps import requiere_permiso_json, verificar_csrf_json
from app.database import get_db
from app.models import (
    Credencial,
    Hipervisor,
    MaquinaVirtual,
    ServidorFisico,
    Usuario,
    normalizar_etiquetas,
)
from app.security.crypto import cifrar

router = APIRouter()

GESTIONAR = Depends(requiere_permiso_json("inventario.gestionar"))
CSRF = Depends(verificar_csrf_json)
IMPORTACION_REALIZADA = "importacion_realizada"
_ORDEN = {"servidor": 0, "hipervisor": 1, "vm": 2, "credencial": 3}


def _estado(valor: str) -> str:
    from app.models import ESTADO_ACTIVO, ESTADOS_ACTIVO

    valor = (valor or "").strip().lower()
    return valor if valor in ESTADOS_ACTIVO else ESTADO_ACTIVO


def _hardware(fila: dict) -> dict:
    """Campos de hardware opcionales compartidos por servidor e hipervisor."""
    return {
        "marca_modelo": (fila.get("marca_modelo") or "").strip(),
        "ubicacion": (fila.get("ubicacion") or "").strip(),
        "ram": (fila.get("ram") or "").strip(),
        "cpu": (fila.get("cpu") or "").strip(),
        "almacenamiento": (fila.get("almacenamiento") or "").strip(),
        "numero_serie": (fila.get("numero_serie") or "").strip(),
        "garantia_hasta": (fila.get("garantia_hasta") or "").strip(),
        "proveedor": (fila.get("proveedor") or "").strip(),
    }


def _procesar_fila(db: Session, fila: dict) -> str:
    """Crea el activo/credencial de una fila y devuelve su tipo. Lanza ValueError."""
    tipo = (fila.get("tipo") or "").strip().lower()
    nombre = (fila.get("nombre") or "").strip()

    if tipo == "servidor":
        if not nombre:
            raise ValueError("nombre obligatorio")
        if db.scalar(select(ServidorFisico).where(func.lower(ServidorFisico.nombre) == nombre.lower())):
            raise ValueError(f"ya existe el servidor «{nombre}»")
        db.add(ServidorFisico(
            nombre=nombre,
            sistema_operativo=(fila.get("sistema_operativo") or "").strip(),
            ip_gestion=(fila.get("ip") or "").strip(),
            descripcion=(fila.get("descripcion") or "").strip(),
            estado=_estado(fila.get("estado")),
            etiquetas=normalizar_etiquetas(fila.get("etiquetas") or ""),
            **_hardware(fila),
        ))
        return "servidor"

    if tipo == "hipervisor":
        if not nombre:
            raise ValueError("nombre obligatorio")
        if db.scalar(select(Hipervisor).where(func.lower(Hipervisor.nombre) == nombre.lower())):
            raise ValueError(f"ya existe el hipervisor «{nombre}»")
        db.add(Hipervisor(
            nombre=nombre,
            plataforma=(fila.get("plataforma") or "").strip(),
            version=(fila.get("version") or "").strip(),
            ip_gestion=(fila.get("ip") or "").strip(),
            descripcion=(fila.get("descripcion") or "").strip(),
            estado=_estado(fila.get("estado")),
            etiquetas=normalizar_etiquetas(fila.get("etiquetas") or ""),
            **_hardware(fila),
        ))
        return "hipervisor"

    if tipo == "vm":
        padre = db.scalar(select(Hipervisor).where(
            func.lower(Hipervisor.nombre) == (fila.get("padre") or "").strip().lower()))
        if padre is None:
            raise ValueError(f"hipervisor padre «{fila.get('padre')}» no encontrado")
        if not nombre:
            raise ValueError("nombre obligatorio")
        db.add(MaquinaVirtual(
            hipervisor_id=padre.id, nombre=nombre,
            sistema_operativo=(fila.get("sistema_operativo") or "").strip(),
            ip=(fila.get("ip") or "").strip(),
            descripcion=(fila.get("descripcion") or "").strip(),
            estado=_estado(fila.get("estado")),
            etiquetas=normalizar_etiquetas(fila.get("etiquetas") or ""),
            ram=(fila.get("ram") or "").strip(),
            cpu=(fila.get("cpu") or "").strip(),
            almacenamiento=(fila.get("almacenamiento") or "").strip(),
        ))
        return "vm"

    if tipo == "credencial":
        activo_tipo = (fila.get("activo_tipo") or "").strip().lower()
        padre_nombre = (fila.get("padre") or "").strip()
        usuario_acceso = (fila.get("usuario_acceso") or "").strip()
        password = fila.get("password") or ""
        if not usuario_acceso or not password:
            raise ValueError("usuario_acceso y password obligatorios")
        modelo = {"servidor": ServidorFisico, "hipervisor": Hipervisor, "vm": MaquinaVirtual}.get(activo_tipo)
        if modelo is None:
            raise ValueError(f"activo_tipo inválido: {activo_tipo}")
        activo = db.scalar(select(modelo).where(func.lower(modelo.nombre) == padre_nombre.lower()))
        if activo is None:
            raise ValueError(f"activo «{padre_nombre}» ({activo_tipo}) no encontrado")
        puerto_txt = (fila.get("puerto") or "").strip()
        puerto = int(puerto_txt) if puerto_txt.isdigit() and 1 <= int(puerto_txt) <= 65535 else None
        db.add(Credencial(
            usuario_acceso=usuario_acceso, password_cifrada=cifrar(password),
            servicio=(fila.get("servicio") or "SSH").strip() or "SSH", puerto=puerto,
            descripcion=(fila.get("descripcion") or "").strip(),
            servidor_fisico_id=activo.id if activo_tipo == "servidor" else None,
            hipervisor_id=activo.id if activo_tipo == "hipervisor" else None,
            maquina_virtual_id=activo.id if activo_tipo == "vm" else None,
        ))
        return "credencial"

    raise ValueError(f"tipo desconocido: {tipo}")


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

    creados = {"servidor": 0, "hipervisor": 0, "vm": 0, "credencial": 0}
    errores: list[str] = []
    for numero, fila in indexadas:
        try:
            with db.begin_nested():
                tipo_creado = _procesar_fila(db, fila)
            creados[tipo_creado] += 1
        except Exception as exc:  # noqa: BLE001 (se informa por fila, no aborta)
            errores.append(f"Fila {numero}: {exc}")

    total_creados = sum(creados.values())
    audit.registrar(db, IMPORTACION_REALIZADA, request=request, usuario=usuario,
                    detalle=f"{total_creados} elemento(s) importado(s), {len(errores)} con error")
    db.commit()
    return {"creados": creados, "errores": errores, "total": len(filas)}
