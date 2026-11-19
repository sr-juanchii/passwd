# Reglas del proyecto

Este archivo lo leen los asistentes de IA al empezar a trabajar en el repositorio. Las
convenciones completas están en [`docs/guia-desarrollo.md`](docs/guia-desarrollo.md) §7.

## Nombres de rama

**Toda rama debe llamarse de forma que su nombre diga qué contiene.** No se aceptan nombres
autogenerados ni arbitrarios (`claude/festive-meitner-r3yw3q`, `parche-2`, `pruebas`): quien mire
la lista de ramas tiene que entender para qué es cada una sin abrirla.

Formato: `prefijo/descripcion-en-castellano`, en minúsculas y separando con guiones.

| Prefijo | Para qué | Ejemplo |
|---|---|---|
| `release/` | Preparar y publicar una versión | `release/v1.3.0` |
| `feature/` | Funcionalidad nueva | `feature/gobernanza-rotacion` |
| `fix/` | Corrección de un defecto | `fix/exportacion-activos-restringidos` |
| `docs/` | Solo documentación | `docs/notas-version-1.3.0` |
| `chore/` | Mantenimiento: CI, dependencias, limpieza | `chore/pruebas-navegador-en-ci` |

Si una sesión arranca en una rama con nombre autogenerado, **renómbrela antes de empujar nada**.

Las etiquetas siguen su propia política, en [`docs/versionado.md`](docs/versionado.md): `vX.Y.Z`
para una versión publicada y `vX.Y.Z-rc.N` para un pre-release.
