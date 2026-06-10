"""Herramientas de línea de comandos.

Uso:
    python -m app.cli init-db
    python -m app.cli crear-admin --username admin --email admin@ejemplo.com
"""

from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import func, select

from app.database import get_db, init_db
from app.models import ROL_ADMIN, Usuario
from app.security.passwords import hashear_password, validar_politica


def _cmd_init_db(_args: argparse.Namespace) -> int:
    init_db()
    print("Base de datos inicializada.")
    return 0


def _cmd_crear_admin(args: argparse.Namespace) -> int:
    init_db()
    db = next(get_db())
    try:
        username = args.username.strip().lower()
        if db.scalar(select(Usuario).where(func.lower(Usuario.username) == username)):
            print(f"Error: ya existe el usuario «{username}».", file=sys.stderr)
            return 1
        password = args.password or getpass.getpass("Contraseña temporal para el administrador: ")
        errores = validar_politica(password, username)
        if errores:
            print("Contraseña rechazada: " + " ".join(errores), file=sys.stderr)
            return 1
        admin = Usuario(
            username=username,
            email=args.email.strip().lower(),
            nombre_completo=args.nombre or "Administrador",
            password_hash=hashear_password(password),
            rol=ROL_ADMIN,
            debe_cambiar_password=True,
        )
        db.add(admin)
        db.commit()
        total = db.scalar(select(func.count(Usuario.id))) or 0
        print(f"Administrador «{username}» creado (usuarios totales: {total}).")
        print("Al primer inicio de sesión deberá cambiar la contraseña y enrolar MFA.")
        return 0
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli", description="Utilidades administrativas.")
    sub = parser.add_subparsers(dest="comando", required=True)

    sub.add_parser("init-db", help="Crea las tablas de la base de datos.")

    p_admin = sub.add_parser("crear-admin", help="Crea una cuenta de administrador.")
    p_admin.add_argument("--username", required=True)
    p_admin.add_argument("--email", required=True)
    p_admin.add_argument("--nombre", default="")
    p_admin.add_argument("--password", default="", help="Si se omite, se solicita de forma interactiva.")

    args = parser.parse_args(argv)
    if args.comando == "init-db":
        return _cmd_init_db(args)
    if args.comando == "crear-admin":
        return _cmd_crear_admin(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
