"""La versión no debe desincronizarse entre sus fuentes.

`app/__init__.py` (`__version__`) es la fuente de verdad; `pyproject.toml` debe
coincidir y el `CHANGELOG.md` debe documentar esa versión. Estas pruebas hacen
cumplir la política de [`docs/versionado.md`](../docs/versionado.md).
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import app

RAIZ = Path(__file__).resolve().parent.parent
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def test_version_es_semver_valida():
    assert SEMVER.match(app.__version__), f"__version__ no es SemVer: {app.__version__!r}"


def test_pyproject_coincide_con_version():
    datos = tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))
    assert datos["project"]["version"] == app.__version__


def test_changelog_documenta_la_version_actual():
    changelog = (RAIZ / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## [{app.__version__}]" in changelog, (
        f"CHANGELOG.md no tiene una sección para la versión {app.__version__}"
    )
