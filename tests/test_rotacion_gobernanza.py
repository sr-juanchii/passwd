"""Criterios de aceptación de la gobernanza de rotación (v1.3.0).

Cada prueba corresponde a una garantía del plan
(``docs/plan-rotacion-agentes.md`` §8.1). No comprueban que el código haga algo,
sino que el sistema **no deja hacer** lo que el ciclo prohíbe: rotar sin
autorización, aprobar lo propio, aprobar sin reautenticarse o cambiar una
contraseña por una puerta lateral.
"""

from __future__ import annotations

import datetime
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import func, select

from tests.conftest import (
    ADMIN_PASS,
    MOTIVO_PRUEBA,
    autenticar_admin,
    autorizar_rotacion,
    cabecera_csrf,
    codigo_totp,
    csrf_de,
    rotar_credencial,
    segundo_administrador,
    sesion_bd,
    solicitar_rotacion,
)
from tests.test_credenciales import CLAVE_SECRETA, _crear_credencial
from tests.test_inventario import _crear_servidor

RAIZ = Path(__file__).resolve().parents[1]
NUEVA = "Clave-Rotada-Por-Gobernanza-2026!"


def _credencial(client, nombre: str = "srv-gob") -> int:
    servidor = _crear_servidor(client, nombre)
    _crear_credencial(client, "fisico", servidor)
    db = sesion_bd()
    try:
        from app.models import Credencial

        return db.scalar(select(Credencial.id).order_by(Credencial.id.desc()))
    finally:
        db.close()


def _envejecer(credencial_id: int, dias: int) -> None:
    """Retrasa la última rotación para poder medir antigüedades reales."""
    db = sesion_bd()
    try:
        from app.models import Credencial, ahora_utc

        credencial = db.get(Credencial, credencial_id)
        credencial.password_rotada_en = ahora_utc() - datetime.timedelta(days=dias)
        db.commit()
    finally:
        db.close()


def _asiento(rotacion_id: int):
    db = sesion_bd()
    try:
        from app.models import RotacionCredencial

        fila = db.get(RotacionCredencial, rotacion_id)
        db.refresh(fila)
        return fila
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 1. Sin autorización no se rota — por ninguna puerta
# ---------------------------------------------------------------------------


def test_sin_autorizacion_no_se_puede_registrar_la_rotacion(client):
    """El ciclo es solicitar → autorizar → registrar. Saltarse el paso del medio falla."""
    autenticar_admin(client)
    cred = _credencial(client)
    _envejecer(cred, 100)

    r = solicitar_rotacion(client, cred)
    assert r.status_code == 200
    rotacion_id = r.json()["id"]

    r = client.post(f"/api/web/rotacion/solicitudes/{rotacion_id}/aplicar-manual",
                    json={"password": NUEVA}, headers=cabecera_csrf(client))
    assert r.status_code == 409
    assert "autorización" in r.json()["detail"].lower()


def test_el_formulario_json_no_cambia_la_contrasena_sin_autorizacion(client):
    """La API de credenciales es una puerta más: también exige el ciclo."""
    autenticar_admin(client)
    cred = _credencial(client, "srv-puerta-json")

    r = client.put(f"/api/web/credenciales/{cred}", json={
        "usuario_acceso": "root", "password": NUEVA, "servicio": "SSH",
        "puerto": 22, "descripcion": "", "usada_por": "",
    }, headers=cabecera_csrf(client))
    assert r.status_code == 409

    # Y el intento queda registrado, no se pierde en silencio.
    db = sesion_bd()
    try:
        from app import audit
        from app.models import RegistroAuditoria

        n = db.scalar(select(func.count(RegistroAuditoria.id)).where(
            RegistroAuditoria.accion == audit.ROTACION_ESCRITURA_DENEGADA))
    finally:
        db.close()
    assert n == 1


