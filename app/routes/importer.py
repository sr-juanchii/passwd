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
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.database import get_db
from app.deps import render, requiere_permiso, verificar_csrf
from app.exporter import exportar_csv, plantilla_csv
from app.models import (
    Credencial,
    DispositivoRed,
    Hipervisor,
    MaquinaVirtual,
    ServidorFisico,
    Usuario,
    normalizar_etiquetas,
)
from app.rbac import tiene_permiso
from app.security.crypto import cifrar

router = APIRouter()

GESTIONAR = Depends(requiere_permiso("inventario.gestionar"))
EXPORTAR = Depends(requiere_permiso("inventario.exportar"))
IMPORTACION_REALIZADA = "importacion_realizada"
_ORDEN = {"servidor": 0, "hipervisor": 1, "dispositivo": 2, "vm": 3, "credencial": 4}


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
    incluir = tiene_permiso(usuario.rol, "inventario.restringir")
    texto = exportar_csv(db, incluir_restringidos=incluir)
    audit.registrar(db, audit.INVENTARIO_EXPORTADO, request=request, usuario=usuario,
                    detalle="Export en claro del inventario (CSV de migración)."
                            + ("" if incluir else " Sin activos restringidos."))
    return _csv_descarga(texto, "inventario-passwd.csv")


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


def _restringido(fila: dict, puede_restringir: bool) -> bool:
    """Lee la columna ``restringido`` del CSV, solo si el usuario puede fijarla.

    Un operador que importe un CSV con la columna marcada NO crea activos
    restringidos: el valor se ignora salvo que tenga ``inventario.restringir``.
    """
    if not puede_restringir:
        return False
    return (fila.get("restringido") or "").strip().lower() in ("si", "sí", "true", "1", "x")


def _procesar_fila(db: Session, fila: dict, puede_restringir: bool = False) -> str:
    """Crea el activo/credencial de una fila. Devuelve un mensaje; lanza ValueError."""
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
            restringido=_restringido(fila, puede_restringir),
            **_hardware(fila),
        ))
        return f"servidor «{nombre}» creado"

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
            restringido=_restringido(fila, puede_restringir),
            **_hardware(fila),
        ))
        return f"hipervisor «{nombre}» creado"

    if tipo == "dispositivo":
        from app.models import TIPO_DISPOSITIVO_SWITCH, TIPOS_DISPOSITIVO

        if not nombre:
            raise ValueError("nombre obligatorio")
        if db.scalar(select(DispositivoRed).where(func.lower(DispositivoRed.nombre) == nombre.lower())):
            raise ValueError(f"ya existe el dispositivo «{nombre}»")
        tipo_dispositivo = (fila.get("tipo_dispositivo") or "").strip().lower()
        if tipo_dispositivo and tipo_dispositivo not in TIPOS_DISPOSITIVO:
            raise ValueError(f"tipo_dispositivo inválido: {tipo_dispositivo}")
        db.add(DispositivoRed(
            nombre=nombre,
            tipo_dispositivo=tipo_dispositivo or TIPO_DISPOSITIVO_SWITCH,
            marca_modelo=(fila.get("marca_modelo") or "").strip(),
            version=(fila.get("version") or "").strip(),
            ip_gestion=(fila.get("ip") or "").strip(),
            ubicacion=(fila.get("ubicacion") or "").strip(),
            puertos=(fila.get("puertos") or "").strip(),
            descripcion=(fila.get("descripcion") or "").strip(),
            numero_serie=(fila.get("numero_serie") or "").strip(),
            garantia_hasta=(fila.get("garantia_hasta") or "").strip(),
            proveedor=(fila.get("proveedor") or "").strip(),
            estado=_estado(fila.get("estado")),
            etiquetas=normalizar_etiquetas(fila.get("etiquetas") or ""),
            restringido=_restringido(fila, puede_restringir),
        ))
        return f"dispositivo «{nombre}» creado"

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
        return f"VM «{nombre}» creada"

    if tipo == "credencial":
        activo_tipo = (fila.get("activo_tipo") or "").strip().lower()
        padre_nombre = (fila.get("padre") or "").strip()
        usuario_acceso = (fila.get("usuario_acceso") or "").strip()
        password = fila.get("password") or ""
        if not usuario_acceso or not password:
            raise ValueError("usuario_acceso y password obligatorios")
        modelo = {"servidor": ServidorFisico, "hipervisor": Hipervisor,
                  "vm": MaquinaVirtual, "dispositivo": DispositivoRed}.get(activo_tipo)
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
            dispositivo_red_id=activo.id if activo_tipo == "dispositivo" else None,
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
