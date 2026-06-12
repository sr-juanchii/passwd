"""Pruebas de las adiciones aprobadas: generador de contraseñas, alertas de
rotación, respaldo cifrado y códigos de recuperación MFA."""

from __future__ import annotations

import datetime

import pytest
from sqlalchemy import func, select

from tests.conftest import (
    ADMIN_PASS,
    ADMIN_PASS_INICIAL,
    ADMIN_USER,
    autenticar_admin,
    cambiar_password,
    csrf_de,
    enrolar_mfa_con_codigos,
    extraer_csrf,
    login_password,
    sesion_bd,
)
from tests.test_credenciales import CLAVE_SECRETA, _crear_credencial
from tests.test_inventario import _crear_hipervisor, _crear_servidor, _crear_vm

# ---------------------------------------------------------------------------
# 1. Generador de contraseñas
# ---------------------------------------------------------------------------


def test_generador_disponible_en_formulario(client):
    autenticar_admin(client)
    fisico = _crear_servidor(client, "srv-generador", "funcion_unica")
    pagina = client.get(f"/credenciales/nueva?activo=fisico&activo_id={fisico}")
    assert pagina.status_code == 200
    assert 'data-generar="password"' in pagina.text

    js = client.get("/static/app.js")
    assert js.status_code == 200
    assert "getRandomValues" in js.text  # CSPRNG del navegador, sin Math.random
    assert "data-generar" in js.text


# ---------------------------------------------------------------------------
# 2. Alertas de rotación
# ---------------------------------------------------------------------------


def test_alerta_de_rotacion_vencida(client):
    autenticar_admin(client)
    fisico = _crear_servidor(client, "srv-rotacion", "funcion_unica")
    _crear_credencial(client, "fisico", fisico)

    # Una credencial recién creada no alerta
    detalle = client.get(f"/servidores/{fisico}")
    assert "sin rotar" not in detalle.text
    panel = client.get("/")
    assert "rotación vencida" not in panel.text.lower()

    # Se retrocede la fecha de rotación más allá del umbral (90 días)
    db = sesion_bd()
    try:
        from app.models import Credencial

        credencial = db.scalar(select(Credencial))
        credencial.password_rotada_en = datetime.datetime.now(datetime.UTC).replace(
            tzinfo=None
        ) - datetime.timedelta(days=120)
        db.commit()
    finally:
        db.close()

    detalle = client.get(f"/servidores/{fisico}")
    assert "120 días sin rotar" in detalle.text
    panel = client.get("/")
    assert "Con rotación vencida" in panel.text


def test_rotar_credencial_reinicia_el_contador(client):
    autenticar_admin(client)
    fisico = _crear_servidor(client, "srv-rotada", "funcion_unica")
    _crear_credencial(client, "fisico", fisico)

    db = sesion_bd()
    try:
        from app.models import Credencial

        credencial = db.scalar(select(Credencial))
        credencial_id = credencial.id
        credencial.password_rotada_en = datetime.datetime.now(datetime.UTC).replace(
            tzinfo=None
        ) - datetime.timedelta(days=120)
        db.commit()
    finally:
        db.close()

    csrf = csrf_de(client, f"/credenciales/{credencial_id}/editar")
    respuesta = client.post(f"/credenciales/{credencial_id}/editar", data={
        "usuario_acceso": "root", "password": "NuevaClaveRotada#2026", "servicio": "SSH",
        "puerto": "22", "descripcion": "", "csrf_token": csrf,
    })
    assert respuesta.status_code == 303

    detalle = client.get(f"/servidores/{fisico}")
    assert "sin rotar" not in detalle.text  # contador reiniciado


# ---------------------------------------------------------------------------
# 3. Respaldo cifrado y restauración
# ---------------------------------------------------------------------------

FRASE_RESPALDO = "FraseDeRespaldo-Segura-2026!"


def test_respaldo_y_restauracion_completa(client):
    autenticar_admin(client)
    host = _crear_servidor(client, "srv-respaldo", "host_virtualizacion")
    hipervisor = _crear_hipervisor(client, host, "pve-respaldo")
    vm = _crear_vm(client, hipervisor, "vm-respaldo")
    _crear_credencial(client, "vm", vm, "ubuntu")

    from app import backup

    db = sesion_bd()
    try:
        datos = backup.exportar(db, FRASE_RESPALDO)
        db.commit()
    finally:
        db.close()

    # El archivo no contiene secretos a la vista
    assert CLAVE_SECRETA.encode() not in datos
    assert b"srv-respaldo" not in datos

    # Se vacía todo y se restaura
    db = sesion_bd()
    try:
        from app.models import Credencial, ServidorFisico, Usuario

        resumen = backup.restaurar(db, datos, FRASE_RESPALDO, sobrescribir=True)
        db.commit()
        assert resumen["servidores_fisicos"] == 1
        assert resumen["credenciales"] == 1
        assert resumen["usuarios"] == 1

        from app.security.crypto import descifrar

        credencial = db.scalar(select(Credencial))
        assert descifrar(credencial.password_cifrada) == CLAVE_SECRETA
        assert db.scalar(select(func.count(ServidorFisico.id))) == 1
        admin = db.scalar(select(Usuario).where(Usuario.username == ADMIN_USER))
        assert admin is not None and admin.mfa_habilitado
    finally:
        db.close()

    # Las relaciones sobreviven a la restauración y el admin puede volver a entrar
    respuesta = login_password(client, ADMIN_USER, ADMIN_PASS)
    assert respuesta.status_code == 303 and respuesta.headers["location"] == "/mfa/verificar"