def test_el_formulario_clasico_tampoco_cambia_la_contrasena_sin_autorizacion(client):
    """La interfaz clásica sigue viva hasta la 2.0: la puerta está en los dos caminos."""
    autenticar_admin(client)
    cred = _credencial(client, "srv-puerta-jinja")

    csrf = csrf_de(client, f"/credenciales/{cred}/editar")
    r = client.post(f"/credenciales/{cred}/editar", data={
        "usuario_acceso": "root", "password": NUEVA, "servicio": "SSH",
        "puerto": "22", "descripcion": "", "usada_por": "", "csrf_token": csrf,
    })
    assert r.status_code == 409
    assert "rotación autorizada" in r.text

    # Nada quedó a medias: la contraseña sigue siendo la original.
    db = sesion_bd()
    try:
        from app.models import Credencial
        from app.security.crypto import descifrar

        assert descifrar(db.get(Credencial, cred).password_cifrada) == CLAVE_SECRETA
    finally:
        db.close()


def test_editar_otros_campos_sigue_funcionando_sin_rotacion(client):
    """La gobernanza cubre la contraseña, no el resto de la ficha."""
    autenticar_admin(client)
    cred = _credencial(client, "srv-campos")

    r = client.put(f"/api/web/credenciales/{cred}", json={
        "usuario_acceso": "root", "password": "", "servicio": "RDP",
        "puerto": 3389, "descripcion": "Consola", "usada_por": "cron de respaldos",
    }, headers=cabecera_csrf(client))
    assert r.status_code == 200

    db = sesion_bd()
    try:
        from app.models import Credencial

        credencial = db.get(Credencial, cred)
        assert credencial.servicio == "RDP"
        assert credencial.usada_por == "cron de respaldos"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 2. Regla de dos pares
# ---------------------------------------------------------------------------


def test_nadie_autoriza_su_propia_solicitud(client):
    """Ni siquiera reautenticándose correctamente: la regla es sobre quién, no sobre cómo."""
    secreto = autenticar_admin(client)
    cred = _credencial(client, "srv-dos-pares")
    _envejecer(cred, 100)

    rotacion_id = solicitar_rotacion(client, cred).json()["id"]

    r = client.post(f"/api/web/rotacion/solicitudes/{rotacion_id}/autorizar",
                    json={"password": ADMIN_PASS, "codigo": codigo_totp(secreto, 30)},
                    headers=cabecera_csrf(client))
    assert r.status_code == 403
    assert "su propia solicitud" in r.json()["detail"]
    assert _asiento(rotacion_id).estado == "solicitada"


def test_la_emergencia_admite_un_solo_admin_pero_queda_marcada(client):
    """La vía de emergencia existe para que la contención no ocurra fuera del sistema.

    Con un único administrador disponible, la regla estricta no impediría la
    rotación: la empujaría a hacerse a mano y sin registro. Aquí se hace dentro,
    marcada de forma imborrable y con una revisión pendiente.
    """
    secreto = autenticar_admin(client)
    cred = _credencial(client, "srv-emergencia")
    _envejecer(cred, 100)

    r = solicitar_rotacion(
        client, cred, tipo="emergencia",
        motivo="Credencial expuesta en un registro compartido por error; hay que contenerla ya",
    )
    assert r.status_code == 200
    rotacion_id = r.json()["id"]

    r = client.post(f"/api/web/rotacion/solicitudes/{rotacion_id}/autorizar",
                    json={"password": ADMIN_PASS, "codigo": codigo_totp(secreto, 30)},
                    headers=cabecera_csrf(client))
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["emergencia_sin_segundo_par"] is True
    assert cuerpo["revision_pendiente"] is True

    # Aparece en el panel como revisión pendiente, y quien la autorizó no puede cerrarla.
    panel = client.get("/api/web/rotacion/panel").json()
    assert [a["id"] for a in panel["revisiones_pendientes"]] == [rotacion_id]

    r = client.post(f"/api/web/rotacion/solicitudes/{rotacion_id}/revisar",
                    json={"nota": "Revisada"}, headers=cabecera_csrf(client))
    assert r.status_code == 403
    assert "otro administrador" in r.json()["detail"]

    # Otro administrador sí la cierra.
    autorizador, _codigos = segundo_administrador(client)
    r = autorizador.post(f"/api/web/rotacion/solicitudes/{rotacion_id}/revisar",
                         json={"nota": "Incidente confirmado en el parte del día"},
                         headers=cabecera_csrf(autorizador))
    assert r.status_code == 200
    assert r.json()["revision_pendiente"] is False


