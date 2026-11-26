"""Prueba de sistema del agente: instalado de verdad con systemd, rotando una cuenta real.

La ejecuta la CI en un runner de GitHub, que arranca con systemd: instala el
agente y el helper con ``agente/instalacion/instalar.sh``, con sus unidades
endurecidas, y comprueba que una rotación autorizada por dos administradores
acaba cambiando la contraseña de una cuenta Linux real. Es lo único que prueba
que el endurecimiento de las unidades (sin red para el helper, sin privilegios
para el agente, filtro de llamadas al sistema…) deja hacer el trabajo.

Dos fases, que comparten la base de datos con el backend (``PASSWD_DATA_DIR``):

    python scripts/prueba_agente_sistema.py preparar --cuenta pa-e2e --password ... --token-archivo T
    sudo agente/instalacion/instalar.sh ... --token - < T
    python scripts/prueba_agente_sistema.py rotar --cuenta pa-e2e

Sale con 0 si la rotación se cierra «aplicada» y la cuenta real autentica con la
contraseña que quedó en el inventario; con 1 en cualquier otro caso.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

HELPER = "/usr/local/sbin/passwd-agente-helper"
ESPERA_MAXIMA_S = 240
MOTIVO = "Prueba de sistema: rotación por agente instalado con systemd en la CI."


def _bd():
    from app.database import get_db
    from app.main import create_app

    create_app()
    return next(get_db())


def preparar(args) -> int:
    from app.models import ACTIVO_FISICO, ROL_ADMIN, ServidorFisico, Usuario, ahora_utc
    from app.servicios import agentes, rotacion

    db = _bd()
    # Cuentas que nunca inician sesión: actúan por el servicio. «x» no es un
    # hash Argon2 válido, así que ninguna contraseña las abre.
    sin_acceso = "x"
    pide = Usuario(username="pide-sistema", email="pide@sistema.local",
                   password_hash=sin_acceso, rol=ROL_ADMIN)
    autoriza = Usuario(username="autoriza-sistema", email="autoriza@sistema.local",
                       password_hash=sin_acceso, rol=ROL_ADMIN)
    servidor = ServidorFisico(nombre="runner-ci")
    db.add_all([pide, autoriza, servidor])
    db.flush()
    credencial = rotacion.nueva_credencial(db, password=args.password, usuario_acceso=args.cuenta,
                                           servidor_fisico_id=servidor.id)
    db.flush()
    # Rotada hace un mes: ni temprana ni frenada por el anti-thrash del backend.
    credencial.password_rotada_en = ahora_utc() - timedelta(days=30)
    _agente, token = agentes.alta(db, tipo_activo=ACTIVO_FISICO, activo_id=servidor.id,
                                  nombre="agente-runner-ci", usuario=pide)
    db.commit()
    ruta = Path(args.token_archivo)
    ruta.write_text(token + "\n", encoding="utf-8")
    ruta.chmod(0o600)
    print(f"preparado: credencial {credencial.id}, token de instalación en {ruta}")
    return 0


def _verificar_con_helper(cuenta: str, password: str) -> bool:
    """Pregunta al helper instalado, como root, si la contraseña vale en la cuenta real."""
    peticion = json.dumps({"accion": "verificar", "cuenta": cuenta, "password": password}) + "\n"
    # Órdenes fijas, sin entrada externa en la línea de órdenes: la contraseña
    # va por la entrada estándar.
    salida = subprocess.run(  # noqa: S603
        ["/usr/bin/sudo", HELPER, "--config", "/etc/passwd-agente/helper.json"],
        input=peticion, capture_output=True, text=True, check=False)
    try:
        return bool(json.loads(salida.stdout or "{}").get("ok"))
    except json.JSONDecodeError:
        return False


def rotar(args) -> int:
    from app.models import ROT_CERRADA, Agente, Credencial, RotacionCredencial, Usuario
    from app.security.crypto import descifrar
    from app.servicios import agentes, rotacion

    db = _bd()
    agente = db.query(Agente).one()
    print(f"agente: estado {agente.estado}, cobertura {agentes.cobertura(agente)}, "
          f"versión {agente.version_agente}")
    if agentes.cobertura(agente) != agentes.COBERTURA_CONECTADO:
        print("FALLO: el agente instalado no está conectado")
        return 1

    credencial = db.query(Credencial).filter(Credencial.usuario_acceso == args.cuenta).one()
    pide = db.query(Usuario).filter(Usuario.username == "pide-sistema").one()
    autoriza = db.query(Usuario).filter(Usuario.username == "autoriza-sistema").one()
    anterior = descifrar(credencial.password_cifrada)
    agentes.usar_agente(db, credencial=credencial, usuario=pide)
    solicitud = rotacion.solicitar(db, credencial=credencial, usuario=pide, motivo=MOTIVO)
    rotacion.autorizar(db, rotacion=solicitud, usuario=autoriza)
    db.commit()
    print(f"rotación {solicitud.id}: {solicitud.estado}")
    if solicitud.estado != "despachada":
        print("FALLO: la rotación autorizada no se despachó al agente")
        return 1

    limite = time.monotonic() + ESPERA_MAXIMA_S
    while time.monotonic() < limite:
        db.expire_all()
        asiento = db.get(RotacionCredencial, solicitud.id)
        if asiento.estado == ROT_CERRADA:
            break
        time.sleep(5)
    else:
        print(f"FALLO: la rotación no se cerró en {ESPERA_MAXIMA_S} s")
        return 1

    print(f"rotación cerrada: resultado {asiento.resultado}, verificación {asiento.verificacion}, "
          f"detalle «{asiento.detalle_error}»")
    if asiento.resultado != "aplicada" or asiento.verificacion != "local":
        print("FALLO: se esperaba «aplicada» con verificación local")
        return 1

    db.expire_all()
    nueva = descifrar(db.get(Credencial, credencial.id).password_cifrada)
    if nueva == anterior:
        print("FALLO: la credencial del inventario no cambió")
        return 1
    if not _verificar_con_helper(args.cuenta, nueva):
        print("FALLO: la cuenta real no autentica con la contraseña del inventario")
        return 1
    if _verificar_con_helper(args.cuenta, anterior):
        print("FALLO: la contraseña anterior sigue valiendo en la cuenta real")
        return 1
    print("OK: la cuenta real autentica con la contraseña nueva del inventario y ya no con la anterior")
    return 0


def main() -> int:
    if not os.environ.get("PASSWD_DATA_DIR"):
        print("defina PASSWD_DATA_DIR (la misma base de datos que el backend)")
        return 2
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="fase", required=True)
    p = sub.add_parser("preparar")
    p.add_argument("--cuenta", required=True)
    p.add_argument("--password", required=True)
    p.add_argument("--token-archivo", required=True)
    r = sub.add_parser("rotar")
    r.add_argument("--cuenta", required=True)
    args = parser.parse_args()
    return preparar(args) if args.fase == "preparar" else rotar(args)


if __name__ == "__main__":
    sys.exit(main())
