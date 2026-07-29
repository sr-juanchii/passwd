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

## [1.1.0] - 2026-07-29

Amplía el inventario a toda la infraestructura, añade control de acceso restrictivo por objeto
y una consola de configuración en caliente; incluye una corrección de despliegue.

### Añadido

- **Módulo de configuración en tiempo de ejecución** (solo administradores, nuevo permiso
  `configuracion.gestionar`): una pantalla de **Configuración** (y su API `/api/web/configuracion`)
  permite ajustar en caliente —sin reiniciar ni editar el `.env`— los parámetros operativos de
  sesión y comportamiento, política de cuentas, límites de tasa (anti-abuso), rotación/auditoría y
  notificaciones por correo/SMTP. Los cambios se guardan en la tabla `configuracion`, **anulan** la
  variable de entorno correspondiente, se aplican al instante, se propagan a otras instancias
  (refresco periódico) y quedan **auditados** (`configuracion_cambiada`/`_restablecida`). La
  contraseña SMTP se guarda **cifrada** y nunca se devuelve en claro; incluye **envío de correo de
  prueba** (`correo_prueba_enviado`). Las claves criptográficas, la base de datos, el arranque y las
  defensas de borde siguen siendo exclusivas de entorno (se muestran como solo lectura). Migración
  Alembic `0007`.
- **Restricción de activos a administradores**: un administrador (nuevo permiso
  `inventario.restringir`) puede marcar un servidor físico, hipervisor o dispositivo de red
  como *restringido*. El operador deja de verlo por completo (404, fuera de listados,
  búsqueda y export); el auditor sí lo ve pero nunca revela contraseñas; el analista solo con
  concesión explícita (que prevalece sobre la restricción). Las máquinas virtuales heredan la
  restricción de su hipervisor. Aplicado en ambas interfaces (checkbox/switch solo para
  administradores, badge «Restringido»), export/import CSV (columna `restringido`, honrada
  solo si quien importa es admin), respaldo cifrado y auditoría (`activo_restriccion_cambiada`).
  Migración Alembic `0006` (columna aditiva `restringido`).
- **Dispositivos de red** como tercer activo de nivel superior del inventario: switches,
  routers, firewalls, puntos de acceso, balanceadores y otros, con tipo, marca/modelo,
  firmware, IP de gestión, ubicación, puertos, número de serie, garantía, proveedor, estado,
  etiquetas y notas cifradas. Cada dispositivo custodia sus **credenciales de gestión** con
  los mismos controles del resto del inventario: cifrado en reposo, RBAC, **concesiones por
  objeto a analistas** (404 por defecto), revelado/copiado auditado con límite
  anti-exfiltración y historial de rotación.
- Cobertura completa del nuevo activo en ambas interfaces (web Jinja y frontend Next.js),
  búsqueda global, importación/exportación CSV (columnas `tipo_dispositivo` y `puertos`,
  `activo_tipo=dispositivo` en credenciales, round-trip), plantilla CSV, respaldo cifrado,
  API REST `GET /api/v1/inventario` (colección `dispositivos_red`) y métrica de conteo en el
  panel.
- Migración Alembic `0005` (nueva tabla `dispositivos_red`; cuarta clave foránea con CHECK y
  UNIQUE ampliados en `credenciales` y `concesiones_acceso`).

### Corregido

- **Error 500 al guardar la contraseña de un dispositivo de red** en instalaciones existentes
  actualizadas por despliegue (`git pull` + `docker compose up --build`, que arranca con
  `init_db()` pero no ejecuta Alembic). En una BD anterior a los dispositivos, la columna
  `dispositivo_red_id` se añadía de forma aditiva, pero la restricción `CHECK` «un activo» de
  `credenciales`/`concesiones_acceso` (y la `UNIQUE` de concesiones) quedaba obsoleta y rechazaba
  el registro. `schema_sync.reconciliar_restricciones()` (invocada por `init_db`) las pone al día
  de forma idempotente y segura al arrancar (SQLite: reconstrucción de tabla; MySQL/MariaDB:
  `ALTER TABLE`), sin abortar el arranque si no puede.

### Seguridad

- **Dependencias del frontend actualizadas** para resolver vulnerabilidades ALTAS detectadas por
  el escaneo de cadena de suministro (Trivy): `next` a `16.2.11` (CVE-2026-64641 denegación de
  servicio, CVE-2026-64642 elusión de autenticación, CVE-2026-64645 y CVE-2026-64649 SSRF) y
  `postcss` forzado a `^8.5.18` mediante `pnpm.overrides` (CVE-2026-45623 y GHSA-r28c-9q8g-f849).

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

[Sin publicar]: https://github.com/sr-juanchii/passwd/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/sr-juanchii/passwd/releases/tag/v1.1.0
[1.0.0]: https://github.com/sr-juanchii/passwd/releases/tag/v1.0.0