def test_fuera_de_la_ventana_la_emergencia_vuelve_a_exigir_dos_pares(client):
    autenticar_admin(client)
    cred = _credencial(client, "srv-ventana")
    _envejecer(cred, 100)

    r = solicitar_rotacion(
        client, cred, tipo="emergencia",
        motivo="Incidente de exposición de la credencial que exige contención inmediata",
    )
    rotacion_id = r.json()["id"]

    # Se envejece la solicitud más allá de la ventana configurada.
    db = sesion_bd()
    try:
        from app.config import get_settings
        from app.models import RotacionCredencial, ahora_utc

        ventana = get_settings().rotacion_emergencia_ventana_min
        fila = db.get(RotacionCredencial, rotacion_id)
        fila.solicitado_en = ahora_utc() - datetime.timedelta(minutes=ventana + 5)
        db.commit()
    finally:
        db.close()

    from app.security import recovery
    from app.servicios.rotacion import ErrorRotacion, autorizar

    db = sesion_bd()
    try:
        from app.models import RotacionCredencial, Usuario

        admin = db.scalar(select(Usuario).where(Usuario.username == "admin"))
        fila = db.get(RotacionCredencial, rotacion_id)
        assert recovery is not None
        with pytest.raises(ErrorRotacion) as exc:
            autorizar(db, rotacion=fila, usuario=admin)
        assert "ventana de emergencia" in exc.value.mensaje
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 3. Reautenticación del autorizador
# ---------------------------------------------------------------------------


def test_autorizar_sin_reautenticarse_falla(client):
    autenticar_admin(client)
    cred = _credencial(client, "srv-reauth")
    _envejecer(cred, 100)
    rotacion_id = solicitar_rotacion(client, cred).json()["id"]

    autorizador, _codigos = segundo_administrador(client)
    r = autorizador.post(f"/api/web/rotacion/solicitudes/{rotacion_id}/autorizar",
                         json={"password": "", "codigo": ""},
                         headers=cabecera_csrf(autorizador))
    assert r.status_code == 400

    r = autorizador.post(f"/api/web/rotacion/solicitudes/{rotacion_id}/autorizar",
                         json={"password": "contraseña-incorrecta", "codigo": "000000"},
                         headers=cabecera_csrf(autorizador))
    assert r.status_code == 403
    assert _asiento(rotacion_id).estado == "solicitada"


def test_el_codigo_por_correo_no_sirve_para_autorizar(client, monkeypatch):
    """Un buzón compartido no acredita a una segunda persona (§3.5 del plan)."""
    from app.security import segundo_factor

    llamadas = {}

    original = segundo_factor.comprobar

    def espia(db, usuario, codigo, *, permitir_correo=True):
        llamadas["permitir_correo"] = permitir_correo
        return original(db, usuario, codigo, permitir_correo=permitir_correo)

    monkeypatch.setattr(segundo_factor, "comprobar", espia)

    autenticar_admin(client)
    cred = _credencial(client, "srv-correo")
    _envejecer(cred, 100)
    rotacion_id = solicitar_rotacion(client, cred).json()["id"]
    autorizar_rotacion(client, rotacion_id)

    assert llamadas["permitir_correo"] is False


# ---------------------------------------------------------------------------
# 4. Motivo obligatorio y reforzado
# ---------------------------------------------------------------------------


def test_el_motivo_es_obligatorio(client):
    autenticar_admin(client)
    cred = _credencial(client, "srv-motivo")
    _envejecer(cred, 100)

    r = solicitar_rotacion(client, cred, motivo="")
    assert r.status_code == 400
    r = solicitar_rotacion(client, cred, motivo="porque sí")
    assert r.status_code == 400


