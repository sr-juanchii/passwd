<!--
Antes de abrir el PR, ejecute localmente las comprobaciones de la guía de
desarrollo (§4) y, en frontend/, lint + typecheck + test + build.
-->

## Resumen

<!-- Qué hace este PR y por qué, en 1-3 frases. -->

## Tipo de cambio (SemVer)

Marque **uno**. Criterios en [`docs/versionado.md`](../docs/versionado.md).

- [ ] **MAYOR** — cambio incompatible (rompe API `/api/v1`, datos o configuración obligatoria).
- [ ] **MENOR** — nueva funcionalidad retrocompatible (endpoint, página, tabla u opción nueva).
- [ ] **PARCHE / fix** — corrección o mejora sin superficie nueva ni rotura.

**Versión objetivo:** `X.Y.Z`  <!-- p. ej. 1.1.0 para una MENOR; 1.0.1 para un PARCHE -->

## Cambios

<!-- Lista de los cambios relevantes. -->

## Verificación

- [ ] `ruff`, `bandit`, `pip-audit` y `pytest` (cobertura ≥ 70 %) en verde.
- [ ] Frontend (si aplica): `pnpm lint`, `pnpm typecheck`, `pnpm test`, `pnpm build`.
- [ ] Añadí entradas en `CHANGELOG.md` bajo **`## [Sin publicar]`**.
- [ ] Si este PR **libera** una versión: actualicé `app/__init__.py` + `pyproject.toml`, moví el
      bloque «Sin publicar» a `## [X.Y.Z] - AAAA-MM-DD` y preparé la etiqueta `vX.Y.Z`.
