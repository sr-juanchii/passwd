# Registro de cambios

Todos los cambios notables de este proyecto se documentan aquí.

El formato sigue [Keep a Changelog](https://keepachangelog.com/es/1.1.0/) y el proyecto adopta
[Versionado Semántico](https://semver.org/lang/es/) (`MAYOR.MENOR.PARCHE`). La política de
versionado y cómo cada *pull request* declara su incremento están en
[`docs/versionado.md`](docs/versionado.md).

La versión en curso vive en `app/__init__.py` (`__version__`) y se refleja en `pyproject.toml`;
`GET /healthz` y la metadata de la API la exponen.

## [Sin publicar]

_Nada pendiente de publicar._

<!--
Al abrir un PR, añada aquí sus entradas bajo la categoría correspondiente
(Añadido / Cambiado / Corregido / Seguridad / Eliminado / Obsoleto). Al liberar
una versión, mueva este bloque a una nueva sección `## [X.Y.Z] - AAAA-MM-DD` y
actualice `app/__init__.py` + `pyproject.toml`.
-->

## [1.0.0] - 2026-07-15

Primera versión estable. Establece la línea base sobre la que se versionan los cambios futuros.

### Añadido

- **Inventario relacional** de servidores físicos, hipervisores y máquinas virtuales, con
  credenciales por activo (usuario, servicio, puerto), notas cifradas por activo, especificaciones
  de VM (RAM, CPU, almacenamiento) y estados de ciclo de vida.
- **Vault personal** por usuario: contraseñas de servicios, aplicaciones o cuentas propias,
  privadas de su dueño (ni el administrador accede a su contenido), con revelado/copiado auditado.
- **Autenticación y sesión**: contraseña (Argon2id) + **MFA TOTP obligatorio**, códigos de
  recuperación de un solo uso, sesiones server-side revocables con doble expiración, y
  **auto-recuperación de contraseña** por el propio usuario mediante su segundo factor.
- **Control de acceso** por roles (admin, operador, auditor, analista) y **concesiones por objeto**
  con nivel y caducidad.
- **Auditoría** de solo anexado, **encadenada por hash** (evidencia de manipulación), con
  exportación y verificación de la cadena.
- **API REST** `/api/v1` de solo lectura con tokens Bearer de **alcance** y **caducidad**;
  doble interfaz web (Jinja) y JSON (`/api/web`) que comparten el modelo de seguridad.
- **Importación/exportación CSV** del inventario (con plantilla) para migración entre versiones.
- **Frontend Next.js** (App Router, React 19, shadcn/ui) con sistema de diseño «tinta y estado»,
  modo claro/oscuro y flujo de auto-recuperación.
- **Operación**: migraciones Alembic, imagen Docker multi-etapa, overlays de Compose (nginx,
  frontend, MySQL, certbot, respaldos, secretos), respaldos cifrados (scrypt) y CLI de
  administración (recifrar, exportar, verificar auditoría).

### Seguridad

- Cifrado en reposo (Fernet/MultiFernet con rotación de clave), claves fuera del volumen en modo
  estricto y soporte de *secrets* por fichero.
- Rate-limiting compartido, bloqueo de cuenta, blocklist amplia de contraseñas, endurecimiento de
  nginx (CSP, zonas de límite) y del respaldo cifrado.
- Cadena de suministro en CI: `ruff`, `bandit`, `pip-audit`, `gitleaks` y Trivy, con cobertura
  mínima del 70 % y pruebas de extremo a extremo sobre SQLite y MySQL.

El detalle del alcance por fases está en [`docs/hoja-de-ruta.md`](docs/hoja-de-ruta.md).

[Sin publicar]: https://github.com/sr-juanchii/passwd/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/sr-juanchii/passwd/releases/tag/v1.0.0