def test_la_rotacion_temprana_exige_motivo_reforzado(client):
    """Una credencial recién rotada que se vuelve a rotar debe justificarse mejor."""
    autenticar_admin(client)
    cred = _credencial(client, "srv-temprana")  # recién creada: 0 días

    r = solicitar_rotacion(client, cred, motivo="Rotación de rutina")
    assert r.status_code == 400
    assert "temprana" in r.json()["detail"].lower()

    r = solicitar_rotacion(
        client, cred,
        motivo="La contraseña se compartió por un canal no seguro y hay que reemplazarla",
    )
    assert r.status_code == 200
    assert r.json()["temprana"] is True


# ---------------------------------------------------------------------------
# 5. La medida del tiempo: a los dos días o a los noventa exactos
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dias", [2, 90, 120])
def test_dias_al_rotar_y_desvio_son_correctos(client, dias):
    autenticar_admin(client)
    cred = _credencial(client, f"srv-dias-{dias}")
    _envejecer(cred, dias)

    motivo = ("La contraseña se expuso y debe reemplazarse cuanto antes"
              if dias < 23 else MOTIVO_PRUEBA)
    asiento = rotar_credencial(client, cred, NUEVA, motivo=motivo)

    assert asiento["dias_al_rotar"] == dias
    assert asiento["desvio_dias"] == dias - 90  # vigencia por defecto
    assert asiento["resultado"] == "manual"
    assert asiento["estado"] == "cerrada"
    # Sin agente no hay comprobación automática, y se dice tal cual.
    assert asiento["verificacion"] == "ninguna"


def test_la_rotacion_reinicia_el_contador_y_archiva_la_anterior(client):
    autenticar_admin(client)
    cred = _credencial(client, "srv-contador")
    _envejecer(cred, 100)
    rotar_credencial(client, cred, NUEVA)

    db = sesion_bd()
    try:
        from app.models import Credencial, HistorialCredencial
        from app.security.crypto import descifrar

        credencial = db.get(Credencial, cred)
        assert credencial.dias_sin_rotar == 0
        assert descifrar(credencial.password_cifrada) == NUEVA
        anteriores = db.scalars(select(HistorialCredencial).where(
            HistorialCredencial.credencial_id == cred)).all()
        assert [descifrar(h.password_cifrada) for h in anteriores] == [CLAVE_SECRETA]
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 6. El libro mayor es permanente
# ---------------------------------------------------------------------------


def test_el_libro_mayor_sobrevive_al_borrado_de_la_credencial(client):
    """Borrar la credencial no borra la evidencia de quién aprobó qué."""
    autenticar_admin(client)
    cred = _credencial(client, "srv-permanente")
    _envejecer(cred, 100)
    rotar_credencial(client, cred, NUEVA)

    r = client.delete(f"/api/web/credenciales/{cred}", headers=cabecera_csrf(client))
    assert r.status_code == 200

    db = sesion_bd()
    try:
        from app.models import RotacionCredencial

        asientos = db.scalars(select(RotacionCredencial)).all()
        assert len(asientos) == 1
        assert asientos[0].credencial_id is None       # la FK se soltó
        assert asientos[0].activo_nombre == "srv-permanente"  # pero sigue siendo legible
        assert asientos[0].dias_al_rotar == 100
    finally:
        db.close()


def test_el_respaldo_cifrado_incluye_el_libro_mayor(client):
    from app import backup

    autenticar_admin(client)
    cred = _credencial(client, "srv-respaldo-rot")
    _envejecer(cred, 95)
    rotar_credencial(client, cred, NUEVA)

    frase = "Frase-De-Respaldo-Rotacion-2026!"
    db = sesion_bd()
    try:
        datos = backup.exportar(db, frase)
        db.commit()
        resumen = backup.restaurar(db, datos, frase, sobrescribir=True)
        db.commit()
        assert resumen["rotaciones"] == 1

        from app.models import RotacionCredencial

        asiento = db.scalar(select(RotacionCredencial))
        assert asiento.dias_al_rotar == 95
        assert asiento.motivo == MOTIVO_PRUEBA
        assert asiento.autorizado_por_username == "admin-par"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 7. La bitácora firmada
# ---------------------------------------------------------------------------


