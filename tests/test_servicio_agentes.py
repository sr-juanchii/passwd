"""Servicios de agentes: cifrado del trabajo, enrolamiento e identidad (v1.4.0, 2a).

Pruebas del servicio sin HTTP: las rutas llegan en el commit de la API. Plan:
docs/plan-rotacion-agentes.md §2.1 (identidad de vida corta), §3.1 (cifrado
hacia el agente), §4.5 (ciclo de vida) y §5 (cobertura).
"""

from __future__ import annotations

import base64
import json
from datetime import timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from app.servicios import cifrado_agente

VECTOR = Path(__file__).parent / "vectores" / "cifrado_agente.json"


def _par() -> tuple[X25519PrivateKey, str]:
    privada = X25519PrivateKey.generate()
    publica = privada.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return privada, base64.b64encode(publica).decode("ascii")


# ---------------------------------------------------------------------------
# Cifrado hacia el agente
# ---------------------------------------------------------------------------


def test_sellar_y_abrir_de_ida_y_vuelta():
    privada, publica = _par()
    contenido = {"trabajo_id": 7, "nueva": "Clave-Con-Eñe-2026!"}
    assert cifrado_agente.abrir(privada, cifrado_agente.sellar(publica, contenido)) == contenido


def test_otra_clave_privada_no_abre_el_sobre():
    _privada, publica = _par()
    ajena, _ = _par()
    sobre = cifrado_agente.sellar(publica, {"nueva": "secreta"})
    with pytest.raises(cifrado_agente.ErrorCifradoAgente):
        cifrado_agente.abrir(ajena, sobre)


def test_cada_sobre_usa_una_clave_efimera_distinta():
    _privada, publica = _par()
    a = cifrado_agente.sellar(publica, {"x": 1})
    b = cifrado_agente.sellar(publica, {"x": 1})
    assert a["efimera"] != b["efimera"]


def test_el_vector_compartido_con_el_agente_go_se_abre():
    """El mismo archivo lo leerá el agente Go: si este falla, los dos lados divergen."""
    vector = json.loads(VECTOR.read_text(encoding="utf-8"))
    privada = X25519PrivateKey.from_private_bytes(base64.b64decode(vector["clave_privada_agente"]))
    assert cifrado_agente.abrir(privada, vector["sobre"]) == vector["contenido"]
    assert cifrado_agente.huella(vector["clave_publica_agente"]) == vector["huella_clave_publica"]


@pytest.mark.parametrize("clave", ["", "no-es-base64!", base64.b64encode(b"corta").decode()])
def test_clave_publica_invalida_se_rechaza(clave):
    with pytest.raises(cifrado_agente.ErrorCifradoAgente):
        cifrado_agente.validar_clave_publica(clave)


# ---------------------------------------------------------------------------
# Escenario con base de datos
# ---------------------------------------------------------------------------


@pytest.fixture()
def bd(request, monkeypatch):
    """BD de una aplicación con los agentes ACTIVADOS (por defecto están apagados)."""
    monkeypatch.setenv("PASSWD_AGENTES_ENABLED", "true")
    request.getfixturevalue("aplicacion")
    from tests.conftest import sesion_bd

    db = sesion_bd()
    yield db
    db.rollback()
    db.close()


@pytest.fixture()
def admin(bd):
    from app.models import ROL_ADMIN, Usuario

    usuario = Usuario(username="admin-agentes", email="admin-agentes@ejemplo.local",
                      password_hash="x", rol=ROL_ADMIN)
    bd.add(usuario)
    bd.flush()
    return usuario


def _servidor(bd, nombre="srv-agente"):
    from app.models import ServidorFisico

    servidor = ServidorFisico(nombre=nombre)
    bd.add(servidor)
    bd.flush()
    return servidor


def _alta(bd, admin, servidor, nombre="agente-1"):
    from app.models import ACTIVO_FISICO
    from app.servicios import agentes

    return agentes.alta(bd, tipo_activo=ACTIVO_FISICO, activo_id=servidor.id,
                        nombre=nombre, usuario=admin)


