"""Importación masiva de inventario desde CSV (admin/operador).

Pensado para la migración inicial desde una hoja de cálculo existente. El
archivo se procesa **en memoria** (nunca se persiste en disco) y las
contraseñas se cifran al guardarse; se recomienda destruir el CSV de origen
tras la importación, pues contiene secretos en claro.

Formato (una fila por activo o credencial; columna `tipo` discrimina):

    tipo            columnas usadas
    -------------   ---------------------------------------------------------
    servidor        nombre, tipo_servidor(funcion_unica|host_virtualizacion),
                    sistema_operativo, ip, descripcion, estado, etiquetas
    hipervisor      nombre, padre(=nombre del servidor físico), plataforma,
                    version, ip, descripcion, estado, etiquetas
    vm              nombre, padre(=nombre del hipervisor), sistema_operativo,
                    ip, descripcion, estado, etiquetas
    credencial      activo_tipo(servidor|hipervisor|vm), padre(=nombre activo),
                    usuario_acceso, password, servicio, puerto, descripcion

Las filas se procesan por orden de dependencia; los errores por fila no abortan
el resto (se informan al final).
"""

from __future__ import annotations

import csv
import io
from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.database import get_db
from app.deps import render, requiere_permiso, verificar_csrf
from app.models import (
    TIPO_HOST_VIRTUALIZACION,
    TIPOS_SERVIDOR,
    Credencial,
    Hipervisor,
    MaquinaVirtual,
    ServidorFisico,
    Usuario,
    normalizar_etiquetas,
)
from app.security.crypto import cifrar

router = APIRouter()

GESTIONAR = Depends(requiere_permiso("inventario.gestionar"))
IMPORTACION_REALIZADA = "importacion_realizada"
_ORDEN = {"servidor": 0, "hipervisor": 1, "vm": 2, "credencial": 3}


@router.get("/importar")
def importar_form(request: Request, usuario: Annotated[Usuario, GESTIONAR]):
    return render(request, "importar.html", {"usuario_actual": usuario})


def _estado(valor: str) -> str:
    from app.models import ESTADO_ACTIVO, ESTADOS_ACTIVO

    valor = (valor or "").strip().lower()
    return valor if valor in ESTADOS_ACTIVO else ESTADO_ACTIVO


def _procesar_fila(db: Session, fila: dict) -> str:
    """Crea el activo/credencial de una fila. Devuelve un mensaje; lanza ValueError."""
    tipo = (fila.get("tipo") or "").strip().lower()
    nombre = (fila.get("nombre") or "").strip()

    if tipo == "servidor":
        tipo_srv = (fila.get("tipo_servidor") or "funcion_unica").strip()
        if tipo_srv not in TIPOS_SERVIDOR:
            raise ValueError(f"tipo_servidor inválido: {tipo_srv}")
        if not nombre:
            raise ValueError("nombre obligatorio")
        if db.scalar(select(ServidorFisico).where(func.lower(ServidorFisico.nombre) == nombre.lower())):
            raise ValueError(f"ya existe el servidor «{nombre}»")
        db.add(ServidorFisico(
            nombre=nombre, tipo=tipo_srv,
            sistema_operativo=(fila.get("sistema_operativo") or "").strip(),
            ip_gestion=(fila.get("ip") or "").strip(),
            descripcion=(fila.get("descripcion") or "").strip(),
            estado=_estado(fila.get("estado")),
            etiquetas=normalizar_etiquetas(fila.get("etiquetas") or ""),
        ))
        return f"servidor «{nombre}» creado"

    if tipo == "hipervisor":
        padre = db.scalar(select(ServidorFisico).where(
            func.lower(ServidorFisico.nombre) == (fila.get("padre") or "").strip().lower()))
        if padre is None:
            raise ValueError(f"servidor padre «{fila.get('padre')}» no encontrado")
        if padre.tipo != TIPO_HOST_VIRTUALIZACION:
            raise ValueError(f"el servidor «{padre.nombre}» no es host de virtualización")
        if not nombre:
            raise ValueError("nombre obligatorio")
        db.add(Hipervisor(
            servidor_fisico_id=padre.id, nombre=nombre,
            plataforma=(fila.get("plataforma") or "").strip(),
            version=(fila.get("version") or "").strip(),
            ip_gestion=(fila.get("ip") or "").strip(),
            descripcion=(fila.get("descripcion") or "").strip(),
            estado=_estado(fila.get("estado")),
            etiquetas=normalizar_etiquetas(fila.get("etiquetas") or ""),
        ))
        return f"hipervisor «{nombre}» creado"

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
        ))
        return f"VM «{nombre}» creada"

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
        cred = Credencial(
            usuario_acceso=usuario_acceso, password_cifrada=cifrar(password),
            servicio=(fila.get("servicio") or "SSH").strip() or "SSH", puerto=puerto,
            descripcion=(fila.get("descripcion") or "").strip(),
            servidor_fisico_id=activo.id if activo_tipo == "servidor" else None,
            hipervisor_id=activo.id if activo_tipo == "hipervisor" else None,
            maquina_virtual_id=activo.id if activo_tipo == "vm" else None,
        )
        db.add(cred)
        return f"credencial «{usuario_acceso}@{padre_nombre}» creada"

    raise ValueError(f"tipo desconocido: {tipo}")


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

    # Orden de dependencia: servidores → hipervisores → VMs → credenciales,
    # conservando el número de fila original para los mensajes.
    indexadas = sorted(enumerate(filas, start=2), key=_clave_orden)

    creados = 0
    errores: list[str] = []
    for numero, fila in indexadas:
        try:
            with db.begin_nested():
                _procesar_fila(db, fila)
            creados += 1
        except Exception as exc:  # noqa: BLE001 (se informa por fila, no aborta)
            errores.append(f"Fila {numero}: {exc}")

    audit.registrar(db, IMPORTACION_REALIZADA, request=request, usuario=usuario,
                    detalle=f"{creados} elemento(s) importado(s), {len(errores)} con error")
    return render(request, "importar.html", {
        "usuario_actual": usuario, "creados": creados, "errores": errores,
        "total": len(filas),
    })
