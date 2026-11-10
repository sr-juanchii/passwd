"""Procesado de filas del CSV de importación, compartido por las dos interfaces.

Única implementación de la creación de activos y credenciales a partir de una
fila: la usan ``app/api_web/importer.py`` (JSON) y ``app/routes/importer.py``
(Jinja) para que las reglas de acceso no puedan divergir entre ambas.

Quien no tiene ``inventario.restringir`` no puede colgar máquinas virtuales ni
credenciales de activos restringidos a administradores: para ese usuario el
activo "no existe" (mismo mensaje que un nombre inexistente, sin filtrar nada).
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Credencial,
    DispositivoRed,
    Hipervisor,
    MaquinaVirtual,
    ServidorFisico,
    normalizar_etiquetas,
)
from app.security.crypto import cifrar

ORDEN = {"servidor": 0, "hipervisor": 1, "dispositivo": 2, "vm": 3, "credencial": 4}


def _oculto(db: Session, activo, puede_restringir: bool) -> bool:
    """¿El activo está restringido y el usuario no puede operar sobre él?"""
    if puede_restringir or activo is None:
        return False
    if isinstance(activo, MaquinaVirtual):
        hipervisor = db.get(Hipervisor, activo.hipervisor_id)
        return bool(hipervisor is not None and hipervisor.restringido)
    return bool(getattr(activo, "restringido", False))


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
    """Lee la columna ``restringido`` del CSV, solo si el usuario puede fijarla."""
    if not puede_restringir:
        return False
    return (fila.get("restringido") or "").strip().lower() in ("si", "sí", "true", "1", "x")


def procesar_fila(db: Session, fila: dict, puede_restringir: bool = False) -> str:
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
            restringido=_restringido(fila, puede_restringir),
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
            restringido=_restringido(fila, puede_restringir),
            **_hardware(fila),
        ))
        return "hipervisor"

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
        return "dispositivo"

    if tipo == "vm":
        padre = db.scalar(select(Hipervisor).where(
            func.lower(Hipervisor.nombre) == (fila.get("padre") or "").strip().lower()))
        if padre is None or _oculto(db, padre, puede_restringir):
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
        modelo = {"servidor": ServidorFisico, "hipervisor": Hipervisor,
                  "vm": MaquinaVirtual, "dispositivo": DispositivoRed}.get(activo_tipo)
        if modelo is None:
            raise ValueError(f"activo_tipo inválido: {activo_tipo}")
        activo = db.scalar(select(modelo).where(func.lower(modelo.nombre) == padre_nombre.lower()))
        if activo is None or _oculto(db, activo, puede_restringir):
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
            dispositivo_red_id=activo.id if activo_tipo == "dispositivo" else None,
        ))
        return "credencial"

    raise ValueError(f"tipo desconocido: {tipo}")