def _enrolado(bd, admin, servidor=None, ip="10.0.0.5"):
    from app.servicios import agentes

    servidor = servidor or _servidor(bd)
    _agente, enrolamiento = _alta(bd, admin, servidor)
    _privada, publica = _par()
    return agentes.enrolar(bd, token_enrolamiento=enrolamiento, clave_publica=publica,
                           nombre_host="srv-agente.local", version="1.4.0", ip=ip)


def test_con_los_agentes_apagados_no_se_da_de_alta_ninguno(aplicacion):
    from app.models import ACTIVO_FISICO, ROL_ADMIN, ServidorFisico, Usuario
    from app.servicios import agentes
    from tests.conftest import sesion_bd

    db = sesion_bd()
    try:
        usuario = Usuario(username="adm", email="adm@ejemplo.local", password_hash="x", rol=ROL_ADMIN)
        servidor = ServidorFisico(nombre="srv-apagado")
        db.add_all([usuario, servidor])
        db.flush()
        with pytest.raises(agentes.ErrorAgente) as error:
            agentes.alta(db, tipo_activo=ACTIVO_FISICO, activo_id=servidor.id, nombre="a", usuario=usuario)
        assert error.value.codigo == 409
    finally:
        db.rollback()
        db.close()


def test_un_dispositivo_de_red_no_admite_agente(bd, admin):
    from app.models import ACTIVO_DISPOSITIVO, DispositivoRed
    from app.servicios import agentes

    switch = DispositivoRed(nombre="sw-core")
    bd.add(switch)
    bd.flush()
    with pytest.raises(agentes.ErrorAgente, match="dispositivos de red"):
        agentes.alta(bd, tipo_activo=ACTIVO_DISPOSITIVO, activo_id=switch.id, nombre="a", usuario=admin)


def test_un_segundo_agente_en_el_mismo_activo_se_rechaza(bd, admin):
    from app.servicios import agentes

    servidor = _servidor(bd)
    _alta(bd, admin, servidor)
    with pytest.raises(agentes.ErrorAgente) as error:
        _alta(bd, admin, servidor, nombre="agente-2")
    assert error.value.codigo == 409


def test_el_enrolamiento_es_de_un_solo_uso(bd, admin):
    from app.models import AGENTE_ACTIVO
    from app.servicios import agentes

    _agente, enrolamiento = _alta(bd, admin, _servidor(bd))
    _privada, publica = _par()
    agente, token = agentes.enrolar(bd, token_enrolamiento=enrolamiento, clave_publica=publica,
                                    nombre_host="h", version="1.4.0", ip="10.0.0.5")
    assert agente.estado == AGENTE_ACTIVO
    assert agente.clave_huella == cifrado_agente.huella(publica)
    assert agente.token_hash != token  # solo el hash en la base de datos

    with pytest.raises(agentes.ErrorAgente) as error:
        agentes.enrolar(bd, token_enrolamiento=enrolamiento, clave_publica=publica,
                        nombre_host="h", version="1.4.0", ip="10.0.0.6")
    assert error.value.codigo == 401


def test_un_enrolamiento_caducado_se_rechaza(bd, admin):
    from app.models import ahora_utc
    from app.servicios import agentes

    agente, enrolamiento = _alta(bd, admin, _servidor(bd))
    agente.enrolamiento_expira_en = ahora_utc() - timedelta(minutes=1)
    _privada, publica = _par()
    with pytest.raises(agentes.ErrorAgente, match="caducó"):
        agentes.enrolar(bd, token_enrolamiento=enrolamiento, clave_publica=publica,
                        nombre_host="h", version="1.4.0", ip="10.0.0.5")


