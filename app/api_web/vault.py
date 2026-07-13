"""Vault PERSONAL de cada usuario en JSON (`/api/web/vault`).

A diferencia de las credenciales del inventario (RBAC + acceso por objeto), cada
entrada pertenece a UN usuario y solo él la ve, edita y revela: el
administrador no accede a su contenido. Sirve para contraseñas de servicios,
aplicaciones o cuentas propias. La contraseña se cifra en reposo (Fernet) y solo
se entrega, auditada y limitada, en ``/revelar`` y ``/copiar``. El permiso
``vault.usar`` lo tienen todos los roles; el aislamiento por dueño se aplica en
cada consulta (una entrada ajena responde 404, sin filtrar su existencia).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.api_web.deps import requiere_permiso_json, verificar_csrf_json
from app.config import get_settings
from app.database import get_db
from app.models import (
    CATEGORIA_VAULT_CUENTA,
    CATEGORIAS_VAULT,
    EntradaVault,
    Usuario,
    ahora_utc,
)
from app.security import ratelimit
from app.security.crypto import cifrar, descifrar

router = APIRouter()

VAULT = Depends(requiere_permiso_json("vault.usar"))
CSRF = Depends(verificar_csrf_json)


class VaultCrear(BaseModel):
    titulo: str = ""
    usuario_acceso: str = ""
    password: str = ""
    url: str = ""
    categoria: str = CATEGORIA_VAULT_CUENTA
    notas: str = ""


class VaultEditar(BaseModel):
    titulo: str = ""
    usuario_acceso: str = ""
    password: str = ""  # "" = conservar la actual
    url: str = ""
    categoria: str = CATEGORIA_VAULT_CUENTA
    notas: str = ""


def _categoria_valida(valor: str) -> str:
    return valor if valor in CATEGORIAS_VAULT else CATEGORIA_VAULT_CUENTA


def _mia(db: Session, usuario: Usuario, entrada_id: int) -> EntradaVault:
    """Entrada del vault del usuario actual, o 404 (no filtra existencia ajena)."""
    entrada = db.get(EntradaVault, entrada_id)
    if entrada is None or entrada.usuario_id != usuario.id:
        raise HTTPException(status_code=404, detail="La entrada no existe.")
    return entrada


def _serializar(entrada: EntradaVault) -> dict:
    settings = get_settings()
    return {
        "id": entrada.id,
        "titulo": entrada.titulo,
        "usuario_acceso": entrada.usuario_acceso,
        "url": entrada.url,
        "categoria": entrada.categoria,
        "notas": entrada.notas,
        "dias_sin_rotar": entrada.dias_sin_rotar,
        "rotacion_vencida": entrada.dias_sin_rotar > settings.rotation_max_days,
    }


@router.get("/vault")
def vault_listar(
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, VAULT],
):
    entradas = db.scalars(
        select(EntradaVault)
        .where(EntradaVault.usuario_id == usuario.id)
        .order_by(EntradaVault.titulo)
    ).all()
    return {"entradas": [_serializar(e) for e in entradas]}


@router.get("/vault/{entrada_id}")
def vault_detalle(
    entrada_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, VAULT],
):
    return _serializar(_mia(db, usuario, entrada_id))


@router.post("/vault", dependencies=[CSRF])
def vault_crear(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, VAULT],
    cuerpo: VaultCrear,
):
    if not cuerpo.titulo.strip():
        raise HTTPException(status_code=400, detail="El título es obligatorio.")
    if not cuerpo.password:
        raise HTTPException(status_code=400, detail="La contraseña es obligatoria.")
    entrada = EntradaVault(
        usuario_id=usuario.id,
        titulo=cuerpo.titulo.strip(),
        usuario_acceso=cuerpo.usuario_acceso.strip(),
        password_cifrada=cifrar(cuerpo.password),
        url=cuerpo.url.strip(),
        categoria=_categoria_valida(cuerpo.categoria),
        notas=cuerpo.notas,
    )
    db.add(entrada)
    db.flush()
    audit.registrar(db, audit.VAULT_CREADA, request=request, usuario=usuario,
                    objeto_tipo="entrada_vault", objeto_id=entrada.id, detalle=entrada.titulo)
    return {"id": entrada.id}


@router.put("/vault/{entrada_id}", dependencies=[CSRF])
def vault_editar(
    request: Request,
    entrada_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, VAULT],
    cuerpo: VaultEditar,
):
    entrada = _mia(db, usuario, entrada_id)
    if not cuerpo.titulo.strip():
        raise HTTPException(status_code=400, detail="El título es obligatorio.")
    entrada.titulo = cuerpo.titulo.strip()
    entrada.usuario_acceso = cuerpo.usuario_acceso.strip()
    entrada.url = cuerpo.url.strip()
    entrada.categoria = _categoria_valida(cuerpo.categoria)
    entrada.notas = cuerpo.notas
    if cuerpo.password:  # vacío = conservar la actual
        entrada.password_cifrada = cifrar(cuerpo.password)
        entrada.password_rotada_en = ahora_utc()
    audit.registrar(db, audit.VAULT_ACTUALIZADA, request=request, usuario=usuario,
                    objeto_tipo="entrada_vault", objeto_id=entrada.id, detalle=entrada.titulo)
    return {"id": entrada.id}


@router.delete("/vault/{entrada_id}", dependencies=[CSRF])
def vault_eliminar(
    request: Request,
    entrada_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, VAULT],
):
    entrada = _mia(db, usuario, entrada_id)
    titulo = entrada.titulo
    db.delete(entrada)
    audit.registrar(db, audit.VAULT_ELIMINADA, request=request, usuario=usuario,
                    objeto_tipo="entrada_vault", objeto_id=entrada_id, detalle=titulo)
    return {"ok": True}


def _entregar(request: Request, db: Session, usuario: Usuario, entrada_id: int, accion: str):
    entrada = _mia(db, usuario, entrada_id)
    settings = get_settings()
    if not ratelimit.permitir_intento(
        f"vault-revelar:{usuario.id}", limite=settings.reveal_rate_limit,
        ventana_minutos=settings.reveal_rate_window_minutes, db=db,
    ):
        audit.registrar(db, audit.REVELADO_TASA_EXCEDIDA, request=request, usuario=usuario,
                        objeto_tipo="entrada_vault", objeto_id=entrada_id, detalle="Vault.", exito=False)
        db.commit()
        raise HTTPException(status_code=429, detail="Límite de accesos alcanzado; espere unos minutos.")
    audit.registrar(db, accion, request=request, usuario=usuario,
                    objeto_tipo="entrada_vault", objeto_id=entrada.id, detalle=entrada.titulo)
    return JSONResponse(
        {"usuario": entrada.usuario_acceso, "password": descifrar(entrada.password_cifrada)},
        headers={"Cache-Control": "no-store"},
    )


@router.post("/vault/{entrada_id}/revelar", dependencies=[CSRF])
def vault_revelar(
    request: Request,
    entrada_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, VAULT],
):
    return _entregar(request, db, usuario, entrada_id, audit.VAULT_REVELADA)


@router.post("/vault/{entrada_id}/copiar", dependencies=[CSRF])
def vault_copiar(
    request: Request,
    entrada_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, VAULT],
):
    return _entregar(request, db, usuario, entrada_id, audit.VAULT_COPIADA)
