"""Vault PERSONAL de cada usuario (interfaz web Jinja).

Paridad con ``app/api_web/vault.py``: cada entrada pertenece a un usuario y solo
él la ve, edita y revela. Sirve para contraseñas de servicios, aplicaciones o
cuentas propias, fuera del inventario de servidores. La contraseña se cifra en
reposo y solo se entrega, auditada y limitada, por ``/revelar`` y ``/copiar``.
Permiso ``vault.usar`` (todos los roles); el aislamiento por dueño se aplica en
cada consulta (una entrada ajena responde 404).
"""

from __future__ import annotations

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.config import get_settings
from app.database import get_db
from app.deps import render, requiere_permiso, verificar_csrf
from app.models import (
    CATEGORIA_VAULT_CUENTA,
    CATEGORIAS_VAULT,
    ETIQUETAS_CATEGORIA_VAULT,
    EntradaVault,
    Usuario,
    ahora_utc,
)
from app.security import ratelimit
from app.security.crypto import cifrar, descifrar

router = APIRouter()

VAULT = Depends(requiere_permiso("vault.usar"))


def _categoria_valida(valor: str) -> str:
    return valor if valor in CATEGORIAS_VAULT else CATEGORIA_VAULT_CUENTA


def _mia(db: Session, usuario: Usuario, entrada_id: int) -> EntradaVault:
    entrada = db.get(EntradaVault, entrada_id)
    if entrada is None or entrada.usuario_id != usuario.id:
        raise HTTPException(status_code=404, detail="La entrada no existe.")
    return entrada


def _redir(mensaje: str) -> RedirectResponse:
    return RedirectResponse(f"/vault?msg={quote(mensaje)}", status_code=303)


@router.get("/vault")
def vault_lista(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, VAULT],
    msg: str = "",
):
    entradas = db.scalars(
        select(EntradaVault)
        .where(EntradaVault.usuario_id == usuario.id)
        .order_by(EntradaVault.titulo)
    ).all()
    return render(request, "vault.html", {
        "usuario_actual": usuario, "entradas": entradas, "msg": msg,
        "etiquetas_categoria": ETIQUETAS_CATEGORIA_VAULT,
        "rotacion_max_dias": get_settings().rotation_max_days,
    })


@router.get("/vault/nueva")
def vault_nueva_form(request: Request, usuario: Annotated[Usuario, VAULT]):
    return render(request, "vault_form.html", {
        "usuario_actual": usuario, "entrada": None,
        "categorias": CATEGORIAS_VAULT, "etiquetas_categoria": ETIQUETAS_CATEGORIA_VAULT,
    })


@router.post("/vault/nueva", dependencies=[Depends(verificar_csrf)])
def vault_crear(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, VAULT],
    titulo: Annotated[str, Form()] = "",
    usuario_acceso: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
    url: Annotated[str, Form()] = "",
    categoria: Annotated[str, Form()] = CATEGORIA_VAULT_CUENTA,
    notas: Annotated[str, Form()] = "",
):
    titulo = titulo.strip()
    if not titulo or not password:
        return render(request, "vault_form.html", {
            "usuario_actual": usuario, "entrada": None,
            "categorias": CATEGORIAS_VAULT, "etiquetas_categoria": ETIQUETAS_CATEGORIA_VAULT,
            "error": "El título y la contraseña son obligatorios.",
        }, status_code=400)
    entrada = EntradaVault(
        usuario_id=usuario.id, titulo=titulo, usuario_acceso=usuario_acceso.strip(),
        password_cifrada=cifrar(password), url=url.strip(),
        categoria=_categoria_valida(categoria), notas=notas,
    )
    db.add(entrada)
    db.flush()
    audit.registrar(db, audit.VAULT_CREADA, request=request, usuario=usuario,
                    objeto_tipo="entrada_vault", objeto_id=entrada.id, detalle=titulo)
    return _redir("Entrada añadida a tu vault.")


@router.get("/vault/{entrada_id}/editar")
def vault_editar_form(
    request: Request,
    entrada_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, VAULT],
):
    entrada = _mia(db, usuario, entrada_id)
    return render(request, "vault_form.html", {
        "usuario_actual": usuario, "entrada": entrada,
        "categorias": CATEGORIAS_VAULT, "etiquetas_categoria": ETIQUETAS_CATEGORIA_VAULT,
    })


@router.post("/vault/{entrada_id}/editar", dependencies=[Depends(verificar_csrf)])
def vault_editar(
    request: Request,
    entrada_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, VAULT],
    titulo: Annotated[str, Form()] = "",
    usuario_acceso: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
    url: Annotated[str, Form()] = "",
    categoria: Annotated[str, Form()] = CATEGORIA_VAULT_CUENTA,
    notas: Annotated[str, Form()] = "",
):
    entrada = _mia(db, usuario, entrada_id)
    titulo = titulo.strip()
    if not titulo:
        return render(request, "vault_form.html", {
            "usuario_actual": usuario, "entrada": entrada,
            "categorias": CATEGORIAS_VAULT, "etiquetas_categoria": ETIQUETAS_CATEGORIA_VAULT,
            "error": "El título es obligatorio.",
        }, status_code=400)
    entrada.titulo = titulo
    entrada.usuario_acceso = usuario_acceso.strip()
    entrada.url = url.strip()
    entrada.categoria = _categoria_valida(categoria)
    entrada.notas = notas
    if password:  # vacío = conservar la actual
        entrada.password_cifrada = cifrar(password)
        entrada.password_rotada_en = ahora_utc()
    audit.registrar(db, audit.VAULT_ACTUALIZADA, request=request, usuario=usuario,
                    objeto_tipo="entrada_vault", objeto_id=entrada.id, detalle=titulo)
    return _redir("Entrada actualizada.")


@router.post("/vault/{entrada_id}/eliminar", dependencies=[Depends(verificar_csrf)])
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
    return _redir("Entrada eliminada.")


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


@router.post("/vault/{entrada_id}/revelar", dependencies=[Depends(verificar_csrf)])
def vault_revelar(
    request: Request,
    entrada_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, VAULT],
):
    return _entregar(request, db, usuario, entrada_id, audit.VAULT_REVELADA)


@router.post("/vault/{entrada_id}/copiar", dependencies=[Depends(verificar_csrf)])
def vault_copiar(
    request: Request,
    entrada_id: int,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, VAULT],
):
    return _entregar(request, db, usuario, entrada_id, audit.VAULT_COPIADA)
