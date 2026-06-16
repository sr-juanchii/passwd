"""Pruebas de gestión de usuarios, RBAC administrativo y bitácora de auditoría."""

from __future__ import annotations

from sqlalchemy import select

from tests.conftest import (
    PASS_USUARIO,
    autenticar_admin,
    autenticar_usuario_nuevo,
    crear_usuario,
    csrf_de,
    login_password,
    sesion_bd,
    verificar_mfa,
)


def test_alta_de_usuario_con_clave_temporal_y_primer_acceso(client, crear_cliente):
    autenticar_admin(client)
    clave_temporal = crear_usuario(client, "operario", "operador")
    assert len(clave_temporal) >= 12

    cliente_operador = crear_cliente()
    secreto = autenticar_usuario_nuevo(cliente_operador, "operario", clave_temporal)
    assert secreto
    assert cliente_operador.get("/").status_code == 200

    # La clave temporal ya no sirve (fue cambiada en el primer acceso)
    cliente_reintento = crear_cliente()
    respuesta = login_password(cliente_reintento, "operario", clave_temporal)
    assert respuesta.status_code == 401


def test_operador_no_gestiona_usuarios_ni_ve_auditoria(client, crear_cliente):
    autenticar_admin(client)
    clave_temporal = crear_usuario(client, "operario2", "operador")
    cliente_operador = crear_cliente()
    autenticar_usuario_nuevo(cliente_operador, "operario2", clave_temporal)

    assert cliente_operador.get("/usuarios").status_code == 403
    assert cliente_operador.get("/auditoria").status_code == 403


def test_desactivar_usuario_revoca_sus_sesiones(client, crear_cliente):
    autenticar_admin(client)
    clave_temporal = crear_usuario(client, "saliente", "operador")
    cliente_objetivo = crear_cliente()
    autenticar_usuario_nuevo(cliente_objetivo, "saliente", clave_temporal)
    assert cliente_objetivo.get("/").status_code == 200

    db = sesion_bd()
    try:
        from app.models import Usuario

        objetivo_id = db.scalar(select(Usuario.id).where(Usuario.username == "saliente"))
    finally:
        db.close()

    csrf = csrf_de(client, "/usuarios")
    respuesta = client.post(f"/usuarios/{objetivo_id}/desactivar", data={"csrf_token": csrf})
    assert respuesta.status_code == 303

    # Sesión revocada al instante y login bloqueado
    assert cliente_objetivo.get("/").status_code == 303
    respuesta = login_password(crear_cliente(), "saliente", PASS_USUARIO)
    assert respuesta.status_code == 401


def test_admin_no_puede_desactivarse_a_si_mismo(client):
    autenticar_admin(client)
    db = sesion_bd()
    try:
        from app.models import Usuario

        admin_id = db.scalar(select(Usuario.id).where(Usuario.username == "admin"))
    finally:
        db.close()

    csrf = csrf_de(client, "/usuarios")
    respuesta = client.post(f"/usuarios/{admin_id}/desactivar", data={"csrf_token": csrf})
    assert respuesta.status_code == 400


def test_reinicio_de_mfa_fuerza_nuevo_enrolamiento(client, crear_cliente):
    autenticar_admin(client)
    clave_temporal = crear_usuario(client, "reinicio", "operador")
    cliente_objetivo = crear_cliente()
    autenticar_usuario_nuevo(cliente_objetivo, "reinicio", clave_temporal)

    db = sesion_bd()
    try:
        from app.models import Usuario

        objetivo_id = db.scalar(select(Usuario.id).where(Usuario.username == "reinicio"))
    finally:
        db.close()

    csrf = csrf_de(client, "/usuarios")
    assert client.post(f"/usuarios/{objetivo_id}/reset-mfa", data={"csrf_token": csrf}).status_code == 303

    cliente_nuevo = crear_cliente()
    respuesta = login_password(cliente_nuevo, "reinicio", PASS_USUARIO)
    assert respuesta.status_code == 303
    assert respuesta.headers["location"] == "/mfa/configurar"  # debe enrolar de nuevo


def test_auditoria_visible_para_admin_y_auditor_con_filtros(client, crear_cliente):
    autenticar_admin(client)
    clave_temporal = crear_usuario(client, "vigilante", "auditor")
    cliente_auditor = crear_cliente()
    autenticar_usuario_nuevo(cliente_auditor, "vigilante", clave_temporal)

    pagina = client.get("/auditoria")
    assert pagina.status_code == 200
    assert "login_correcto" in pagina.text
    assert "usuario_creado" in pagina.text

    pagina = client.get("/auditoria?filtro_accion=usuario_creado")
    assert pagina.status_code == 200
    assert "vigilante" in pagina.text

    assert cliente_auditor.get("/auditoria").status_code == 200


def test_retencion_de_auditoria(client):
    autenticar_admin(client)
    db = sesion_bd()
    try:
        import datetime

        from app import audit
        from app.models import RegistroAuditoria

        antiguo = RegistroAuditoria(
            username="historico", accion="login_correcto",
            fecha=datetime.datetime.utcnow() - datetime.timedelta(days=400),
        )
        db.add(antiguo)
        db.commit()

        eliminados = audit.purgar_antiguos(db, dias_retencion=365)
        db.commit()
        assert eliminados == 1
        assert db.scalar(select(RegistroAuditoria).where(
            RegistroAuditoria.username == "historico")) is None
    finally:
        db.close()


def test_cambio_de_rol_revoca_sesiones(client, crear_cliente):
    autenticar_admin(client)
    clave_temporal = crear_usuario(client, "promovible", "auditor")
    cliente_objetivo = crear_cliente()
    secreto = autenticar_usuario_nuevo(cliente_objetivo, "promovible", clave_temporal)

    db = sesion_bd()
    try:
        from app.models import Usuario

        objetivo_id = db.scalar(select(Usuario.id).where(Usuario.username == "promovible"))
    finally:
        db.close()

    csrf = csrf_de(client, "/usuarios")
    respuesta = client.post(f"/usuarios/{objetivo_id}/rol", data={"rol": "operador", "csrf_token": csrf})
    assert respuesta.status_code == 303

    # La sesión anterior quedó revocada; tras autenticarse de nuevo, ya es operador
    assert cliente_objetivo.get("/").status_code == 303
    login_password(cliente_objetivo, "promovible", PASS_USUARIO)
    assert verificar_mfa(cliente_objetivo, secreto, desplazamiento=30).status_code == 303
    panel = cliente_objetivo.get("/")
    assert panel.status_code == 200
    assert "+ Servidor dedicado" in panel.text  # permiso de gestión visible
