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
3. **Fusione el PR en `main`.** El flujo [`publicar.yml`](../.github/workflows/publicar.yml) detecta el
   cambio de `app/__init__.py`, crea la etiqueta `vX.Y.Z` sobre el commit de `main` y publica la
   Release de GitHub con las notas de esa versión tomadas de `CHANGELOG.md`. Es idempotente (si la
   etiqueta existe no hace nada) y puede relanzarse a mano desde la pestaña *Actions*. Como
   alternativa manual: `git tag -a vX.Y.Z -m "Versión X.Y.Z" && git push origin vX.Y.Z`.

`GET /healthz` y la metadata de la API OpenAPI exponen `__version__`, de modo que la versión
desplegada es siempre verificable en caliente.

## Pre-releases

Cuando el alcance de una versión ya está terminado pero todavía no se quiere publicar —porque
faltan la documentación, las notas de versión o simplemente pruebas funcionales—, se libera un
**pre-release**: `X.Y.Z-rc.N`, forma de SemVer 2.0.0 §9 que además es válida como PEP 440.

| | Versión final | Pre-release |
|---|---|---|
| Ejemplo | `1.3.0` | `1.3.0-rc.1` |
| `__version__` | `1.3.0` | `1.3.0-rc.1` |
| Notas | sección `## [1.3.0]` del CHANGELOG | bloque `## [Sin publicar]` |
| Dónde vive | `main` | la rama de trabajo |
| Quién lo publica | [`publicar.yml`](../.github/workflows/publicar.yml) al llegar a `main` | [`prelanzamiento.yml`](../.github/workflows/prelanzamiento.yml) al empujar la etiqueta |

Tres reglas que conviene no saltarse:

1. **`__version__` lleva el sufijo.** Es lo que hace útil al pre-release: `GET /healthz` responde
   `1.3.0-rc.1` y quien prueba sabe exactamente qué está corriendo. Dejarlo en la versión anterior
   convertiría cualquier informe de fallo en una adivinanza.
2. **El pre-release no llega a `main`.** Se etiqueta sobre la rama de trabajo. Si aun así llegara,
   `publicar.yml` lo detecta y se aparta en vez de romperse, pero no es el camino previsto.
3. **No se abre una sección propia en el CHANGELOG.** Un pre-release publica cambios que todavía
   no están cerrados; darles sección propia obligaría a reescribirla al liberar la versión final.

Publicarlo, una vez la rama tiene el commit que sube `__version__`, de una de dos formas:

- **Desde la interfaz de GitHub:** *Releases → Draft a new release*, etiqueta nueva `vX.Y.Z-rc.N`
  sobre la rama de trabajo, marcar *Set as a pre-release* y publicar. Las notas pueden dejarse en
  blanco: el flujo las escribe.
- **Desde la línea de órdenes:**

  ```bash
  git tag -a v1.4.0-rc.1 -m "Pre-release 1.4.0-rc.1 para pruebas funcionales"
  ```

  ```bash
  git push origin v1.4.0-rc.1
  ```

El flujo comprueba que la etiqueta coincide con `__version__` —una etiqueta mal escrita publicaría
un artefacto que miente sobre su contenido—, compila los paquetes del agente para amd64 y arm64
([`binarios-agente.yml`](../.github/workflows/binarios-agente.yml)) y **crea o completa** la
Release: si ya existe porque se creó desde la interfaz, le pone las notas del CHANGELOG (sustituyen
a las escritas a mano), la marca de *pre-release* y los paquetes con su `SHA256SUMS`. Hasta la
1.4.0 se apartaba al encontrarla, y por eso la de `v1.3.0-rc.1` quedó sin notas. Si algo falla, se
repite desde *Actions → Publicar pre-release → Run workflow* con la etiqueta, sin borrarla. Las
versiones finales reciben los mismos paquetes desde `publicar.yml`. Los
siguientes son `-rc.2`, `-rc.3`…

Dos reglas más, aprendidas en la 1.4.0:

- **Cree la Release solo cuando el commit de versión esté en la rama y su CI en verde**, y compruebe
  antes que el último commit de la rama es ese. Una etiqueta creada un minuto antes apunta al commit
  anterior: su `__version__` no coincide y el flujo la rechaza. Así le pasó a `v1.4.0-rc.1`.
- **Una etiqueta publicada no se reutiliza.** Si apunta al commit equivocado, no se borra y se
  vuelve a crear: se publica el siguiente `-rc.N`. Así, lo que alguien ya descargó con ese nombre
  no cambia por debajo. Al liberar la versión final se sigue el procedimiento de arriba:
`__version__` pasa a `X.Y.Z` y el bloque «Sin publicar» se convierte en su sección.

## Relación con la hoja de ruta

[`hoja-de-ruta.md`](hoja-de-ruta.md) describe **qué** se construye y en qué fases; este documento y
`CHANGELOG.md` registran **cuándo** se publicó y bajo qué versión. La v1.0.0 recoge las fases 0–7,
las funcionalidades de preproducción, el rediseño del frontend y la auto-recuperación. La v1.2.0
recoge la fase 8 (sesión, segundo factor elegible y configuración coherente). El plan de la
siguiente versión mayor está en [`plan-v2.0.md`](plan-v2.0.md).
