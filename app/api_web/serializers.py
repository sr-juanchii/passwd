"""Serializadores de modelos a los dicts del contrato de la API JSON.

Nunca exponen secretos: contraseñas, notas en claro ni semillas TOTP. Las
contraseñas solo se entregan en los endpoints de revelado/copiado, jamás aquí.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app import access
from app.config import get_settings
from app.models import (
    NIVEL_VER,
    ConcesionAcceso,
    Credencial,
    Hipervisor,
    MaquinaVirtual,
    RegistroAuditoria,
    ServidorFisico,
    TokenApi,
    Usuario,
)
from app.rbac import ETIQUETAS_ROL

NIVELES_LABEL = {
    NIVEL_VER: "Ver",
    "ver_credenciales": "Ver y revelar credenciales",
}


def _iso(valor) -> str | None:
    return valor.isoformat() if valor is not None else None


def serializar_usuario(usuario: Usuario) -> dict:
    return {
        "id": usuario.id,
        "username": usuario.username,
        "email": usuario.email,
        "nombre_completo": usuario.nombre_completo,
        "rol": usuario.rol,
        "rol_label": ETIQUETAS_ROL.get(usuario.rol, usuario.rol),
        "mfa_habilitado": usuario.mfa_habilitado,
        "activo": usuario.activo,
        "ultimo_acceso": _iso(usuario.ultimo_acceso),
    }


def serializar_credencial(db: Session, usuario: Usuario, credencial: Credencial) -> dict:
    settings = get_settings()
    return {
        "id": credencial.id,
        "usuario_acceso": credencial.usuario_acceso,
        "servicio": credencial.servicio,
        "puerto": credencial.puerto,
        "descripcion": credencial.descripcion,
        "dias_sin_rotar": credencial.dias_sin_rotar,
        "rotacion_vencida": credencial.dias_sin_rotar > settings.rotation_max_days,
        "puede_revelar": access.puede_revelar_credencial(db, usuario, credencial),
        "tipo_activo": credencial.tipo_activo,
        "activo_id": (
            credencial.servidor_fisico_id
            or credencial.hipervisor_id
            or credencial.maquina_virtual_id
        ),
    }


def serializar_concesion(concesion: ConcesionAcceso) -> dict:
    return {
        "id": concesion.id,
        "usuario_id": concesion.usuario_id,
        "username": concesion.usuario.username if concesion.usuario else "",
        "nombre_completo": concesion.usuario.nombre_completo if concesion.usuario else "",
        "nivel": concesion.nivel,
        "nivel_label": NIVELES_LABEL.get(concesion.nivel, concesion.nivel),
        "expira_en": _iso(concesion.expira_en),
        "expirada": concesion.expirada,
        "tipo": concesion.tipo_activo,
        "activo_id": (
            concesion.servidor_fisico_id
            or concesion.hipervisor_id
            or concesion.maquina_virtual_id
        ),
        "activo_nombre": concesion.nombre_activo,
    }


def serializar_registro(registro: RegistroAuditoria) -> dict:
    return {
        "id": registro.id,
        "fecha": _iso(registro.fecha),
        "usuario": registro.username,
        "accion": registro.accion,
        "objeto_tipo": registro.objeto_tipo,
        "objeto_id": registro.objeto_id,
        "detalle": registro.detalle,
        "direccion_ip": registro.direccion_ip,
        "agente_usuario": registro.agente_usuario,
        "exito": registro.exito,
    }


def serializar_token(token: TokenApi) -> dict:
    return {
        "id": token.id,
        "nombre": token.nombre,
        "creado_en": _iso(token.creado_en),
        "ultimo_uso": _iso(token.ultimo_uso),
        "activo": token.activo,
        "creado_por": token.creado_por.username if token.creado_por else None,
    }


# ---------------------------------------------------------------------------
# Árbol del inventario (dashboard)
# ---------------------------------------------------------------------------


def _credenciales_de(db: Session, usuario: Usuario, credenciales) -> list[dict]:
    return [serializar_credencial(db, usuario, c) for c in credenciales]


def serializar_vm_nodo(db: Session, usuario: Usuario, vm: MaquinaVirtual) -> dict:
    return {
        "id": vm.id,
        "nombre": vm.nombre,
        "sistema_operativo": vm.sistema_operativo,
        "estado": vm.estado,
        "credenciales": _credenciales_de(db, usuario, vm.credenciales),
    }


def serializar_hipervisor_nodo(db: Session, usuario: Usuario, hipervisor: Hipervisor) -> dict:
    return {
        "id": hipervisor.id,
        "nombre": hipervisor.nombre,
        "plataforma": hipervisor.plataforma,
        "estado": hipervisor.estado,
        "credenciales": _credenciales_de(db, usuario, hipervisor.credenciales),
        "vms": [serializar_vm_nodo(db, usuario, v) for v in hipervisor.maquinas_virtuales],
    }


def serializar_servidor_nodo(db: Session, usuario: Usuario, servidor: ServidorFisico) -> dict:
    return {
        "id": servidor.id,
        "nombre": servidor.nombre,
        "tipo": servidor.tipo,
        "etiqueta_tipo": servidor.etiqueta_tipo,
        "estado": servidor.estado,
        "ip_gestion": servidor.ip_gestion,
        "etiquetas": servidor.lista_etiquetas,
        "credenciales": _credenciales_de(db, usuario, servidor.credenciales),
        "hipervisores": [serializar_hipervisor_nodo(db, usuario, h) for h in servidor.hipervisores],
    }


# ---------------------------------------------------------------------------
# Detalle de cada activo
# ---------------------------------------------------------------------------


def serializar_servidor_detalle(servidor: ServidorFisico) -> dict:
    return {
        "id": servidor.id,
        "nombre": servidor.nombre,
        "tipo": servidor.tipo,
        "etiqueta_tipo": servidor.etiqueta_tipo,
        "descripcion": servidor.descripcion,
        "sistema_operativo": servidor.sistema_operativo,
        "marca_modelo": servidor.marca_modelo,
        "ubicacion": servidor.ubicacion,
        "ip_gestion": servidor.ip_gestion,
        "ram": servidor.ram,
        "cpu": servidor.cpu,
        "almacenamiento": servidor.almacenamiento,
        "numero_serie": servidor.numero_serie,
        "garantia_hasta": servidor.garantia_hasta,
        "proveedor": servidor.proveedor,
        "estado": servidor.estado,
        "etiquetas": servidor.etiquetas,
        "lista_etiquetas": servidor.lista_etiquetas,
    }


def serializar_hipervisor_detalle(hipervisor: Hipervisor) -> dict:
    return {
        "id": hipervisor.id,
        "nombre": hipervisor.nombre,
        "plataforma": hipervisor.plataforma,
        "version": hipervisor.version,
        "ip_gestion": hipervisor.ip_gestion,
        "descripcion": hipervisor.descripcion,
        "estado": hipervisor.estado,
        "etiquetas": hipervisor.etiquetas,
        "lista_etiquetas": hipervisor.lista_etiquetas,
        "servidor_fisico_id": hipervisor.servidor_fisico_id,
        "servidor_fisico_nombre": (
            hipervisor.servidor_fisico.nombre if hipervisor.servidor_fisico else ""
        ),
    }


def serializar_vm_detalle(vm: MaquinaVirtual) -> dict:
    return {
        "id": vm.id,
        "nombre": vm.nombre,
        "sistema_operativo": vm.sistema_operativo,
        "ip": vm.ip,
        "descripcion": vm.descripcion,
        "estado": vm.estado,
        "etiquetas": vm.etiquetas,
        "lista_etiquetas": vm.lista_etiquetas,
        "hipervisor_id": vm.hipervisor_id,
        "hipervisor_nombre": vm.hipervisor.nombre if vm.hipervisor else "",
    }


def serializar_hipervisor_breve(hipervisor: Hipervisor) -> dict:
    return {
        "id": hipervisor.id,
        "nombre": hipervisor.nombre,
        "plataforma": hipervisor.plataforma,
        "estado": hipervisor.estado,
    }


def serializar_vm_breve(vm: MaquinaVirtual) -> dict:
    return {
        "id": vm.id,
        "nombre": vm.nombre,
        "sistema_operativo": vm.sistema_operativo,
        "estado": vm.estado,
    }


def serializar_analista(usuario: Usuario) -> dict:
    return {
        "id": usuario.id,
        "username": usuario.username,
        "nombre_completo": usuario.nombre_completo,
    }
