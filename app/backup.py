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
    TIPO_DISPOSITIVO_SWITCH,
    CodigoRecuperacionMFA,
    Credencial,
    DispositivoRed,
    EntradaVault,
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
VERSION = 2
LARGO_MINIMO_FRASE = 16

# Parámetros del KDF (scrypt). Los vigentes se escriben en el archivo (v2) y
# se leen de vuelta al restaurar, con topes de cordura para que un archivo
# manipulado no fuerce un consumo de memoria arbitrario. Los respaldos v1 se
# crearon con n=2**14 fijo y siguen siendo restaurables.
_SCRYPT_N = 2**17
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_N_V1 = 2**14
_SCRYPT_N_MAX = 2**22
_SCRYPT_R_MAX = 32
_SCRYPT_P_MAX = 16


class ErrorRespaldo(Exception):
    pass


def _clave_desde_frase(frase: str, salt: bytes,
                       n: int = _SCRYPT_N, r: int = _SCRYPT_R, p: int = _SCRYPT_P) -> bytes:
    kdf = Scrypt(salt=salt, length=32, n=n, r=r, p=p)
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
             "estado": s.estado, "etiquetas": s.etiquetas, "restringido": s.restringido,
             "creado_en": _fecha(s.creado_en)}
            for s in db.scalars(select(ServidorFisico)).all()
        ],
        "hipervisores": [
            {"id": h.id, "nombre": h.nombre, "plataforma": h.plataforma, "version": h.version,
             "ip_gestion": h.ip_gestion, "descripcion": h.descripcion, "marca_modelo": h.marca_modelo,
             "ubicacion": h.ubicacion, "ram": h.ram, "cpu": h.cpu, "almacenamiento": h.almacenamiento,
             "numero_serie": h.numero_serie, "garantia_hasta": h.garantia_hasta, "proveedor": h.proveedor,
             "estado": h.estado, "etiquetas": h.etiquetas, "restringido": h.restringido,
             "creado_en": _fecha(h.creado_en)}
            for h in db.scalars(select(Hipervisor)).all()
        ],
        "maquinas_virtuales": [
            {"id": v.id, "hipervisor_id": v.hipervisor_id, "nombre": v.nombre,
             "sistema_operativo": v.sistema_operativo, "ip": v.ip,
             "descripcion": v.descripcion, "ram": v.ram, "cpu": v.cpu,
             "almacenamiento": v.almacenamiento, "estado": v.estado, "etiquetas": v.etiquetas,
             "creado_en": _fecha(v.creado_en)}
            for v in db.scalars(select(MaquinaVirtual)).all()
        ],
        "dispositivos_red": [
            {"id": d.id, "nombre": d.nombre, "tipo_dispositivo": d.tipo_dispositivo,
             "marca_modelo": d.marca_modelo, "version": d.version, "ip_gestion": d.ip_gestion,
             "ubicacion": d.ubicacion, "puertos": d.puertos, "descripcion": d.descripcion,
             "numero_serie": d.numero_serie, "garantia_hasta": d.garantia_hasta,
             "proveedor": d.proveedor, "estado": d.estado, "etiquetas": d.etiquetas,
             "restringido": d.restringido, "creado_en": _fecha(d.creado_en)}
            for d in db.scalars(select(DispositivoRed)).all()
        ],
        "credenciales": [
            {"id": c.id, "servidor_fisico_id": c.servidor_fisico_id,
             "hipervisor_id": c.hipervisor_id, "maquina_virtual_id": c.maquina_virtual_id,
             "dispositivo_red_id": c.dispositivo_red_id,
             "usuario_acceso": c.usuario_acceso, "password": descifrar(c.password_cifrada),
             "servicio": c.servicio, "puerto": c.puerto, "descripcion": c.descripcion,
             "creado_por_id": c.creado_por_id, "creado_en": _fecha(c.creado_en),
             "password_rotada_en": _fecha(c.password_rotada_en)}
            for c in db.scalars(select(Credencial)).all()
        ],
        # Vaults personales: privados por usuario, pero SÍ se respaldan (dato del
        # sistema). La contraseña se guarda en claro dentro del JSON cifrado, como
        # el resto de secretos del respaldo; nunca sale al export en claro.
        "vaults": [
            {"id": e.id, "usuario_id": e.usuario_id, "titulo": e.titulo,
             "usuario_acceso": e.usuario_acceso, "password": descifrar(e.password_cifrada),
             "url": e.url, "categoria": e.categoria, "notas": e.notas,
             "creado_en": _fecha(e.creado_en), "password_rotada_en": _fecha(e.password_rotada_en)}
            for e in db.scalars(select(EntradaVault)).all()
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
        "kdf": {"algoritmo": "scrypt", "n": _SCRYPT_N, "r": _SCRYPT_R, "p": _SCRYPT_P},
        "salt": base64.b64encode(salt).decode("ascii"),
        "datos": token.decode("ascii"),
    }
    audit.registrar(db, audit.RESPALDO_CREADO, username="cli",
                    detalle=f"{len(carga['credenciales'])} credencial(es), "
                            f"{len(carga['servidores_fisicos'])} servidor(es).")
    return json.dumps(contenedor, indent=2).encode("utf-8")