def test_la_cadena_de_auditoria_se_firma_y_se_verifica(client):
    from app import audit

    autenticar_admin(client)
    db = sesion_bd()
    try:
        resultado = audit.verificar_cadena(db)
        assert resultado["ok"] is True
        assert resultado["firmados"] > 0
        assert resultado["corte_id"] is not None
    finally:
        db.close()


def test_un_registro_alterado_rompe_la_cadena(client):
    from app import audit

    autenticar_admin(client)
    db = sesion_bd()
    try:
        from app.models import RegistroAuditoria

        fila = db.scalar(select(RegistroAuditoria).order_by(RegistroAuditoria.id))
        fila.detalle = "detalle reescrito por quien tenga acceso a la base de datos"
        db.commit()
        resultado = audit.verificar_cadena(db)
        assert resultado["ok"] is False
        assert resultado["motivo"] == "contenido alterado"
    finally:
        db.close()


def test_no_se_puede_degradar_la_firma_a_sha256(client):
    """Reescribir una fila como «heredada» para poder recalcularla se detecta."""
    from app import audit

    autenticar_admin(client)
    db = sesion_bd()
    try:
        from app.models import RegistroAuditoria

        fila = db.scalar(select(RegistroAuditoria).order_by(RegistroAuditoria.id.desc()))
        fila.hash_algoritmo = ""
        fila.hash_registro = audit._hash_heredado(fila)
        db.commit()
        resultado = audit.verificar_cadena(db)
        assert resultado["ok"] is False
        assert "degradada" in resultado["motivo"]
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 8. Prueba de arquitectura: el punto único de escritura
# ---------------------------------------------------------------------------


# Módulos que exponen credenciales del INVENTARIO. El vault personal queda
# fuera a propósito (§10 del plan): es un almacén privado de cada usuario, no
# inventario, y no entra en el ciclo de gobernanza.
_MODULOS_CONTROLADOR = (
    "app/routes/credentials.py",
    "app/api_web/credentials.py",
    "app/importacion.py",
)
_ESCRITURA = re.compile(r"password_cifrada\s*=")


def test_ningun_controlador_escribe_la_contrasena_de_una_credencial():
    """El control que impide que la puerta de atrás vuelva dentro de seis meses.

    Si esta prueba falla, alguien añadió una vía para cambiar una contraseña del
    inventario sin pasar por ``app/servicios/rotacion.py``. No se arregla
    borrando la prueba: se arregla haciendo pasar esa vía por el servicio.
    """
    infractores = []
    for ruta in _MODULOS_CONTROLADOR:
        texto = (RAIZ / ruta).read_text(encoding="utf-8")
        for numero, linea in enumerate(texto.splitlines(), start=1):
            if linea.lstrip().startswith("#"):
                continue  # comentario que nombra el campo
            if _ESCRITURA.search(linea):
                infractores.append(f"{ruta}:{numero}: {linea.strip()}")
    assert not infractores, (
        "Escritura de password_cifrada fuera de app/servicios/rotacion.py:\n"
        + "\n".join(infractores)
    )


def test_la_importacion_da_de_alta_pero_no_rota(client):
    """Un alta no es una rotación: no deja asiento en el libro mayor."""
    autenticar_admin(client)
    servidor = _crear_servidor(client, "srv-importado")
    assert servidor

    csv = (
        "tipo,nombre,activo_tipo,padre,usuario_acceso,password,servicio,puerto,descripcion\n"
        "credencial,,servidor,srv-importado,admin,Clave-Importada-2026!,SSH,22,Alta por CSV\n"
    )
    csrf = csrf_de(client, "/importar")
    r = client.post("/importar", data={"csrf_token": csrf},
                    files={"archivo": ("inventario.csv", csv, "text/csv")})
    assert r.status_code in (200, 303), r.status_code

    db = sesion_bd()
    try:
        from app.models import Credencial, RotacionCredencial
        from app.security.crypto import descifrar

        credencial = db.scalar(select(Credencial).where(Credencial.usuario_acceso == "admin"))
        assert credencial is not None
        assert descifrar(credencial.password_cifrada) == "Clave-Importada-2026!"
        assert credencial.via_rotacion == "manual"
        assert db.scalar(select(func.count(RotacionCredencial.id))) == 0
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 9. Permisos
# ---------------------------------------------------------------------------


