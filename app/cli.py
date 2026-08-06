"""Herramientas de línea de comandos.

Uso:
    python -m app.cli init-db
    python -m app.cli crear-admin --username admin --email admin@ejemplo.com
    python -m app.cli respaldo --salida respaldo.passwd
    python -m app.cli restaurar --entrada respaldo.passwd [--sobrescribir]
    python -m app.cli recifrar    # rotación de la clave de cifrado (ver docs)
    python -m app.cli exportar-csv --salida inventario.csv  # export EN CLARO (migración)
    python -m app.cli verificar-auditoria    # integridad de la cadena de auditoría
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
    from app.backup import LARGO_MINIMO_FRASE

    frase = getpass.getpass(f"Frase de cifrado del respaldo (mínimo {LARGO_MINIMO_FRASE} caracteres): ")
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


def _podar_respaldos(ruta: Path, retener: int) -> int:
    """Conserva los `retener` respaldos *.passwd más recientes del directorio."""
    if retener <= 0:
        return 0
    archivos = sorted(ruta.parent.glob("*.passwd"), key=lambda p: p.stat().st_mtime, reverse=True)
    eliminados = 0
    for sobrante in archivos[retener:]:
        sobrante.unlink()
        eliminados += 1
    return eliminados


def _cmd_respaldo(args: argparse.Namespace) -> int:
    from app import backup
    from app.notifications import enviar_alerta

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
        if args.retener:
            eliminados = _podar_respaldos(ruta, args.retener)
            if eliminados:
                print(f"Retención: {eliminados} respaldo(s) antiguo(s) eliminado(s).")
        print("Guarde la frase en un lugar seguro: sin ella el respaldo es irrecuperable.")
        return 0
    except backup.ErrorRespaldo as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 — avisar de un fallo de respaldo
        enviar_alerta("Fallo de respaldo", f"El respaldo automático falló: {exc}")
        print(f"Error inesperado: {exc}", file=sys.stderr)
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


def _cmd_recifrar(_args: argparse.Namespace) -> int:
    """Recifra todo el material con la clave primaria (rotación de clave).

    Procedimiento: fijar ``PASSWD_ENCRYPTION_KEY=nueva,antigua`` (la primera
    cifra, todas descifran), ejecutar este comando y, al terminar, dejar solo
    la clave nueva. Ver ``docs/referencia-cli.md``.
    """
    from app.models import (
        Credencial,
        DispositivoRed,
        EntradaVault,
        Hipervisor,
        HistorialCredencial,
        MaquinaVirtual,
        ServidorFisico,
        Usuario,
    )
    from app.security import crypto

    init_db()
    db = next(get_db())
    try:
        objetivos = [
            (Usuario, "totp_secret_cifrado"),
            (Credencial, "password_cifrada"),
            (HistorialCredencial, "password_cifrada"),
            (ServidorFisico, "notas_cifradas"),
            (Hipervisor, "notas_cifradas"),
            (MaquinaVirtual, "notas_cifradas"),
            (DispositivoRed, "notas_cifradas"),
            (EntradaVault, "password_cifrada"),
        ]
        total = 0
        print("Recifrando con la clave primaria:")
        for modelo, columna in objetivos:
            procesadas = 0
            for fila in db.scalars(select(modelo)).all():
                blob = getattr(fila, columna)
                if blob is None:
                    continue
                setattr(fila, columna, crypto.recifrar(blob))
                procesadas += 1
            print(f"  - {modelo.__tablename__}.{columna}: {procesadas}")
            total += procesadas
        db.commit()
        print(f"Recifrado completado: {total} valores usan ahora la clave primaria.")
        print("Ya puede retirar las claves antiguas de PASSWD_ENCRYPTION_KEY.")
        return 0
    except ValueError as exc:
        db.rollback()
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


def _cmd_export_csv(args: argparse.Namespace) -> int:
    """Exporta el inventario EN CLARO a CSV (migración; contiene contraseñas).

    Mismo formato que acepta el importador, para editarlo y volver a importarlo.
    No incluye los vaults personales (privados). El archivo se escribe con
    permisos 0600; destrúyalo tras la migración.
    """
    from app import audit
    from app.exporter import exportar_csv

    init_db()
    db = next(get_db())
    try:
        texto = exportar_csv(db)
        ruta = Path(args.salida)
        ruta.touch(mode=0o600, exist_ok=True)
        ruta.write_text(texto, encoding="utf-8")
        audit.registrar(db, audit.INVENTARIO_EXPORTADO, username="cli",
                        detalle=f"Export en claro a {ruta} ({len(texto)} bytes).")
        db.commit()
        print(f"Inventario exportado en claro a {ruta} ({len(texto)} bytes).")
        print("Contiene contraseñas en claro: custódielo y destrúyalo tras la migración.")
        return 0
    finally:
        db.close()


def _cmd_verificar_auditoria(_args: argparse.Namespace) -> int:
    """Verifica el encadenamiento por hash de la bitácora (tamper-evidence)."""
    from app import audit

    init_db()
    db = next(get_db())
    try:
        resultado = audit.verificar_cadena(db)
        if resultado["ok"]:
            print(f"Cadena de auditoría íntegra: {resultado['verificados']} registro(s) verificado(s).")
            return 0
        print(f"CADENA ROTA en el registro {resultado['id_roto']}: {resultado['motivo']}.", file=sys.stderr)
        return 1
    finally:
        db.close()


def _cmd_avisar_rotacion(args: argparse.Namespace) -> int:
    """Avisa a los usuarios con acceso de las rotaciones obligatorias próximas.

    Pensado para una tarea programada diaria (cron / systemd timer). Es idempotente
    dentro de la semana: ``avisos.aviso_rotacion_proxima`` deduplica por credencial
    y umbral con una ventana de 7 días, así que ejecutarlo a diario no repite el
    mismo aviso cada día.

    Con ``--simular`` no envía nada: solo informa de cuántas credenciales entrarían
    en la ventana de preaviso, para poder revisar el alcance antes de activarlo.
    """
    from sqlalchemy import select

    from app import avisos
    from app.access import usuarios_con_acceso_a_credencial
    from app.config import get_settings
    from app.models import Credencial

    init_db()
    db = next(get_db())
    try:
        settings = get_settings()
        if args.simular:
            credenciales = db.scalars(select(Credencial)).all()
            en_ventana = [
                c for c in credenciales
                if avisos.dias_para_rotacion(c) <= settings.rotation_warning_days
            ]
            print(
                f"Simulación: {len(en_ventana)} de {len(credenciales)} credencial(es) "
                f"entran en la ventana de preaviso "
                f"(política {settings.rotation_max_days} días, preaviso "
                f"{settings.rotation_warning_days} días)."
            )
            for c in en_ventana:
                restantes = avisos.dias_para_rotacion(c)
                estado = f"vencida hace {abs(restantes)} d" if restantes < 0 else f"vence en {restantes} d"
                destinatarios = len(
                    usuarios_con_acceso_a_credencial(db, c, solo_con_revelado=True)
                )
                print(f"  - {c.usuario_acceso}@{c.nombre_activo} ({c.servicio}): "
                      f"{estado}; {destinatarios} destinatario(s)")
            return 0

        if not avisos.avisos_activos():
            print(
                "Los avisos dinámicos están desactivados: se necesita "
                "PASSWD_NOTIFY_ENABLED=true, PASSWD_NOTIFY_USERS_ENABLED=true y SMTP "
                "configurado. No se envió nada.",
                file=sys.stderr,
            )
            return 1
        resumen = avisos.revisar_rotaciones(db)
        db.commit()
        print(
            f"Revisadas {resumen['credenciales_revisadas']} credencial(es); "
            f"{resumen['avisos_enviados']} aviso(s) enviado(s) sobre "
            f"{resumen['credenciales_avisadas']} credencial(es)."
        )
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

    p_respaldo = sub.add_parser("respaldo", help="Exporta un respaldo cifrado de todo el sistema.")
    p_respaldo.add_argument("--salida", required=True, help="Ruta del archivo de respaldo a crear.")
    p_respaldo.add_argument("--passphrase", default="",
                            help="Si se omite, se usa PASSWD_BACKUP_PASSPHRASE o se solicita interactivamente.")
    p_respaldo.add_argument("--retener", type=int, default=0,
                            help="Conserva solo los N respaldos *.passwd más recientes del directorio.")

    p_restaurar = sub.add_parser("restaurar", help="Restaura un respaldo cifrado.")
    p_restaurar.add_argument("--entrada", required=True, help="Ruta del archivo de respaldo.")
    p_restaurar.add_argument("--passphrase", default="",
                             help="Si se omite, se usa PASSWD_BACKUP_PASSPHRASE o se solicita interactivamente.")
    p_restaurar.add_argument("--sobrescribir", action="store_true",
                             help="Reemplaza los datos existentes (obligatorio si la BD no está vacía).")

    sub.add_parser("recifrar",
                   help="Recifra todos los secretos con la clave primaria de PASSWD_ENCRYPTION_KEY "
                        "(rotación de clave: fijar 'nueva,antigua', recifrar y dejar solo 'nueva').")

    p_export = sub.add_parser("exportar-csv",
                              help="Exporta el inventario EN CLARO a CSV para migración "
                                   "(mismo formato que el importador; contiene contraseñas).")
    p_export.add_argument("--salida", required=True, help="Ruta del CSV a crear (se escribe con permisos 0600).")

    sub.add_parser("verificar-auditoria",
                   help="Verifica la integridad (encadenamiento por hash) de la bitácora de auditoría.")

    p_rotacion = sub.add_parser(
        "avisar-rotacion",
        help="Avisa por correo a los usuarios con acceso de las rotaciones obligatorias "
             "próximas o vencidas (pensado para una tarea programada diaria).",
    )
    p_rotacion.add_argument("--simular", action="store_true",
                            help="No envía correos: solo informa de qué credenciales entrarían "
                                 "en la ventana de preaviso y a cuántos destinatarios.")

    args = parser.parse_args(argv)
    if args.comando == "init-db":
        return _cmd_init_db(args)
    if args.comando == "crear-admin":
        return _cmd_crear_admin(args)
    if args.comando == "respaldo":
        return _cmd_respaldo(args)
    if args.comando == "restaurar":
        return _cmd_restaurar(args)
    if args.comando == "recifrar":
        return _cmd_recifrar(args)
    if args.comando == "exportar-csv":
        return _cmd_export_csv(args)
    if args.comando == "verificar-auditoria":
        return _cmd_verificar_auditoria(args)
    if args.comando == "avisar-rotacion":
        return _cmd_avisar_rotacion(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