def _parametros_kdf(contenedor: dict) -> tuple[int, int, int]:
    """Parámetros scrypt del contenedor, validados contra topes de cordura."""
    if contenedor.get("version") == 1:
        return _SCRYPT_N_V1, _SCRYPT_R, _SCRYPT_P  # v1: parámetros fijos históricos
    kdf = contenedor.get("kdf") or {}
    if not isinstance(kdf, dict) or kdf.get("algoritmo") != "scrypt":
        raise ErrorRespaldo("El archivo no declara un cifrado de respaldo compatible.")
    try:
        n, r, p = int(kdf["n"]), int(kdf["r"]), int(kdf["p"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ErrorRespaldo("Parámetros de cifrado del respaldo ilegibles.") from exc
    # Cordura anti-DoS: n potencia de dos acotada; r y p en rangos razonables.
    if not (2**10 <= n <= _SCRYPT_N_MAX and n & (n - 1) == 0
            and 1 <= r <= _SCRYPT_R_MAX and 1 <= p <= _SCRYPT_P_MAX):
        raise ErrorRespaldo("Parámetros de cifrado del respaldo fuera de rango.")
    return n, r, p


def _abrir(datos: bytes, frase: str) -> dict:
    try:
        contenedor = json.loads(datos)
    except json.JSONDecodeError as exc:
        raise ErrorRespaldo("El archivo no tiene el formato de respaldo esperado.") from exc
    if contenedor.get("formato") != FORMATO or contenedor.get("version") not in (1, VERSION):
        raise ErrorRespaldo("El archivo no es un respaldo válido de este sistema.")
    n, r, p = _parametros_kdf(contenedor)
    salt = base64.b64decode(contenedor["salt"])
    try:
        carga = Fernet(_clave_desde_frase(frase, salt, n=n, r=r, p=p)).decrypt(
            contenedor["datos"].encode("ascii")
        )
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
    for modelo in (SesionWeb, CodigoRecuperacionMFA, RegistroAuditoria, EntradaVault, Credencial,
                   MaquinaVirtual, Hipervisor, DispositivoRed, ServidorFisico, Usuario):
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
            etiquetas=s.get("etiquetas", ""), restringido=s.get("restringido", False),
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
            restringido=h.get("restringido", False),
            creado_en=_parse_fecha(h["creado_en"]) or ahora_utc(),
        ))
    db.flush()
    for v in carga["maquinas_virtuales"]:
        db.add(MaquinaVirtual(
            id=v["id"], hipervisor_id=v["hipervisor_id"], nombre=v["nombre"],
            sistema_operativo=v["sistema_operativo"], ip=v["ip"], descripcion=v["descripcion"],
            ram=v.get("ram", ""), cpu=v.get("cpu", ""), almacenamiento=v.get("almacenamiento", ""),
            estado=v.get("estado", ESTADO_ACTIVO), etiquetas=v.get("etiquetas", ""),
            creado_en=_parse_fecha(v["creado_en"]) or ahora_utc(),
        ))
    db.flush()
    # Respaldos anteriores a los dispositivos de red no traen esta clave.
    for d in carga.get("dispositivos_red", []):
        db.add(DispositivoRed(
            id=d["id"], nombre=d["nombre"],
            tipo_dispositivo=d.get("tipo_dispositivo", TIPO_DISPOSITIVO_SWITCH),
            marca_modelo=d.get("marca_modelo", ""), version=d.get("version", ""),
            ip_gestion=d.get("ip_gestion", ""), ubicacion=d.get("ubicacion", ""),
            puertos=d.get("puertos", ""), descripcion=d.get("descripcion", ""),
            numero_serie=d.get("numero_serie", ""), garantia_hasta=d.get("garantia_hasta", ""),
            proveedor=d.get("proveedor", ""), estado=d.get("estado", ESTADO_ACTIVO),
            etiquetas=d.get("etiquetas", ""), restringido=d.get("restringido", False),
            creado_en=_parse_fecha(d.get("creado_en")) or ahora_utc(),
        ))
    db.flush()
    for c in carga["credenciales"]:
        db.add(Credencial(
            id=c["id"], servidor_fisico_id=c["servidor_fisico_id"],
            hipervisor_id=c["hipervisor_id"], maquina_virtual_id=c["maquina_virtual_id"],
            dispositivo_red_id=c.get("dispositivo_red_id"),
            usuario_acceso=c["usuario_acceso"], password_cifrada=cifrar(c["password"]),
            servicio=c["servicio"], puerto=c["puerto"], descripcion=c["descripcion"],
            creado_por_id=c["creado_por_id"],
            creado_en=_parse_fecha(c["creado_en"]) or ahora_utc(),
            password_rotada_en=_parse_fecha(c.get("password_rotada_en")) or ahora_utc(),
        ))
    for e in carga.get("vaults", []):
        db.add(EntradaVault(
            id=e["id"], usuario_id=e["usuario_id"], titulo=e["titulo"],
            usuario_acceso=e.get("usuario_acceso", ""), password_cifrada=cifrar(e["password"]),
            url=e.get("url", ""), categoria=e.get("categoria", "cuenta"), notas=e.get("notas", ""),
            creado_en=_parse_fecha(e.get("creado_en")) or ahora_utc(),
            password_rotada_en=_parse_fecha(e.get("password_rotada_en")) or ahora_utc(),
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
        "dispositivos_red": len(carga.get("dispositivos_red", [])),
        "credenciales": len(carga["credenciales"]),
        "vaults": len(carga.get("vaults", [])),
        "auditoria": len(carga.get("auditoria", [])),
    }
    audit.registrar(db, audit.RESPALDO_RESTAURADO, username="cli",
                    detalle=json.dumps(resumen, ensure_ascii=False))
    return resumen