def test_el_token_autentica_y_al_caducar_deja_de_hacerlo(bd, admin):
    from app.models import ahora_utc
    from app.servicios import agentes

    agente, token = _enrolado(bd, admin)
    assert agentes.autenticar(bd, token) == (agente, False)
    assert agentes.cobertura(agente) == agentes.COBERTURA_CONECTADO

    agente.token_expira_en = ahora_utc() - timedelta(seconds=1)
    assert agentes.autenticar(bd, token) is None
    assert agentes.cobertura(agente) == agentes.COBERTURA_CADUCADO


def test_sin_latido_mas_alla_del_umbral_la_insignia_avisa(bd, admin):
    from app.models import ahora_utc
    from app.servicios import agentes

    agente, _token = _enrolado(bd, admin)
    agente.ultimo_contacto_en = ahora_utc() - timedelta(hours=25)
    assert agentes.cobertura(agente) == agentes.COBERTURA_SIN_CONTACTO
    assert agentes.cobertura(None) == agentes.COBERTURA_SIN_AGENTE


def test_la_renovacion_deja_valer_el_token_anterior_solo_durante_el_solapamiento(bd, admin):
    from app.models import ahora_utc
    from app.servicios import agentes

    agente, viejo = _enrolado(bd, admin)
    # Lejos de caducar: el latido no renueva.
    assert agentes.saludo(bd, agente=agente, ip="10.0.0.5", version="1.4.0")["token_nuevo"] is None

    # En su último cuarto de vida: renueva.
    agente.token_expira_en = ahora_utc() + timedelta(hours=1)
    nuevo = agentes.saludo(bd, agente=agente, ip="10.0.0.5", version="1.4.0")["token_nuevo"]
    assert nuevo and nuevo != viejo
    assert agentes.autenticar(bd, nuevo) == (agente, False)
    assert agentes.autenticar(bd, viejo) == (agente, True)   # dentro del solapamiento

    agente.token_anterior_expira_en = ahora_utc() - timedelta(seconds=1)
    assert agentes.autenticar(bd, viejo) is None              # fuera de él


def test_quien_entra_con_el_token_anterior_recibe_otro_nuevo(bd, admin):
    """Si la respuesta de la renovación se perdió, el agente no se queda fuera."""
    from app.models import ahora_utc
    from app.servicios import agentes

    agente, viejo = _enrolado(bd, admin)
    agente.token_expira_en = ahora_utc() + timedelta(hours=1)
    perdido = agentes.saludo(bd, agente=agente, ip="10.0.0.5", version="1.4.0")["token_nuevo"]

    _, con_anterior = agentes.autenticar(bd, viejo)
    otro = agentes.saludo(bd, agente=agente, ip="10.0.0.5", version="1.4.0",
                          con_token_anterior=con_anterior)["token_nuevo"]
    assert otro and otro not in (perdido, viejo)
    assert agentes.autenticar(bd, otro) == (agente, False)
    assert agentes.autenticar(bd, perdido) is None


def test_renovar_desde_otra_ip_en_la_misma_ventana_es_una_anomalia(bd, admin):
    from sqlalchemy import select

    from app import audit
    from app.models import RegistroAuditoria, ahora_utc
    from app.servicios import agentes

    agente, _token = _enrolado(bd, admin, ip="10.0.0.5")
    agente.token_expira_en = ahora_utc() + timedelta(hours=1)
    agentes.saludo(bd, agente=agente, ip="203.0.113.9", version="1.4.0")

    anomalias = bd.scalars(select(RegistroAuditoria)
                           .where(RegistroAuditoria.accion == audit.AGENTE_ANOMALIA_IP)).all()
    assert len(anomalias) == 1
    assert "203.0.113.9" in anomalias[0].detalle and "10.0.0.5" in anomalias[0].detalle
    assert anomalias[0].exito is False


