"""Enumeración del registro de rutas de la aplicación.

Las pruebas que verifican propiedades **de toda la superficie** —que ninguna
ruta se alcanza antes del segundo factor, que toda ruta declara su política de
permisos— no pueden partir de una lista escrita a mano: una lista envejece, y
deja de cubrir justo lo que se añadió después. Se enumera el registro real.

Hay dos formas de mirarlo y cada prueba usa la que le sirve:

- ``caminos_del_esquema``: los caminos tal como los publica OpenAPI. Basta para
  recorrer la superficie pidiendo cada endpoint.
- ``rutas_de``: los objetos ``APIRoute`` reales, con sus dependencias. Es lo que
  permite leer **qué permiso exige** cada ruta.

Desde FastAPI 0.141, ``app.routes`` NO aplana los routers incluidos: los envuelve
en ``_IncludedRouter``, de modo que un recorrido plano solo encontraría los
endpoints declarados directamente en la aplicación. Hay que descender por
``original_router`` acumulando el prefijo de cada inclusión.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.routing import APIRoute

# Prefijos con su propio esquema de autenticación o sin lógica de aplicación.
# `/api/agent` se autentica con la identidad del agente, no con una sesión de
# usuario: su propia prueba (tests/test_api_agente.py) exige que TODAS sus rutas
# rechacen sin esa identidad, de modo que una ruta nueva no se cuela por aquí.
PREFIJOS_EXCLUIDOS = ("/api/v1", "/api/agent", "/static", "/docs", "/redoc", "/openapi.json")

METODOS = ("GET", "POST", "PUT", "PATCH", "DELETE")


@dataclass(frozen=True)
class RutaRegistrada:
    """Una ruta del registro, con la política que declara."""

    metodo: str
    camino: str
    #: Permiso RBAC que exige, leído de la dependencia; ``None`` si no exige ninguno.
    permiso: str | None

    @property
    def clave(self) -> str:
        return f"{self.metodo} {self.camino}"


def _permiso_de(ruta: APIRoute) -> str | None:
    """Permiso declarado por la dependencia de autorización, si la hay.

    Se lee del atributo ``permiso_requerido`` que ponen ``requiere_permiso`` y
    ``requiere_permiso_json``. Leerlo del *closure* sería adivinar, y fallaría
    en silencio el día que cambie la forma de la función.
    """
    for dependencia in ruta.dependant.dependencies:
        permiso = getattr(dependencia.call, "permiso_requerido", None)
        if permiso is not None:
            return permiso
    return None


def _recorrer(contenedor, prefijo: str = ""):
    for ruta in getattr(contenedor, "routes", []):
        if isinstance(ruta, APIRoute):
            yield prefijo + ruta.path, ruta
        elif type(ruta).__name__ == "_IncludedRouter":
            yield from _recorrer(ruta.original_router,
                                 prefijo + ruta.include_context.prefix)
        elif hasattr(ruta, "routes"):
            yield from _recorrer(ruta, prefijo)


def rutas_de(aplicacion: FastAPI, *, incluir_excluidos: bool = False) -> list[RutaRegistrada]:
    """Todas las rutas registradas, una por combinación de ruta y método."""
    registradas: list[RutaRegistrada] = []
    for camino, ruta in _recorrer(aplicacion):
        if not incluir_excluidos and camino.startswith(PREFIJOS_EXCLUIDOS):
            continue
        permiso = _permiso_de(ruta)
        for metodo in sorted(m for m in ruta.methods if m in METODOS):
            registradas.append(RutaRegistrada(metodo=metodo, camino=camino, permiso=permiso))
    return sorted(registradas, key=lambda r: (r.camino, r.metodo))


def caminos_del_esquema(aplicacion: FastAPI) -> list[tuple[str, set[str]]]:
    """``(camino, métodos)`` desde el esquema OpenAPI, sin los prefijos excluidos."""
    esquema = aplicacion.openapi()
    caminos = []
    for camino, operaciones in esquema.get("paths", {}).items():
        if camino.startswith(PREFIJOS_EXCLUIDOS):
            continue
        metodos = {m.upper() for m in operaciones if m.upper() in METODOS}
        if metodos:
            caminos.append((camino, metodos))
    return sorted(caminos)


def concretar(camino: str) -> str:
    """Sustituye los parámetros de ruta por un identificador plausible."""
    partes = [
        "1" if parte.startswith("{") and parte.endswith("}") else parte
        for parte in camino.split("/")
    ]
    return "/".join(partes)