def test_el_auditor_ve_el_panel_pero_no_autoriza(client, crear_cliente):
    from tests.conftest import autenticar_usuario_nuevo, crear_usuario

    autenticar_admin(client)
    cred = _credencial(client, "srv-auditor")
    _envejecer(cred, 100)
    rotacion_id = solicitar_rotacion(client, cred).json()["id"]

    clave = crear_usuario(client, "auditora", "auditor")
    aud = crear_cliente()
    autenticar_usuario_nuevo(aud, "auditora", clave)

    assert aud.get("/api/web/rotacion/panel").status_code == 200
    r = aud.post(f"/api/web/rotacion/solicitudes/{rotacion_id}/autorizar",
                 json={"password": "x", "codigo": "000000"},
                 headers=cabecera_csrf(aud))
    assert r.status_code == 403


def test_el_analista_no_alcanza_la_gobernanza(client, crear_cliente):
    from tests.conftest import autenticar_usuario_nuevo, crear_usuario

    autenticar_admin(client)
    clave = crear_usuario(client, "analista1", "analista")
    ana = crear_cliente()
    autenticar_usuario_nuevo(ana, "analista1", clave)

    assert ana.get("/api/web/rotacion/panel").status_code == 403


# ---------------------------------------------------------------------------
# 10. Nada de lo existente cambia de contrato
# ---------------------------------------------------------------------------


def test_la_api_v1_del_siem_sigue_sin_saber_de_rotaciones(client):
    """`/api/v1` es de solo lectura y su contrato no cambia en esta versión."""
    autenticar_admin(client)
    csrf = csrf_de(client, "/tokens")
    r = client.post("/tokens", data={"nombre": "siem", "csrf_token": csrf})
    assert r.status_code == 303
    token = parse_qs(urlparse(r.headers["location"]).query)["nuevo_token"][0]

    r = client.get("/api/v1/inventario", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert "rotaciones" not in json.dumps(r.json())


# ---------------------------------------------------------------------------
# 11. La regla de dos pares necesita dos administradores
# ---------------------------------------------------------------------------


def test_el_panel_avisa_cuando_falta_el_segundo_administrador(client):
    """Con un solo admin la regla no es más débil: no se puede aplicar.

    El manual promete que el sistema lo advierte. Aquí se comprueba que lo hace
    donde se toman las decisiones, no solo en un registro que nadie lee.
    """
    autenticar_admin(client)

    panel = client.get("/api/web/rotacion/panel").json()
    assert panel["gobernanza"]["administradores_activos"] == 1
    assert panel["gobernanza"]["dos_pares_posible"] is False

    segundo_administrador(client)

    panel = client.get("/api/web/rotacion/panel").json()
    assert panel["gobernanza"]["administradores_activos"] == 2
    assert panel["gobernanza"]["dos_pares_posible"] is True


def test_el_arranque_avisa_si_no_hay_segundo_administrador(client):
    """El mantenimiento (que corre al arrancar y cada pocas horas) lo registra.

    Se engancha un manejador al propio logger en vez de usar ``caplog``: este
    depende de que la propagación siga activa, y basta con que otra prueba de la
    suite toque la configuración de logging para que capture en vacío y el
    control pase sin verificar nada.
    """
    import logging

    from app.main import ejecutar_mantenimiento

    autenticar_admin(client)

    mensajes: list[str] = []

    class _Captura(logging.Handler):
        def emit(self, registro: logging.LogRecord) -> None:
            mensajes.append(registro.getMessage())

    logger = logging.getLogger("app.main")
    manejador = _Captura()
    nivel = logger.level
    logger.addHandler(manejador)
    logger.setLevel(logging.WARNING)
    try:
        ejecutar_mantenimiento()
    finally:
        logger.removeHandler(manejador)
        logger.setLevel(nivel)

    assert any("regla de dos pares" in m for m in mensajes), mensajes
    assert any("Solo hay 1 administrador" in m for m in mensajes)