def test_respaldo_con_frase_incorrecta_rechazado(client):
    autenticar_admin(client)
    from app import backup

    db = sesion_bd()
    try:
        datos = backup.exportar(db, FRASE_RESPALDO)
        db.commit()
        with pytest.raises(backup.ErrorRespaldo, match="incorrecta"):
            backup.restaurar(db, datos, "frase-equivocada-123", sobrescribir=True)
        with pytest.raises(backup.ErrorRespaldo, match="12 caracteres"):
            backup.exportar(db, "corta")
        with pytest.raises(backup.ErrorRespaldo, match="sobrescribir"):
            backup.restaurar(db, datos, FRASE_RESPALDO, sobrescribir=False)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 4. Códigos de recuperación MFA
# ---------------------------------------------------------------------------


def _login_hasta_mfa(client):
    respuesta = login_password(client, ADMIN_USER, ADMIN_PASS)
    assert respuesta.status_code == 303 and respuesta.headers["location"] == "/mfa/verificar"
    pagina = client.get("/mfa/verificar")
    return extraer_csrf(pagina.text)


def test_codigos_de_recuperacion_un_solo_uso(client):
    # El enrolamiento emite 8 códigos y solo persiste sus hashes
    respuesta = login_password(client, ADMIN_USER, ADMIN_PASS_INICIAL)
    assert respuesta.status_code == 303
    cambiar_password(client, ADMIN_PASS_INICIAL, ADMIN_PASS)
    _secreto, codigos = enrolar_mfa_con_codigos(client)
    assert len(codigos) == 8

    db = sesion_bd()
    try:
        from app.models import CodigoRecuperacionMFA

        registros = db.scalars(select(CodigoRecuperacionMFA)).all()
        assert len(registros) == 8
        for codigo in codigos:
            for registro in registros:
                assert codigo not in registro.codigo_hash  # solo hashes en BD
    finally:
        db.close()

    csrf = csrf_de(client, "/")
    client.post("/logout", data={"csrf_token": csrf})

    # Un código de recuperación sustituye al TOTP
    csrf = _login_hasta_mfa(client)
    respuesta = client.post("/mfa/verificar", data={"codigo": codigos[0], "csrf_token": csrf})
    assert respuesta.status_code == 303
    assert client.get("/").status_code == 200

    csrf = csrf_de(client, "/")
    client.post("/logout", data={"csrf_token": csrf})

    # El mismo código no puede reutilizarse
    csrf = _login_hasta_mfa(client)
    respuesta = client.post("/mfa/verificar", data={"codigo": codigos[0], "csrf_token": csrf})
    assert respuesta.status_code == 401

    # Pero el siguiente código sigue siendo válido
    respuesta = client.post("/mfa/verificar", data={
        "codigo": codigos[1], "csrf_token": _login_hasta_mfa(client),
    })
    assert respuesta.status_code == 303

    # El uso quedó auditado con el conteo restante
    db = sesion_bd()
    try:
        from app.models import RegistroAuditoria

        eventos = db.scalars(select(RegistroAuditoria).where(
            RegistroAuditoria.accion == "mfa_codigo_recuperacion_usado")).all()
        assert len(eventos) == 2
    finally:
        db.close()


def test_reset_mfa_invalida_codigos_de_recuperacion(client, crear_cliente):
    from tests.conftest import autenticar_usuario_nuevo, crear_usuario

    autenticar_admin(client)
    clave_temporal = crear_usuario(client, "conrecuperacion", "operador")
    cliente_objetivo = crear_cliente()
    autenticar_usuario_nuevo(cliente_objetivo, "conrecuperacion", clave_temporal)

    db = sesion_bd()
    try:
        from app.models import CodigoRecuperacionMFA, Usuario

        objetivo_id = db.scalar(select(Usuario.id).where(Usuario.username == "conrecuperacion"))
        assert (db.scalar(select(func.count(CodigoRecuperacionMFA.id)).where(
            CodigoRecuperacionMFA.usuario_id == objetivo_id)) or 0) == 8
    finally:
        db.close()

    csrf = csrf_de(client, "/usuarios")
    assert client.post(f"/usuarios/{objetivo_id}/reset-mfa", data={"csrf_token": csrf}).status_code == 303

    db = sesion_bd()
    try:
        from app.models import CodigoRecuperacionMFA

        assert (db.scalar(select(func.count(CodigoRecuperacionMFA.id)).where(
            CodigoRecuperacionMFA.usuario_id == objetivo_id)) or 0) == 0
    finally:
        db.close()
