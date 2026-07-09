"""Pruebas de las mejoras de la Ola 2 del análisis (`docs/analisis-mejoras.md`).

SEC-1: modo estricto de claves (PASSWD_REQUIRE_ENV_KEYS) — sin claves por
       entorno la aplicación no arranca ni autogenera archivos de clave.
SEC-2: rotación de la clave de cifrado (MultiFernet + CLI `recifrar`).
SEC-7: lista amplia de contraseñas comunes prohibidas.
SEC-8: respaldo v2 (scrypt reforzado con parámetros en el archivo, frase
       mínima de 16) con compatibilidad para restaurar respaldos v1.
"""

from __future__ import annotations

import base64
import json
import secrets

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from tests.conftest import autenticar_admin, sesion_bd
from tests.test_credenciales import CLAVE_SECRETA, _crear_credencial
from tests.test_inventario import _crear_servidor

# ---------------------------------------------------------------------------
# SEC-1 — modo estricto de claves por entorno
# ---------------------------------------------------------------------------


def test_modo_estricto_exige_claves_por_entorno(tmp_path, monkeypatch):
    from app.config import Settings, reset_settings

    monkeypatch.setenv("PASSWD_DATA_DIR", str(tmp_path / "datos"))
    monkeypatch.setenv("PASSWD_REQUIRE_ENV_KEYS", "true")
    monkeypatch.delenv("PASSWD_SECRET_KEY", raising=False)
    monkeypatch.delenv("PASSWD_ENCRYPTION_KEY", raising=False)
    reset_settings()

    with pytest.raises(RuntimeError, match="REQUIRE_ENV_KEYS"):
        Settings()
    # No debe haber autogenerado ningún archivo de clave junto a los datos.
    assert not (tmp_path / "datos" / ".secret_key").exists()
    assert not (tmp_path / "datos" / ".encryption_key").exists()

    # Con ambas claves por entorno, arranca con normalidad.
    monkeypatch.setenv("PASSWD_SECRET_KEY", secrets.token_urlsafe(48))
    monkeypatch.setenv("PASSWD_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    settings = Settings()
    assert settings.encryption_key
    reset_settings()


# ---------------------------------------------------------------------------
# SEC-2 — rotación de la clave de cifrado (MultiFernet + `recifrar`)
# ---------------------------------------------------------------------------


def _password_credencial_descifrada() -> str:
    from app.models import Credencial
    from app.security.crypto import descifrar

    db = sesion_bd()
    try:
        credencial = db.scalar(select(Credencial))
        return descifrar(credencial.password_cifrada)
    finally:
        db.close()


def test_rotacion_de_clave_con_multifernet_y_recifrado(client, monkeypatch):
    from app.cli import main as cli_main
    from app.config import get_settings, reset_settings

    autenticar_admin(client)
    sid = _crear_servidor(client, "srv-rotacion")
    _crear_credencial(client, "fisico", sid)

    clave_antigua = get_settings().encryption_key
    clave_nueva = Fernet.generate_key().decode("ascii")

    # 1) Doble clave: la nueva cifra, la antigua sigue descifrando lo viejo.
    monkeypatch.setenv("PASSWD_ENCRYPTION_KEY", f"{clave_nueva},{clave_antigua}")
    reset_settings()
    assert _password_credencial_descifrada() == CLAVE_SECRETA

    # 2) Recifrado masivo por CLI.
    assert cli_main(["recifrar"]) == 0

    # 3) Solo la clave nueva: todo el material quedó recifrado con ella.
    monkeypatch.setenv("PASSWD_ENCRYPTION_KEY", clave_nueva)
    reset_settings()
    assert _password_credencial_descifrada() == CLAVE_SECRETA

    # La semilla TOTP del admin también quedó recifrada y es legible.
    from app.models import Usuario
    from app.security.crypto import descifrar

    db = sesion_bd()
    try:
        admin = db.scalar(select(Usuario))
        assert admin.totp_secret_cifrado is not None
        assert descifrar(admin.totp_secret_cifrado)
    finally:
        db.close()

    # 4) Con SOLO la clave antigua, el material recifrado ya no es legible:
    #    la rotación fue efectiva, no un simple alias.
    monkeypatch.setenv("PASSWD_ENCRYPTION_KEY", clave_antigua)
    reset_settings()
    with pytest.raises(ValueError):
        _password_credencial_descifrada()

    # Restaurar el estado esperado por el teardown del fixture.
    monkeypatch.setenv("PASSWD_ENCRYPTION_KEY", clave_nueva)
    reset_settings()


# ---------------------------------------------------------------------------
# SEC-7 — lista amplia de contraseñas comunes
# ---------------------------------------------------------------------------


def test_blocklist_amplia_rechaza_contrasenas_comunes(aplicacion):
    from app.security.passwords import _contrasenas_comunes, validar_politica

    assert len(_contrasenas_comunes()) > 9000  # la lista empaquetada cargó

    # Entrada real de la lista (≥12 caracteres, pasa el resto de reglas).
    errores = validar_politica("unbelievable")
    assert any("uso común" in e for e in errores)

    # La semilla corta original sigue vetada y una frase robusta pasa.
    assert any("uso común" in e for e in validar_politica("password1234"))
    assert validar_politica("Frase-Robusta-Unica-2026!") == []


# ---------------------------------------------------------------------------
# SEC-8 — respaldo v2 y compatibilidad v1
# ---------------------------------------------------------------------------

FRASE = "FraseDeRespaldo-Segura-2026!"


def test_respaldo_v2_declara_kdf_y_es_restaurable(client):
    from app import backup

    autenticar_admin(client)
    sid = _crear_servidor(client, "srv-respaldo-v2")
    _crear_credencial(client, "fisico", sid)

    db = sesion_bd()
    try:
        datos = backup.exportar(db, FRASE)
        contenedor = json.loads(datos)
        assert contenedor["version"] == 2
        assert contenedor["kdf"] == {"algoritmo": "scrypt", "n": 2**17, "r": 8, "p": 1}
        resumen = backup.restaurar(db, datos, FRASE, sobrescribir=True)
        db.commit()
        assert resumen["credenciales"] == 1
    finally:
        db.close()
    assert _password_credencial_descifrada() == CLAVE_SECRETA


def test_respaldo_v1_sigue_siendo_restaurable(client):
    """Un contenedor v1 (scrypt n=2**14 fijo, sin parámetros) se restaura."""
    from app import backup

    autenticar_admin(client)

    salt = secrets.token_bytes(16)
    clave = backup._clave_desde_frase(FRASE, salt, n=2**14, r=8, p=1)
    carga = {
        "version": 1, "creado_en": "2026-01-01T00:00:00",
        "usuarios": [], "codigos_recuperacion": [], "servidores_fisicos": [],
        "hipervisores": [], "maquinas_virtuales": [], "credenciales": [], "auditoria": [],
    }
    contenedor_v1 = {
        "formato": "respaldo-passwd",
        "version": 1,
        "kdf": "scrypt-n16384-r8-p1",   # cadena descriptiva del formato antiguo
        "salt": base64.b64encode(salt).decode("ascii"),
        "datos": Fernet(clave).encrypt(json.dumps(carga).encode("utf-8")).decode("ascii"),
    }

    db = sesion_bd()
    try:
        resumen = backup.restaurar(db, json.dumps(contenedor_v1).encode("utf-8"),
                                   FRASE, sobrescribir=True)
        assert resumen["usuarios"] == 0
    finally:
        db.close()


def test_respaldo_frase_corta_y_kdf_fuera_de_rango_rechazados(client):
    from app import backup

    autenticar_admin(client)
    db = sesion_bd()
    try:
        # Frase de 12-15 caracteres: válida en v1, ya no para crear respaldos.
        with pytest.raises(backup.ErrorRespaldo, match="al menos 16"):
            backup.exportar(db, "corta-12chars!")

        # Parámetros scrypt manipulados por encima del tope: rechazo temprano.
        datos = backup.exportar(db, FRASE)
        contenedor = json.loads(datos)
        contenedor["kdf"]["n"] = 2**23
        with pytest.raises(backup.ErrorRespaldo, match="fuera de rango"):
            backup.restaurar(db, json.dumps(contenedor).encode("utf-8"),
                             FRASE, sobrescribir=True)
    finally:
        db.close()
