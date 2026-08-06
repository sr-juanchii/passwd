# Registro de cambios

Todos los cambios notables de este proyecto se documentan aquí.

El formato sigue [Keep a Changelog](https://keepachangelog.com/es/1.1.0/) y el proyecto adopta
[Versionado Semántico](https://semver.org/lang/es/) (`MAYOR.MENOR.PARCHE`). La política de
versionado y cómo cada *pull request* declara su incremento están en
[`docs/versionado.md`](docs/versionado.md).

La versión en curso vive en `app/__init__.py` (`__version__`) y se refleja en `pyproject.toml`;
`GET /healthz` y la metadata de la API la exponen.

## [Sin publicar]

### Añadido

- **Manual de uso, funciones y procedimientos** ([`docs/manual-operativo.md`](docs/manual-operativo.md)):
  documento único, apto para aprobación formal, que cubre **todas** las funciones del
  sistema —interfaz web, API JSON, API REST, CLI y avisos— con **52 capturas de pantalla**
  nuevas, la **configuración óptima** de cada parámetro para producción (MySQL 8.4 + nginx
  con TLS + frontend Next.js + backend FastAPI), los procedimientos operativos (alta y baja
  de usuarios, rotación, respaldo y prueba de restauración, respuesta a exfiltración,
  rotación de la clave de cifrado, actualización de versión) y una lista de verificación
  previa a la puesta en producción. Incluye control documental con campos de revisión y
  aprobación, mapa función → interfaz → rol mínimo, e índice de capturas.
  Las capturas se tomaron sobre el **stack real de producción** con datos ficticios.
  Sustituye a `docs/manual-uso-ilustrado.md`, que se elimina.

- **MFA de respaldo por OTP al correo**: un usuario sin acceso a su aplicación
  autenticadora ni a sus códigos de recuperación puede pedir un código de un solo uso
  a su buzón registrado (`POST /mfa/otp-correo` y su equivalente JSON) y completar con
  él el segundo factor. Solo alcanzable desde la etapa `mfa_pendiente` —exige la
  contraseña válida primero, **no es un punto de entrada**—, con código de 8 dígitos,
  un solo uso, caducidad de 10 min, tope de 5 intentos, límite de tasa por cuenta y
  por IP, CSRF, solo hash SHA-256 en base de datos, y auditoría más alerta al equipo
  de seguridad en cada uso. La normalización del código vive en **una sola función**,
  aplicando la lección del hallazgo de reutilización de TOTP. Nueva tabla
  `codigos_otp_correo` (migración `0008`, no toca datos existentes).
  **Nota:** es un factor más débil que el TOTP —quien controle el buzón y conozca la
  contraseña entra— y añade el proveedor de correo a la cadena de confianza. Se
  desactiva con `PASSWD_EMAIL_OTP_ENABLED=false` (también en caliente) sin afectar al
  resto del MFA. El orden de preferencia recomendado sigue siendo TOTP → códigos de
  recuperación → OTP por correo.
- **Restablecimiento administrativo con envío automático**: al restablecer la
  contraseña de una cuenta, la temporal se envía **directamente al correo del
  titular** y ya no se muestra al administrador, eliminando el paso manual de
  copiarla y transmitirla por un canal sin auditoría. La respuesta confirma el envío
  con el buzón **enmascarado**. La acción sigue siendo **exclusiva de administradores**
  (`usuarios.gestionar`), verificado con pruebas para operador, auditor y analista. Si
  SMTP falla, la contraseña se devuelve al administrador como contingencia —el
  restablecimiento ya ocurrió y la cuenta quedaría inaccesible— y la bitácora registra
  ese caso de forma distinguible.
- **Sistema dinámico de notificaciones por matriz de permisos** (`app/avisos.py`).
  Los destinatarios se resuelven **en tiempo de ejecución** con
  `access.usuarios_con_acceso_a_activo`, que reutiliza como predicado las mismas
  funciones que autorizan de verdad (`puede_ver_activo` / `puede_revelar_en_activo`):
  no duplica la lógica, así que los destinatarios no pueden divergir de la
  autorización real. Eventos cubiertos:
  - **Actividad y permisos propios**: aviso de inicio de sesión (IP, cliente, rol),
    de actividad sensible (revelado/copia de credenciales) y de todo cambio en los
    permisos propios (concesión, revocación y cambio de rol).
  - **Credenciales compartidas**: al actualizar una credencial se identifica
    automáticamente a los demás usuarios con acceso a ese activo y se les avisa de la
    modificación, excluyendo al autor.
  - **Caducidad de rotación**: aviso preventivo a quienes pueden rotar la contraseña
    cuando se acerca el cambio obligatorio, con nuevo comando programable
    `python -m app.cli avisar-rotacion` (y `--simular` para revisar el alcance sin
    enviar). Distingue «próxima» de «VENCIDA».

  Los avisos comunican **el hecho, nunca el secreto**: ningún correo sobre una
  credencial incluye la contraseña, ni la anterior ni la nueva, ni pistas sobre ellas
  — quien la necesite la revela en la aplicación, donde el permiso se comprueba, se
  limita por tasa y queda en la bitácora. Verificado de forma explícita contra el
  texto real de los correos. Las dos únicas excepciones son el OTP del MFA y la
  contraseña temporal de un reset: ambas de un solo uso, con cambio forzado o
  caducidad corta, y dirigidas al buzón de su propio titular.
  Los envíos a varios destinatarios salen **como mensajes independientes**: agrupar
  las direcciones en un `To:` revelaría quién más tiene acceso al activo.
  Nuevas variables: `PASSWD_NOTIFY_USERS_ENABLED` (defecto `true`, dentro de
  `PASSWD_NOTIFY_ENABLED`), `PASSWD_ROTATION_WARNING_DAYS` (14),
  `PASSWD_EMAIL_OTP_ENABLED` (true) y `PASSWD_EMAIL_OTP_TTL_MINUTES` (10), todas
  editables en caliente.
- Nuevo documento
  [`docs/notificaciones-y-mfa-correo.md`](docs/notificaciones-y-mfa-correo.md) y
  `tests/test_avisos_dinamicos.py` (25 pruebas).

### Cambiado

- **Comportamiento del correo al actualizar**: en despliegues que ya tuvieran
  `PASSWD_NOTIFY_ENABLED=true`, los **usuarios finales** empezarán a recibir avisos
  (inicios de sesión, cambios de permisos, credenciales compartidas), no solo la lista
  fija `PASSWD_NOTIFY_TO`. Es el comportamiento solicitado; para conservar el anterior,
  `PASSWD_NOTIFY_USERS_ENABLED=false`. Conviene avisar a los usuarios antes de
  activarlo para que no confundan los avisos legítimos con phishing.
- Los avisos de actividad sensible se **deduplican por sesión y categoría** (un aviso
  por tipo de actividad y sesión) en lugar de uno por acción: decenas de correos harían
  que el usuario los filtrara y se perdería la señal. La bitácora conserva el registro
  completo acción por acción. La deduplicación se apoya en el limitador de tasa, así
  que con más de un worker conviene `PASSWD_RATE_LIMIT_BACKEND=bd`.

### Seguridad

- **Corregida la reutilización del código TOTP de enrolamiento** (severidad alta;
  OWASP A07 — fallos de identificación y autenticación; RFC 6238 §5.2). La
  protección anti-reutilización (`Usuario.ultimo_otp_usado`) quedaba anulada por una
  **asimetría de normalización**: el enrolamiento guardaba el código con
  `codigo.strip()`, conservando los espacios internos, mientras que la verificación
  comparaba con `strip().replace(" ", "")`. Como las aplicaciones autenticadoras
  muestran los códigos agrupados (`599 790`), al enrolar con esa forma se almacenaba
  `"599 790"` y la comparación posterior contra `"599790"` no coincidía: **el mismo
  código de 6 dígitos volvía a ser aceptado** durante toda su ventana de validez
  (hasta ~90 s con `valid_window=1`), que es exactamente el ataque de *replay* con un
  proxy de intercepción. Afectaba a los dos flujos (web Jinja y API JSON del
  frontend). Segunda cara del mismo defecto: la columna es `String(8)`, así que una
  forma sin normalizar (`1 2 3 4 5 6`) se truncaba en MySQL no estricto —rompiendo
  también la comparación— o fallaba en modo estricto. Se introduce
  `mfa.normalizar_codigo()` como **única** forma canónica y los seis puntos que tocan
  un código TOTP (validación, y registro y comparación en enrolamiento, verificación
  y recuperación) pasan por ella, de modo que la asimetría no puede reaparecer al
  editar un solo sitio.

- **Reducción de la exposición del código fuente en producción** (OWASP A05 — configuración de
  seguridad incorrecta). Nuevo documento
  [`docs/proteccion-codigo-fuente.md`](docs/proteccion-codigo-fuente.md) que delimita qué se puede
  bloquear de verdad y qué no: **no es posible impedir la lectura del bundle desde las herramientas
  de desarrollador** —el navegador debe ejecutar ese código, y `view-source`, `curl` o un proxy de
  intercepción eluden cualquier truco anti-DevTools— por lo que la protección se centra en no
  entregar información que la aplicación no necesita:
  - **Mapas de origen**: `productionBrowserSourceMaps: false` fijado de forma explícita en
    `next.config.ts`, y nginx responde `404` a `*.map`, `*.ts` y `*.tsx` como segunda barrera, para
    que un build mal configurado no publique el TypeScript original con nombres y comentarios.
  - **Metadatos de repositorio y entorno**: nginx responde `404` a las rutas que empiezan por punto
    (`/.git/`, `/.env`, `/.svn/`, archivos de editor), preservando `/.well-known/` para ACME. Un
    `/.git/` accesible es la fuga completa de código fuente más habitual en despliegues reales.
  - **Trazas de pila**: el error boundary de la aplicación ya no vuelca el objeto `Error` a la
    consola en producción (solo en desarrollo); la interfaz muestra el `digest` de Next, suficiente
    para correlacionar con el log del servidor.
  - **Huella tecnológica**: `poweredByHeader: false` en Next y `proxy_hide_header X-Powered-By` en
    ambas plantillas de nginx.
  - **Indexación**: cabecera `X-Robots-Tag: noindex, nofollow, noarchive, nosnippet` en las páginas
    del frontend, para que una aplicación interna no quede en cachés públicas de terceros.

### Añadido

- **Control automático de exposición del build del frontend**:
  [`scripts/verificar-build-frontend.sh`](scripts/verificar-build-frontend.sh), integrado en el CI
  tras `next build`. Falla el pipeline si en `.next/static` o `public/` aparecen mapas de origen,
  patrones de secretos de servidor (`PASSWD_SECRET_KEY`, `PASSWD_ENCRYPTION_KEY`, claves privadas…)
  o rutas absolutas de la máquina de compilación.
- **Batería exhaustiva contra el salto del MFA**: `tests/test_bypass_mfa.py` (20
  pruebas). El barrido principal **enumera las rutas registradas en la aplicación**
  —vía esquema OpenAPI— y ataca las 113 con todos sus métodos desde una sesión
  detenida en cada una de las tres etapas previas a `activa`, de modo que un endpoint
  nuevo que olvide su dependencia de sesión rompe la suite en lugar de pasar
  inadvertido. Un 422 **no** se acepta como rechazo válido (significaría que la
  petición superó la autenticación y llegó a validar el cuerpo). Incluye pruebas
  dirigidas de re-enrolamiento, fuga del secreto TOTP, replay de TOTP y de códigos de
  recuperación, fuerza bruta con bloqueo de cuenta, fijación de sesión, falsificación
  de cookie, CSRF cruzado, recuperación de contraseña como puerta trasera y emisión
  de tokens de API desde una sesión pre-MFA. Dos pruebas vigilan a la propia suite
  para que no pase en vacío (cobertura mínima de rutas y ausencia de exenciones
  fantasma). Nuevo documento
  [`docs/resistencia-bypass-mfa.md`](docs/resistencia-bypass-mfa.md) con el modelo de
  amenaza, los vectores auditados y los límites del TOTP frente a WebAuthn/FIDO2.

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