def test_revocar_devuelve_las_credenciales_al_flujo_manual(bd, admin):
    from app.models import VIA_ROTACION_AGENTE, VIA_ROTACION_MANUAL
    from app.servicios import agentes, rotacion

    servidor = _servidor(bd)
    agente, token = _enrolado(bd, admin, servidor)
    credencial = rotacion.nueva_credencial(bd, password="Inicial-2026!", usuario_acceso="root",
                                           servidor_fisico_id=servidor.id)
    bd.flush()
    agentes.usar_agente(bd, credencial=credencial, usuario=admin)
    assert credencial.via_rotacion == VIA_ROTACION_AGENTE

    agentes.revocar(bd, agente=agente, usuario=admin)
    assert credencial.via_rotacion == VIA_ROTACION_MANUAL
    assert agente.vinculo_vigente is None
    assert agentes.autenticar(bd, token) is None
    assert agentes.cobertura(agentes.agente_vigente_de(bd, *agentes.activo_de_credencial(credencial))) \
        == agentes.COBERTURA_SIN_AGENTE
    _alta(bd, admin, servidor, nombre="agente-sustituto")  # el activo queda libre


def test_una_credencial_no_puede_rotar_por_el_agente_de_otro_activo(bd, admin):
    from app.servicios import agentes, rotacion

    _enrolado(bd, admin, _servidor(bd, "srv-con-agente"))
    sin_agente = _servidor(bd, "srv-sin-agente")
    credencial = rotacion.nueva_credencial(bd, password="Inicial-2026!", usuario_acceso="root",
                                           servidor_fisico_id=sin_agente.id)
    bd.flush()
    with pytest.raises(agentes.ErrorAgente) as error:
        agentes.usar_agente(bd, credencial=credencial, usuario=admin)
    assert error.value.codigo == 409


def test_version_minima_sin_gracia_si_se_fija_por_entorno(bd, admin, monkeypatch):
    from app.config import get_settings
    from app.servicios import agentes

    agente, _token = _enrolado(bd, admin)
    monkeypatch.setattr(get_settings(), "agentes_version_minima", "1.5.0")
    assert agentes.version_admitida(bd, agente) == (False, False)
    agente.version_agente = "1.5.2"
    assert agentes.version_admitida(bd, agente) == (True, False)


# ---------------------------------------------------------------------------
# Telemetría
# ---------------------------------------------------------------------------


def test_la_telemetria_se_acota_y_refresca_el_contacto(bd, admin):
    import json

    from app.models import ahora_utc
    from app.servicios import agentes

    agente, _token = _enrolado(bd, admin)
    agente.ultimo_contacto_en = ahora_utc() - timedelta(days=3)
    discos = [{"montaje": f"/datos{i}", "total_bytes": 10, "usado_pct": 150} for i in range(40)]

    fila = agentes.registrar_telemetria(
        bd, agente=agente, ip="10.0.0.5", cpu_pct=-7, ram_pct=55, disco_pct=250, uptime_s=-1,
        sistema_operativo="Debian " + "x" * 500, kernel="6.18", discos=discos,
    )
    assert (fila.cpu_pct, fila.ram_pct, fila.disco_pct, fila.uptime_s) == (0, 55, 100, 0)
    assert len(fila.sistema_operativo) == 120
    guardados = json.loads(fila.discos_json)
    assert len(guardados) == agentes.MAX_DISCOS and guardados[0]["usado_pct"] == 100
    assert fila.recortada is True                      # lo dice, en vez de ocultarlo
    assert agentes.cobertura(agente) == agentes.COBERTURA_CONECTADO
    bd.flush()
    assert agentes.ultima_telemetria(bd, agente).id == fila.id


def test_la_telemetria_antigua_se_purga(bd, admin):
    from app.models import TelemetriaAgente, ahora_utc
    from app.servicios import agentes

    agente, _token = _enrolado(bd, admin)
    vieja = agentes.registrar_telemetria(bd, agente=agente, ip="10.0.0.5", cpu_pct=1)
    vieja.fecha = ahora_utc() - timedelta(days=31)
    agentes.registrar_telemetria(bd, agente=agente, ip="10.0.0.5", cpu_pct=2)
    bd.flush()
    assert agentes.purgar_telemetria(bd) == 1
    assert [f.cpu_pct for f in bd.query(TelemetriaAgente).all()] == [2]


