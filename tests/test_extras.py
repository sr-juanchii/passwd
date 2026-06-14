"""Pruebas de extras: modo oscuro (cliente, compatible con la CSP estricta)."""

from __future__ import annotations

from tests.conftest import autenticar_admin


def test_toggle_de_tema_presente_para_usuario(client):
    autenticar_admin(client)
    pagina = client.get("/")
    assert 'id="toggle-tema"' in pagina.text  # botón en la cabecera


def test_js_aplica_tema_persistido(client):
    js = client.get("/static/app.js")
    assert js.status_code == 200
    assert 'localStorage.getItem("tema")' in js.text       # lee la preferencia
    assert 'document.documentElement.dataset.tema' in js.text


def test_css_define_tema_oscuro(client):
    css = client.get("/static/styles.css")
    assert css.status_code == 200
    assert 'html[data-tema="oscuro"]' in css.text
