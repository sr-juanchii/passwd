"""Respaldo cifrado y restauración del sistema completo (CIS 11.2).

El respaldo incluye usuarios, inventario, credenciales, códigos de
recuperación y bitácora de auditoría. Los secretos viajan dentro de una carga
JSON cifrada con una clave derivada (scrypt) de una frase de respaldo, de
modo que el archivo es portable entre instancias con claves de cifrado
distintas. Sin la frase, el archivo es inservible.
"""

from __future__ import annotations

import base64
import json
import secrets
from datetime import datetime

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.models import (
    ESTADO_ACTIVO,
    CodigoRecuperacionMFA,
    Credencial,
    Hipervisor,
    MaquinaVirtual,
    RegistroAuditoria,
    ServidorFisico,
    SesionWeb,
    Usuario,
    ahora_utc,
)
from app.security.crypto import cifrar, descifrar

FORMATO = "respaldo-passwd"
VERSION = 1
LARGO_MINIMO_FRASE = 12


class ErrorRespaldo(Exception):
    pass


def _clave_desde_frase(frase: str, salt: bytes) -> bytes:
    kdf = Scrypt(salt=salt, length=32, n=2**14, r=8, p=1)
    return base64.urlsafe_b64encode(kdf.derive(frase.encode("utf-8")))


def _fecha(valor: datetime | None) -> str | None:
    return valor.isoformat() if valor is not None else None


def _parse_fecha(valor: str | None) -> datetime | None:
    return datetime.fromisoformat(valor) if valor else None


def exportar(db: Session, frase: str) -> bytes:
    """Serializa y cifra todo el contenido; devuelve el archivo de respaldo."""
    if len(frase) < LARGO_MINIMO_FRASE:
        raise ErrorRespaldo(f"La frase de respaldo debe tener al menos {LARGO_MINIMO_FRASE} caracteres.")

    carga = {
        "version": VERSION,
        "creado_en": ahora_utc().isoformat(),
        "usuarios": [
            {
                "id": u.id, "username": u.username, "email": u.email,
                "nombre_completo": u.nombre_completo, "password_hash": u.password_hash,
                "rol": u.rol, "mfa_habilitado": u.mfa_habilitado,
                "totp_secret": descifrar(u.totp_secret_cifrado) if u.totp_secret_cifrado else None,
                "ultimo_otp_usado": u.ultimo_otp_usado, "activo": u.activo,
                "debe_cambiar_password": u.debe_cambiar_password,
                "password_cambiada_en": _fecha(u.password_cambiada_en),
                "ultimo_acceso": _fecha(u.ultimo_acceso), "creado_en": _fecha(u.creado_en),
            }
            for u in db.scalars(select(Usuario)).all()
        ],
        "codigos_recuperacion": [
            {"usuario_id": c.usuario_id, "codigo_hash": c.codigo_hash,
             "creado_en": _fecha(c.creado_en), "usado_en": _fecha(c.usado_en)}
            for c in db.scalars(select(CodigoRecuperacionMFA)).all()
        ],
        "servidores_fisicos": [
            {"id": s.id, "nombre": s.nombre, "descripcion": s.descripcion,
             "sistema_operativo": s.sistema_operativo, "marca_modelo": s.marca_modelo,
             "ubicacion": s.ubicacion, "ip_gestion": s.ip_gestion, "ram": s.ram, "cpu": s.cpu,
             "almacenamiento": s.almacenamiento, "numero_serie": s.numero_serie,
             "garantia_hasta": s.garantia_hasta, "proveedor": s.proveedor,
             "estado": s.estado, "etiquetas": s.etiquetas, "creado_en": _fecha(s.creado_en)}
            for s in db.scalars(select(ServidorFisico)).all()
        ],
        "hipervisores": [
            {"id": h.id, "nombre": h.nombre, "plataforma": h.plataforma, "version": h.version,
             "ip_gestion": h.ip_gestion, "descripcion": h.descripcion, "marca_modelo": h.marca_modelo,
             "ubicacion": h.ubicacion, "ram": h.ram, "cpu": h.cpu, "almacenamiento": h.almacenamiento,
             "numero_serie": h.numero_serie, "garantia_hasta": h.garantia_hasta, "proveedor": h.proveedor,
             "estado": h.estado, "etiquetas": h.etiquetas, "creado_en": _fecha(h.creado_en)}
            for h in db.scalars(select(Hipervisor)).all()
        ],
        "maquinas_virtuales": [
            {"id": v.id, "hipervisor_id": v.hipervisor_id, "nombre": v.nombre,
             "sistema_operativo": v.sistema_operativo, "ip": v.ip,
             "descripcion": v.descripcion, "creado_en": _fecha(v.creado_en)}
            for v in db.scalars(select(MaquinaVirtual)).all()
        ],
        "credenciales": [
            {"id": c.id, "servidor_fisico_id": c.servidor_fisico_id,
             "hipervisor_id": c.hipervisor_id, "maquina_virtual_id": c.maquina_virtual_id,
             "usuario_acceso": c.usuario_acceso, "password": descifrar(c.password_cifrada),
             "servicio": c.servicio, "puerto": c.puerto, "descripcion": c.descripcion,
             "creado_por_id": c.creado_por_id, "creado_en": _fecha(c.creado_en),
             "password_rotada_en": _fecha(c.password_rotada_en)}
            for c in db.scalars(select(Credencial)).all()
        ],
        "auditoria": [
            {"fecha": _fecha(r.fecha), "usuario_id": r.usuario_id, "username": r.username,
             "accion": r.accion, "objeto_tipo": r.objeto_tipo, "objeto_id": r.objeto_id,
             "detalle": r.detalle, "direccion_ip": r.direccion_ip,
             "agente_usuario": r.agente_usuario, "exito": r.exito}
            for r in db.scalars(select(RegistroAuditoria).order_by(RegistroAuditoria.id)).all()
        ],
    }

    salt = secrets.token_bytes(16)
    token = Fernet(_clave_desde_frase(frase, salt)).encrypt(
        json.dumps(carga, ensure_ascii=False).encode("utf-8")
    )
    contenedor = {
        "formato": FORMATO,
        "version": VERSION,
        "kdf": "scrypt-n16384-r8-p1",
        "salt": base64.b64encode(salt).decode("ascii"),
        "datos": token.decode("ascii"),
    }
    audit.registrar(db, audit.RESPALDO_CREADO, username="cli",
                    detalle=f"{len(carga['credenciales'])} credencial(es), "
                            f"{len(carga['servidores_fisicos'])} servidor(es).")
    return json.dumps(contenedor, indent=2).encode("utf-8")


