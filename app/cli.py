"""Herramientas de línea de comandos.

Uso:
    python -m app.cli init-db
    python -m app.cli crear-admin --username admin --email admin@ejemplo.com
    python -m app.cli respaldo --salida respaldo.passwd
    python -m app.cli restaurar --entrada respaldo.passwd [--sobrescribir]
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

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


def _pedir_frase(confirmar: bool) -> str:
    frase = getpass.getpass("Frase de cifrado del respaldo (mínimo 12 caracteres): ")
    if confirmar and getpass.getpass("Confirme la frase: ") != frase:
        raise SystemExit("Las frases no coinciden.")
    return frase


def _frase_respaldo(args: argparse.Namespace, confirmar: bool) -> str:
    """Prioridad: --passphrase, variable PASSWD_BACKUP_PASSPHRASE, interactivo."""
    if args.passphrase:
        return args.passphrase
    desde_entorno = os.environ.get("PASSWD_BACKUP_PASSPHRASE", "")
    if desde_entorno:
        return desde_entorno
    return _pedir_frase(confirmar)


def _cmd_respaldo(args: argparse.Namespace) -> int:
    from app import backup

    init_db()
    db = next(get_db())
    try:
        frase = _frase_respaldo(args, confirmar=True)
        datos = backup.exportar(db, frase)
        db.commit()
        ruta = Path(args.salida)
        ruta.touch(mode=0o600, exist_ok=True)
        ruta.write_bytes(datos)
        print(f"Respaldo cifrado escrito en {ruta} ({len(datos)} bytes).")
        print("Guarde la frase en un lugar seguro: sin ella el respaldo es irrecuperable.")
        return 0
    except backup.ErrorRespaldo as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


def _cmd_restaurar(args: argparse.Namespace) -> int:
    from app import backup

    init_db()
    db = next(get_db())
    try:
        datos = Path(args.entrada).read_bytes()
        frase = _frase_respaldo(args, confirmar=False)
        resumen = backup.restaurar(db, datos, frase, sobrescribir=args.sobrescribir)
        db.commit()
        print("Restauración completada:")
        for clave, cantidad in resumen.items():
            print(f"  - {clave}: {cantidad}")
        return 0
    except FileNotFoundError:
        print(f"Error: no existe el archivo {args.entrada}", file=sys.stderr)
        return 1
    except backup.ErrorRespaldo as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
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

    p_respaldo = sub.add_parser("respaldo", help="Exporta un respaldo cifrado de todo el sistema.")
    p_respaldo.add_argument("--salida", required=True, help="Ruta del archivo de respaldo a crear.")
    p_respaldo.add_argument("--passphrase", default="",
                            help="Si se omite, se usa PASSWD_BACKUP_PASSPHRASE o se solicita interactivamente.")

    p_restaurar = sub.add_parser("restaurar", help="Restaura un respaldo cifrado.")
    p_restaurar.add_argument("--entrada", required=True, help="Ruta del archivo de respaldo.")
    p_restaurar.add_argument("--passphrase", default="",
                             help="Si se omite, se usa PASSWD_BACKUP_PASSPHRASE o se solicita interactivamente.")
    p_restaurar.add_argument("--sobrescribir", action="store_true",
                             help="Reemplaza los datos existentes (obligatorio si la BD no está vacía).")

    args = parser.parse_args(argv)
    if args.comando == "init-db":
        return _cmd_init_db(args)
    if args.comando == "crear-admin":
        return _cmd_crear_admin(args)
    if args.comando == "respaldo":
        return _cmd_respaldo(args)
    if args.comando == "restaurar":
        return _cmd_restaurar(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
