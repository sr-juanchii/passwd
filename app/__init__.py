"""Gestor de contraseñas de servidores con inventario relacional y MFA."""

# Fuente de verdad de la versión (SemVer, con sufijo de pre-release cuando toca:
# «1.3.0-rc.1»). Debe coincidir con pyproject.toml (lo verifica
# tests/test_version.py). Política e histórico: docs/versionado.md y
# CHANGELOG.md. La expone GET /healthz y la metadata de la API, de modo que lo
# que está desplegado siempre se puede identificar en caliente.
__version__ = "1.4.0-rc.3"