def _abrir(datos: bytes, frase: str) -> dict:
    try:
        contenedor = json.loads(datos)
    except json.JSONDecodeError as exc:
        raise ErrorRespaldo("El archivo no tiene el formato de respaldo esperado.") from exc
    if contenedor.get("formato") != FORMATO or contenedor.get("version") != VERSION:
        raise ErrorRespaldo("El archivo no es un respaldo válido de este sistema.")
    salt = base64.b64decode(contenedor["salt"])
    try:
        carga = Fernet(_clave_desde_frase(frase, salt)).decrypt(contenedor["datos"].encode("ascii"))
    except InvalidToken as exc:
        raise ErrorRespaldo("Frase de respaldo incorrecta o archivo dañado.") from exc
    return json.loads(carga)


def restaurar(db: Session, datos: bytes, frase: str, sobrescribir: bool = False) -> dict[str, int]:
    """Restaura un respaldo; exige `sobrescribir=True` si hay datos previos."""
    carga = _abrir(datos, frase)

    hay_datos = (db.scalar(select(func.count(Usuario.id))) or 0) > 0 or (
        db.scalar(select(func.count(ServidorFisico.id))) or 0
    ) > 0
    if hay_datos and not sobrescribir:
        raise ErrorRespaldo("La base de datos ya contiene información; use --sobrescribir para reemplazarla.")

    # Limpieza total en orden inverso de dependencias
    for modelo in (SesionWeb, CodigoRecuperacionMFA, RegistroAuditoria, Credencial,
                   MaquinaVirtual, Hipervisor, ServidorFisico, Usuario):
        for fila in db.scalars(select(modelo)).all():
            db.delete(fila)
    db.flush()

    for u in carga["usuarios"]:
        db.add(Usuario(
            id=u["id"], username=u["username"], email=u["email"],
            nombre_completo=u["nombre_completo"], password_hash=u["password_hash"],
            rol=u["rol"], mfa_habilitado=u["mfa_habilitado"],
            totp_secret_cifrado=cifrar(u["totp_secret"]) if u["totp_secret"] else None,
            ultimo_otp_usado=u["ultimo_otp_usado"], activo=u["activo"],
            debe_cambiar_password=u["debe_cambiar_password"],
            password_cambiada_en=_parse_fecha(u["password_cambiada_en"]) or ahora_utc(),
            ultimo_acceso=_parse_fecha(u["ultimo_acceso"]),
            creado_en=_parse_fecha(u["creado_en"]) or ahora_utc(),
        ))
    db.flush()
    for c in carga.get("codigos_recuperacion", []):
        db.add(CodigoRecuperacionMFA(
            usuario_id=c["usuario_id"], codigo_hash=c["codigo_hash"],
            creado_en=_parse_fecha(c["creado_en"]) or ahora_utc(),
            usado_en=_parse_fecha(c["usado_en"]),
        ))
    for s in carga["servidores_fisicos"]:
        db.add(ServidorFisico(
            id=s["id"], nombre=s["nombre"], descripcion=s["descripcion"],
            sistema_operativo=s["sistema_operativo"], marca_modelo=s["marca_modelo"],
            ubicacion=s["ubicacion"], ip_gestion=s["ip_gestion"],
            ram=s.get("ram", ""), cpu=s.get("cpu", ""), almacenamiento=s.get("almacenamiento", ""),
            numero_serie=s.get("numero_serie", ""), garantia_hasta=s.get("garantia_hasta", ""),
            proveedor=s.get("proveedor", ""), estado=s.get("estado", ESTADO_ACTIVO),
            etiquetas=s.get("etiquetas", ""),
            creado_en=_parse_fecha(s["creado_en"]) or ahora_utc(),
        ))
    db.flush()
    for h in carga["hipervisores"]:
        db.add(Hipervisor(
            id=h["id"], nombre=h["nombre"],
            plataforma=h["plataforma"], version=h["version"], ip_gestion=h["ip_gestion"],
            descripcion=h["descripcion"], marca_modelo=h.get("marca_modelo", ""),
            ubicacion=h.get("ubicacion", ""), ram=h.get("ram", ""), cpu=h.get("cpu", ""),
            almacenamiento=h.get("almacenamiento", ""), numero_serie=h.get("numero_serie", ""),
            garantia_hasta=h.get("garantia_hasta", ""), proveedor=h.get("proveedor", ""),
            estado=h.get("estado", ESTADO_ACTIVO), etiquetas=h.get("etiquetas", ""),
            creado_en=_parse_fecha(h["creado_en"]) or ahora_utc(),
        ))
    db.flush()
    for v in carga["maquinas_virtuales"]:
        db.add(MaquinaVirtual(
            id=v["id"], hipervisor_id=v["hipervisor_id"], nombre=v["nombre"],
            sistema_operativo=v["sistema_operativo"], ip=v["ip"], descripcion=v["descripcion"],
            creado_en=_parse_fecha(v["creado_en"]) or ahora_utc(),
        ))
    db.flush()
    for c in carga["credenciales"]:
        db.add(Credencial(
            id=c["id"], servidor_fisico_id=c["servidor_fisico_id"],
            hipervisor_id=c["hipervisor_id"], maquina_virtual_id=c["maquina_virtual_id"],
            usuario_acceso=c["usuario_acceso"], password_cifrada=cifrar(c["password"]),
            servicio=c["servicio"], puerto=c["puerto"], descripcion=c["descripcion"],
            creado_por_id=c["creado_por_id"],
            creado_en=_parse_fecha(c["creado_en"]) or ahora_utc(),
            password_rotada_en=_parse_fecha(c.get("password_rotada_en")) or ahora_utc(),
        ))
    for r in carga.get("auditoria", []):
        db.add(RegistroAuditoria(
            fecha=_parse_fecha(r["fecha"]) or ahora_utc(), usuario_id=r["usuario_id"],
            username=r["username"], accion=r["accion"], objeto_tipo=r["objeto_tipo"],
            objeto_id=r["objeto_id"], detalle=r["detalle"], direccion_ip=r["direccion_ip"],
            agente_usuario=r["agente_usuario"], exito=r["exito"],
        ))
    db.flush()

    resumen = {
        "usuarios": len(carga["usuarios"]),
        "servidores_fisicos": len(carga["servidores_fisicos"]),
        "hipervisores": len(carga["hipervisores"]),
        "maquinas_virtuales": len(carga["maquinas_virtuales"]),
        "credenciales": len(carga["credenciales"]),
        "auditoria": len(carga.get("auditoria", [])),
    }
    audit.registrar(db, audit.RESPALDO_RESTAURADO, username="cli",
                    detalle=json.dumps(resumen, ensure_ascii=False))
    return resumen
