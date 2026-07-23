# Versionado

El proyecto adopta **Versionado Semántico** ([SemVer 2.0.0](https://semver.org/lang/es/)):
`MAYOR.MENOR.PARCHE`. La versión estable inicial es **1.0.0**.

## Qué incrementa cada número

| Incremento | Cuándo | Ejemplos en este proyecto |
|---|---|---|
| **MAYOR** (`X.0.0`) | Cambios **incompatibles** o un conjunto grande de funcionalidad que redefine el sistema. Rompe integraciones, el contrato de la API `/api/v1`, el esquema de datos de forma no migrable, o la configuración obligatoria. | Rediseño del modelo de datos; cambio incompatible del contrato REST; eliminación de un endpoint. |
| **MENOR** (`x.Y.0`) | **Nueva funcionalidad retrocompatible**. No rompe integraciones ni datos existentes (las migraciones son aditivas o Alembic las cubre). | Vault personal; auto-recuperación de contraseña; alcance/caducidad de tokens; nuevas páginas del frontend. |
| **PARCHE** (`x.y.Z`) | **Correcciones retrocompatibles**: *bug fixes*, seguridad sin cambio de contrato, ajustes de documentación o de CI, mejoras internas sin superficie nueva. | Arreglo de un fallo de CI; corrección de un cálculo; endurecimiento sin API nueva; parche de una vulnerabilidad de dependencia. |

Regla práctica para decidir «¿versión distinta o fix?» según **la cantidad y naturaleza** del
cambio del PR:

- ¿El PR **rompe** algo que un consumidor externo ya usaba (API, datos, configuración)? → **MAYOR**.
- ¿El PR **añade** capacidad nueva sin romper lo anterior? → **MENOR**.
- ¿El PR solo **arregla/afina** lo existente? → **PARCHE** (un «fix»).

Ante la duda entre MENOR y PARCHE, pesa la superficie nueva: si aparece un endpoint, una página, una
tabla o una opción de configuración, es MENOR; si no, es PARCHE.

## Cómo lo declara cada pull request

1. En la plantilla de PR (`.github/pull_request_template.md`) marque el **tipo de cambio**
   (MAYOR / MENOR / PARCHE) y la **versión objetivo**.
2. Añada sus entradas al bloque **`## [Sin publicar]`** de [`CHANGELOG.md`](../CHANGELOG.md), bajo la
   categoría que corresponda: *Añadido, Cambiado, Corregido, Seguridad, Eliminado, Obsoleto*.
3. La versión **no** se incrementa en cada PR: se acumulan cambios en «Sin publicar» y se **libera**
   cuando se decide publicar (ver abajo). Un PR puede, si así se acuerda, liberar directamente.

## Cómo se libera una versión

Al publicar `X.Y.Z`:

1. Actualice **`app/__init__.py`** (`__version__`) — es la **fuente de verdad**; `pyproject.toml`
   debe llevar el mismo valor (una prueba lo verifica, ver `tests/test_version.py`).
2. En `CHANGELOG.md`, mueva el contenido de `## [Sin publicar]` a una nueva sección
   `## [X.Y.Z] - AAAA-MM-DD` y añada los enlaces de comparación al pie.
3. Etiquete el commit de publicación como `vX.Y.Z` (`git tag vX.Y.Z`).

`GET /healthz` y la metadata de la API OpenAPI exponen `__version__`, de modo que la versión
desplegada es siempre verificable en caliente.

## Relación con la hoja de ruta

[`hoja-de-ruta.md`](hoja-de-ruta.md) describe **qué** se construye y en qué fases; este documento y
`CHANGELOG.md` registran **cuándo** se publicó y bajo qué versión. La v1.0.0 recoge las fases 0–7,
las funcionalidades de preproducción, el rediseño del frontend y la auto-recuperación.
