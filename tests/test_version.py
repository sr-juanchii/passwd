"""La versión no debe desincronizarse entre sus fuentes.

`app/__init__.py` (`__version__`) es la fuente de verdad; `pyproject.toml` debe
coincidir y el `CHANGELOG.md` debe documentar esa versión. Estas pruebas hacen
cumplir la política de [`docs/versionado.md`](../docs/versionado.md).
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

import app

RAIZ = Path(__file__).resolve().parent.parent

# Gramática de SemVer 2.0.0 con el bloque de pre-release opcional (§9): cada
# identificador es numérico sin ceros a la izquierda, o alfanumérico. No se
# admiten metadatos de compilación (`+...`): este proyecto no los usa y
# aceptarlos solo abriría formas de nombrar lo mismo de varias maneras.
SEMVER = re.compile(
    r"^\d+\.\d+\.\d+"
    r"(?:-(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*)?$"
)

SECCION_SIN_PUBLICAR = "## [Sin publicar]"


def es_prelanzamiento(version: str) -> bool:
    """¿La versión lleva sufijo de pre-release (`1.3.0-rc.1`)?"""
    return "-" in version


def test_version_es_semver_valida():
    assert SEMVER.match(app.__version__), f"__version__ no es SemVer: {app.__version__!r}"


@pytest.mark.parametrize("version", ["1.0.0", "1.2.0", "1.3.0-rc.1", "2.0.0-alpha.1", "1.3.0-rc1"])
def test_la_expresion_acepta_las_versiones_validas(version):
    assert SEMVER.match(version), f"debería aceptarse: {version!r}"


@pytest.mark.parametrize(
    "version",
    [
        "p1.3.0",     # el prefijo no es SemVer (ni PEP 440)
        "1.3",        # faltan componentes
        "1.3.0.1",    # sobran
        "1.3.0-",     # sufijo vacío
        "1.3.0-01",   # cero a la izquierda en un identificador numérico
        "1.3.0+meta", # metadatos de compilación: no se usan en este proyecto
        "v1.3.0",     # la «v» es de la etiqueta de git, no de la versión
        "",
    ],
)
def test_la_expresion_rechaza_lo_que_no_es_semver(version):
    """Sin esta prueba, relajar el patrón para los pre-releases no tendría quien lo vigile."""
    assert not SEMVER.match(version), f"no debería aceptarse: {version!r}"


def test_pyproject_coincide_con_version():
    datos = tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))
    assert datos["project"]["version"] == app.__version__


def test_changelog_documenta_la_version_actual():
    """Una versión final necesita su sección; un pre-release vive en «Sin publicar».

    No es una excepción de conveniencia: un pre-release publica precisamente
    cambios que todavía no están cerrados, y darles una sección propia obligaría
    a reescribirla al liberar la versión final.
    """
    changelog = (RAIZ / "CHANGELOG.md").read_text(encoding="utf-8")

    if es_prelanzamiento(app.__version__):
        assert SECCION_SIN_PUBLICAR in changelog, (
            f"{app.__version__} es un pre-release y CHANGELOG.md no tiene «{SECCION_SIN_PUBLICAR}»"
        )
        cuerpo = changelog.split(SECCION_SIN_PUBLICAR, 1)[1].split("\n## ", 1)[0]
        assert cuerpo.strip(), "«Sin publicar» está vacía: el pre-release no documenta nada"
        return

    assert f"## [{app.__version__}]" in changelog, (
        f"CHANGELOG.md no tiene una sección para la versión {app.__version__}"
    )