# ---------------------------------------------------------------------------
# Alerta de agente sin contacto (§8.2)
# ---------------------------------------------------------------------------


def test_un_agente_callado_se_avisa_una_vez_por_silencio(bd, admin, monkeypatch):
    from app import notifications
    from app.models import ahora_utc
    from app.servicios import agentes

    enviadas = []
    monkeypatch.setattr(notifications, "enviar_alerta",
                        lambda asunto, cuerpo: enviadas.append((asunto, cuerpo)) or True)
    agente, _token = _enrolado(bd, admin)
    assert agentes.avisar_sin_contacto(bd) == 0          # conectado: nada que decir

    agente.ultimo_contacto_en = ahora_utc() - timedelta(hours=25)
    bd.flush()
    assert agentes.avisar_sin_contacto(bd) == 1
    assert "agente-1" in enviadas[0][0]
    # El siguiente mantenimiento no repite el aviso del mismo silencio…
    assert agentes.avisar_sin_contacto(bd) == 0
    # …ni cuando ese silencio acaba también en identidad caducada.
    agente.token_expira_en = ahora_utc() - timedelta(minutes=1)
    bd.flush()
    assert agentes.avisar_sin_contacto(bd) == 0

    # Vuelve, late, y se calla de nuevo: es otro silencio y se avisa otra vez.
    agente.token_expira_en = ahora_utc() + timedelta(hours=20)
    agente.ultimo_contacto_en = ahora_utc() + timedelta(seconds=1)
    bd.flush()
    assert agentes.avisar_sin_contacto(bd) == 0
    assert agentes.avisar_sin_contacto(bd, ahora=ahora_utc() + timedelta(hours=26)) == 1
    assert len(enviadas) == 2


def test_la_alerta_sin_contacto_no_cuenta_pendientes_ni_revocados(bd, admin, monkeypatch):
    from app import notifications
    from app.models import ahora_utc
    from app.servicios import agentes

    monkeypatch.setattr(notifications, "enviar_alerta", lambda *_: True)
    _pendiente, _ = _alta(bd, admin, _servidor(bd, "srv-pendiente"), nombre="pendiente")
    revocado, _token = _enrolado(bd, admin)
    revocado.ultimo_contacto_en = ahora_utc() - timedelta(hours=48)
    agentes.revocar(bd, agente=revocado, usuario=admin)
    bd.flush()
    assert agentes.avisar_sin_contacto(bd, ahora=ahora_utc() + timedelta(days=3)) == 0


def test_con_los_agentes_apagados_no_hay_alertas(bd, admin, monkeypatch):
    from app.config import get_settings
    from app.models import ahora_utc
    from app.servicios import agentes

    agente, _token = _enrolado(bd, admin)
    agente.ultimo_contacto_en = ahora_utc() - timedelta(hours=48)
    monkeypatch.setattr(get_settings(), "agentes_enabled", False)
    assert agentes.avisar_sin_contacto(bd) == 0


def test_los_valores_por_omision_dejan_ver_cada_estado():
    """Relaciones entre ajustes que, rotas, esconden estados sin que nada falle.

    Con el umbral de «sin contacto» igual a la vida de la identidad, un agente
    callado pasaría directamente a «caducado»; con la ventana del trabajo igual
    al latido, un trabajo despachado justo después de un latido vencería sin
    recogerse.
    """
    from app.config import OVERRIDABLES

    por_omision = {clave: valor[2] for clave, valor in OVERRIDABLES.items()}
    assert por_omision["agentes_umbral_sin_contacto_horas"] < por_omision["agentes_token_vida_horas"]
    assert por_omision["rotacion_ventana_job_min"] > por_omision["agentes_telemetria_intervalo_min"]
