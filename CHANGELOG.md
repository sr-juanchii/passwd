# Registro de cambios

Todos los cambios notables de este proyecto se documentan aquí.

El formato sigue [Keep a Changelog](https://keepachangelog.com/es/1.1.0/) y el proyecto adopta
[Versionado Semántico](https://semver.org/lang/es/) (`MAYOR.MENOR.PARCHE`). La política de
versionado y cómo cada *pull request* declara su incremento están en
[`docs/versionado.md`](docs/versionado.md).

La versión en curso vive en `app/__init__.py` (`__version__`) y se refleja en `pyproject.toml`;
`GET /healthz` y la metadata de la API la exponen.

## [Sin publicar]

**Agentes de rotación para Linux.** Versión 1.4.0, MENOR: la rotación que dos personas autorizan
en la 1.3.0 la puede aplicar ahora un agente instalado en el servidor, que cambia la contraseña de
la cuenta local, comprueba que la nueva funciona y, si no, deja la anterior. Todo está **apagado
por omisión**: hasta que se activa, el sistema se comporta como la 1.3.0. Alcance en
[`docs/plan-rotacion-agentes.md`](docs/plan-rotacion-agentes.md) §8.2.

**Al actualizar desde la 1.3.x** (detalle en [`docs/notas-version-1.4.0.md`](docs/notas-version-1.4.0.md)):

- Aplique la migración `0011` (aditiva); en contenedor las tablas se crean solas al arrancar.
- Nada cambia hasta activar `PASSWD_AGENTES_ENABLED`, y activarlo tampoco cambia ninguna
  credencial: cada una sigue «a mano» hasta que alguien elige que la rote su agente.
- Para instalar un agente, siga [`docs/guia-instalacion-agente-linux.md`](docs/guia-instalacion-agente-linux.md)
  con el paquete de su arquitectura publicado en la Release.

### Añadido

- **Agente de rotación para Linux** (`agente/`, Go): binario estático que corre como un usuario
  **sin privilegios** y solo ejecuta rotaciones que ya autorizaron dos administradores. Aplica en
  **dos fases** con un journal cifrado: apunta lo que va a hacer antes de tocar la cuenta, aplica,
  **verifica la nueva con PAM** y, si no autentica, **restaura la anterior**. Tras un reinicio a
  mitad, el journal le dice qué pasó y lo informa.
- **Helper root de acción única**, sin sudo ni setuid: systemd lo arranca por cada conexión a un
  socket que solo el usuario del agente puede abrir, **sin red**, y solo toca las cuentas de una
  lista que es de root y que existan: **nunca crea una cuenta**. Antes de aplicar comprueba que la
  contraseña del inventario sigue valiendo en el servidor.
- **Instalador** `instalar.sh` que no toca nada hasta que pasan todas sus comprobaciones (SHA-256
  de los binarios incluido), con unidades systemd endurecidas y la salida de red del agente
  limitada al backend. **Paquetes del agente** para amd64 y arm64 en cada Release.
- **API `/api/agent`** con identidad de máquina: enrolamiento de un solo uso, identidad de vida
  corta renovada en cada latido, trabajo cifrado en reposo y **sellado a la clave X25519 del
  agente** al entregarlo, un resultado por trabajo, límites de tasa y topes de tamaño. Apagada,
  todo el prefijo responde 404.
- **Vía de rotación por credencial** («Rotar con el agente» / «Rotar a mano»). Con la del agente,
  **autorizar despacha**; si no se puede, la autorización se mantiene y se puede registrar a mano.
- **Rotación «sin confirmar»**: si el agente recoge el trabajo y calla, la credencial queda
  bloqueada hasta que un administrador, reautenticándose, diga qué pasó.
- **Panel**: cobertura del agente en la ficha de cada servidor, hipervisor y VM (alta y
  reinstalación con reautenticación, token de instalación visible una sola vez), página
  `/agentes`, métricas de agentes en `/metricas` y alerta de agente sin contacto.
- Permisos `agentes.ver` y `agentes.gestionar`, y diez ajustes en el grupo «Agentes de rotación».
- Migración `0011`: tablas `agentes`, `trabajos_rotacion` y `telemetria_agente`, con un único agente
  vigente por activo y un único trabajo activo por agente **impuestos por la base de datos**.
- Documentación: contrato normativo del agente, referencia de `/api/agent`, arquitectura de
  agentes y guía de instalación.

### Cambiado

- El respaldo cifrado incluye los agentes (revocados, sin identidad válida) y **nunca** los
  trabajos: un restore no resucita un trabajo con secretos y ventana vencida.
- Los flujos de publicación **completan** una Release creada desde la interfaz de GitHub en vez
  de apartarse (la de `v1.3.0-rc.1` quedó sin notas por eso) y adjuntan los paquetes del agente.
- La imagen de nginx sube de `1.27-alpine` a **`1.31.10-alpine`** en los dos despliegues con
  proxy (`docker-compose.nginx.yml` y `docker-compose.frontend.yml`). La subida llegó primero solo
  al primero; ahora ambos usan la misma versión. Las plantillas de `infrastructure/nginx/` no
  cambian.

### Corregido

- **Las fechas del panel salían con el desfase de la zona horaria**: el backend envía UTC sin zona y
  el navegador lo leía como hora local (cuatro horas de más en Caracas). Una prueba impide que
  vuelva.
- El diálogo de autorizar ya no se cierra cuando la petición falla.
- Una prueba de TOTP fallaba de forma intermitente si un límite de 30 s caía en mitad de ella.

### Seguridad

- **Pruebas de aceptación** con la trazabilidad de cada criterio a su prueba: `/api/v1` congelada
  en rutas y claves, y un volcado entero de la base tras una rotación por agente sin ninguna
  contraseña en claro.
- **Prueba de sistema en cada push**: la CI instala el agente con systemd en el runner y comprueba
  que una rotación autorizada cambia la contraseña de una **cuenta Linux real**; y una prueba de
  integración como root con PAM y `chpasswd` de verdad.

## [1.3.0] - 2026-11-20

**Gobernanza de rotación y bitácora firmada.** Versión MENOR: cambiar la contraseña de una
credencial del inventario deja de ser una edición y pasa a ser un acto gobernado por dos personas,
con motivo, autorización y rastro permanente. Corresponde a la **Fase 9** (parcial) de la
[hoja de ruta](docs/hoja-de-ruta.md).

**Al actualizar desde la 1.2.x** (detalle en [`docs/notas-version-1.3.0.md`](docs/notas-version-1.3.0.md)):

- **Defina `PASSWD_AUDIT_KEY`** por entorno antes de arrancar: si no, se autogenera y se avisa.
- Aplique la migración `0010` (aditiva); en contenedor las columnas se añaden solas al arrancar.
- **Hacen falta dos administradores activos**: con uno solo, toda rotación cae por la vía de
  emergencia, queda marcada y espera revisión. El arranque lo avisa.
- El formulario de edición de una credencial **ya no cambia la contraseña**.

### Añadido

- **Gobernanza de rotación de credenciales.** Cambiar la contraseña de una credencial del
  inventario deja de ser una edición y pasa a ser un ciclo con dos personas:
  `SOLICITADA → AUTORIZADA → CERRADA`, con **motivo obligatorio**, **regla de dos pares** (nadie
  autoriza lo que pidió) y **reautenticación con aplicación autenticadora** del autorizador. Cada
  rotación deja un asiento permanente en el libro mayor `rotaciones_credencial` con la antigüedad
  de la contraseña al solicitar, al autorizar y al rotar, y la desviación respecto a la fecha que
  marcaba la política.
- **Vía de emergencia acotada**: con un solo administrador disponible, una solicitud de emergencia
  la puede autorizar su propio solicitante dentro de una ventana corta. Queda marcada de forma
  imborrable, alerta a todos los administradores y exige revisión posterior de otro administrador.
- **Panel de rotación** (`/rotacion`) con pendientes de autorizar, autorización en lote,
  pendientes de aplicar y emergencias por revisar; y **línea de tiempo de gobernanza** en la ficha
  de cada credencial.
- **Reglas de patrón** sobre el libro mayor (tempranas repetidas, fuera de horario, concentración,
  abuso de la vía de emergencia), en **modo observación** por defecto.
- Campo **«usada por»** en la credencial: servicios y automatismos que consumen la cuenta, visible
  al solicitar y al autorizar una rotación.
- Capa **`app/servicios/`** con los casos de uso de rotación, reautenticación, patrones,
  **credenciales** y **autenticación completa** (login por etapas, cambio de contraseña, segundo
  factor por ambos métodos, auto-recuperación y cierre de sesión). Los controladores pasan a
  traducir HTTP ↔ servicio y no contienen ya consultas ni decisiones de acceso.
- Permisos `rotacion.ver`, `rotacion.solicitar`, `rotacion.autorizar` y `rotacion.revisar`.
- **Matriz de permisos generada del registro de rutas.** Cada dependencia de autorización declara
  el permiso que exige, de modo que el registro es autodescriptivo y la matriz se genera leyéndolo
  en vez de mantener una lista a mano. Añadir un endpoint sin declarar su política —un permiso
  RBAC, o una exención con su motivo escrito— hace fallar la suite.
- **Pruebas de navegador en CI** (Playwright) contra el sistema entero: backend, frontend
  compilado para producción y un receptor SMTP local. Cubren el acceso completo, la expiración de
  sesión, el alta y la verificación del segundo factor por **los dos métodos** (aplicación
  autenticadora y correo), la configuración y la exportación del inventario en claro. No hay
  endpoints de prueba en la aplicación: el correo se lee del buzón simulado, como lo leería una
  persona.
- Ajustes nuevos: `PASSWD_ROTACION_TEMPRANA_PCT`, `PASSWD_ROTACION_EMERGENCIA_VENTANA_MIN`,
  `PASSWD_ROTACION_EMERGENCIA_MAX_POR_MES` y `PASSWD_ROTACION_PATRONES_MODO_OBSERVACION`.
- [`docs/plan-rotacion-agentes.md`](docs/plan-rotacion-agentes.md): plan maestro de rotación
  asistida por agentes y monitoreo (propuesta revisada contra el código).
- [`docs/plan-v2.0.md`](docs/plan-v2.0.md): plan de la versión 2.0 (propuesta para aprobación).

### Seguridad

- **Bitácora de auditoría firmada con HMAC-SHA256** y clave `PASSWD_AUDIT_KEY` fuera de la base de
  datos. El encadenamiento anterior era un SHA-256 sin clave: quien pudiera escribir en la base
  podía recalcular la cadena entera y reescribir quién hizo qué. El material previo se conserva
  como **tramo heredado**, `verificar-auditoria` valida ambos tramos e informa del punto de corte,
  y un registro sin firmar después del corte se trata como cadena rota, de modo que la firma no se
  puede degradar reescribiendo filas con el algoritmo público.
- **Punto único de escritura de contraseñas del inventario.** Hasta ahora había tres caminos que
  escribían `Credencial.password_cifrada` con lógica duplicada (formulario clásico, API JSON e
  importación CSV); un circuito de autorización en uno solo no habría sido un control. Todos
  delegan ahora en `app/servicios/rotacion.py`, y una prueba de arquitectura falla si alguno
  vuelve a hacerlo por su cuenta. Un intento de cambiar la contraseña sin autorización vigente se
  rechaza con 409 y queda auditado.
- La reautenticación para autorizar una rotación **rechaza el código por correo**: un buzón puede
  estar compartido o abierto en la misma sesión, de modo que no acredita a una segunda persona.
- **Tres divergencias entre la interfaz clásica y la API JSON**, encontradas al unificar la
  autenticación. En las tres la interfaz clásica era la débil:
  - La **verificación del segundo factor no tenía límite de tasa por usuario**: solo la API JSON lo
    aplicaba. El bloqueo de cuenta seguía frenando la prueba sistemática, de modo que no era una
    puerta abierta, pero sí una defensa menos. Ahora la tienen las dos.
  - Un **código de enrolamiento incorrecto no contaba para el bloqueo** de la cuenta; solo se
    auditaba. Ahora cuenta, como ya hacía la API JSON.
  - Una cuenta con **segundo factor por correo no podía iniciar la auto-recuperación**, porque se
    exigía un secreto TOTP que esas cuentas no tienen. Quedaba atrapada en un desafío señuelo
    imposible de superar, aun teniendo códigos de recuperación válidos con los que completar el
    paso 2. Ahora puede.
- **El login deja de estar escrito dos veces.** El CSRF de doble cookie, el límite por IP, la
  comparación en tiempo constante contra un hash ficticio, el bloqueo de cuenta y el *rehash*
  oportunista vivían duplicados en los dos controladores de autenticación. Ahora hay una sola
  implementación, con pruebas propias sin HTTP. Al retirarlos, el hash ficticio que cada
  controlador calculaba al importarse (un Argon2id por módulo y por proceso) deja de computarse
  dos veces de más.
- **La entrega de una contraseña en claro deja de estar escrita dos veces.** El control de acceso
  por objeto, el límite anti-exfiltración y la auditoría vivían duplicados, línea por línea, en los
  dos controladores de credenciales, y mantenerlos sincronizados a mano es lo que falló en la
  1.2.0. Ahora hay una sola implementación en `app/servicios/credenciales.py`, con pruebas propias
  que no pasan por HTTP.

### Obsoleto

Avisos previos de las roturas de la 2.0, para que ninguna llegue por sorpresa
([`docs/plan-v2.0.md`](docs/plan-v2.0.md) §4):

- **La interfaz clásica (HTML) se retira en la 2.0** (R1). Sus respuestas llevan ya
  `Deprecation: true` y un `Link` a la documentación, y sus páginas muestran un aviso. `/api/web`,
  `/api/v1` y los estáticos no se marcan: siguen vivos.
- **`PASSWD_SMTP_TLS` y el uso de `PASSWD_NOTIFY_ENABLED` como interruptor del servicio de correo**
  dejarán de aceptarse en la 2.0 (R4). El arranque avisa **solo cuando esa herencia decide de
  verdad**, es decir cuando la variable nueva no está definida, y el aviso pide definirla, no
  sustituir la antigua: `PASSWD_NOTIFY_ENABLED` conserva su significado propio —las alertas de
  seguridad a los administradores— y pedir que se borre dejaría a quien lo hiciera sin ellas. Una
  instalación que no dependa de la herencia no ve nada.
- **`/api/v1/inventario` paginará siempre y excluirá por defecto los activos restringidos** en la
  2.0 (R7). La aplicación lo registra la primera vez que recibe una llamada sin `limit`. El
  contrato de `/api/v1` **no cambia en esta versión**: el aviso va por registro y documentación, no
  por el cuerpo de la respuesta, para no romper a un cliente con validación estricta de esquema.

### Cambiado

- El formulario de edición de una credencial **ya no permite cambiar la contraseña**: se rota por
  el ciclo de gobernanza. El resto de campos se siguen editando igual.
- El respaldo cifrado (formato `3`) incluye el libro mayor de rotaciones y las columnas nuevas de
  la credencial. Los respaldos de formato `1` y `2` se siguen restaurando.
- La verificación funcional de `/api/web` (`scripts/verificar_api_web.py`, el único control que
  corre sobre **MySQL**) recorre ya el ciclo de gobernanza completo —dos administradores,
  solicitud con motivo, autorización con reautenticación y registro— y comprueba que editar la
  credencial **ya no** cambia la contraseña. La matriz de permisos se valida contra `app/rbac.py`
  en vez de contra un número fijo, que envejecía con cada permiso nuevo.

## [1.2.1] - 2026-11-17

Versión PARCHE publicada desde `main` sin pasar por este registro; se documenta aquí para que el
histórico no tenga huecos.

### Corregido

- Sincronizar los permisos del menú **renovaba la sesión**, de modo que una sesión inactiva no
  llegaba a vencer mientras la pestaña siguiera abierta
  ([#29](https://github.com/sr-juanchii/passwd/pull/29)).

## [1.2.0] - 2026-11-14

**Sesión, segundo factor elegible y configuración coherente.** Versión MENOR: añade
funcionalidad y corrige un fallo de control de acceso sin romper integraciones, datos ni
configuración existentes (la migración `0009` es aditiva y las variables antiguas se siguen
aceptando). Corresponde a la **Fase 8** de la [hoja de ruta](docs/hoja-de-ruta.md).

**Al actualizar desde 1.1.0** (detalle en [`docs/notas-version-1.2.0.md`](docs/notas-version-1.2.0.md)):

- Se recomienda actualizar cuanto antes: corrige la exportación que entregaba a un operador las
  contraseñas de activos restringidos.
- `PASSWD_NOTIFY_ENABLED` pasa a controlar solo las alertas a administradores; el servicio de
  correo se enciende con `PASSWD_SMTP_ENABLED` (hereda el valor anterior si no se define).
- El correo como método principal de segundo factor queda **permitido por defecto** para los
  no administradores cuando el servicio de correo está activo. Se desactiva en
  Configuración → Verificación en dos pasos (`PASSWD_EMAIL_OTP_PRIMARY_ENABLED=false`).
- Aplique la migración `0009` (`alembic upgrade head`); en despliegues por contenedor la
  columna se añade sola al arrancar.


### Seguridad

- **Corregida una fuga de control de acceso en la exportación.** `POST /api/web/exportar`
  entregaba a un operador las contraseñas en claro de los activos **restringidos a
  administradores**; la interfaz clásica sí los excluía. La decisión vive ahora en un único
  punto compartido y `exportar_csv` es seguro por defecto. La exportación gana límite de tasa
  (5 por hora y usuario) y aviso de actividad sensible al titular.
- La **importación CSV** ya no permite a quien no puede restringir crear máquinas virtuales ni
  credenciales bajo activos restringidos.
- **TOTP**: se rechaza cualquier código de un paso temporal igual o anterior al último aceptado;
  los fallos durante el alta cuentan para el bloqueo; límite de tasa propio en la verificación.
- `recifrar` recifra también los **secretos guardados en la configuración** (contraseña SMTP).
- **Dependencias del frontend actualizadas** por avisos de seguridad publicados tras la 1.1.0:
  Next.js 16.2.11 → 16.4.6 (incluye vulnerabilidades críticas), `sharp` 0.35.0 → 0.35.5 y las
  transitivas `source-map-js`, `nanoid`, `browserslist` y `baseline-browser-mapping`. La auditoría
  de dependencias de producción queda sin hallazgos.

### Añadido

- **Aviso de expiración de sesión.** Poco antes de vencer, un diálogo con cuenta atrás permite
  extender la sesión o cerrarla; al vencer, la interfaz se cierra y lleva al inicio de sesión
  con un mensaje claro, conservando la página de origen. Nuevos `POST /api/web/session/extender`
  y plazos en `GET /api/web/session`, que deja de contar como actividad.
- **Método de segundo factor elegible**: aplicación autenticadora o **código por correo** como
  método principal, con política del administrador y vista **«Mi seguridad»** (cambio de método
  y regeneración de códigos de recuperación). Migración `0009`.
- **Configuración**: interruptor propio del servicio de correo (`PASSWD_SMTP_ENABLED`), modo de
  cifrado `PASSWD_SMTP_SECURITY` (`starttls` / `ssl` / `ninguna`), **«Probar conexión»** con los
  valores sin guardar, panel **«Estado del correo»**, dependencias visibles entre ajustes y
  validación de formato y coherencia. Pasan a ser editables en pantalla el respaldo y la validez
  del código por correo, los avisos a usuarios y el preaviso de rotación.
- **Mantenimiento periódico** (cada 6 h): la retención de auditoría surte efecto sin reiniciar.
- El respaldo incluye los ajustes guardados y el método de segundo factor.
- **Publicación automática**: al fusionar en `main` un cambio de versión, el flujo
  `publicar.yml` crea la etiqueta `vX.Y.Z` y la Release de GitHub con las notas del changelog.

### Cambiado

- `PASSWD_NOTIFY_ENABLED` controla **solo las alertas a administradores**; ya no apaga el resto
  del correo. Compatibilidad: `PASSWD_SMTP_ENABLED` hereda su valor si no se define, y los
  ajustes guardados se migran una vez al arrancar.
- `PASSWD_SMTP_TLS` queda **obsoleta** (se sigue aceptando) en favor de `PASSWD_SMTP_SECURITY`.
- `ACTIVITY_THROTTLE_SECONDS` deja de editarse en pantalla (solo por entorno) y se acota a la
  mitad de la ventana de inactividad.
- La CLI (`respaldo`, `avisar-rotacion`) aplica los ajustes guardados en la consola.
- El inicio de sesión muestra mensajes fijos por motivo en lugar de texto libre de la URL.
- El 401 de una sesión vencida incluye `code: "sesion_expirada"` y borra la cookie.

### Corregido

- La interfaz quedaba aparentemente abierta, mostrando «No autenticado», tras caducar la sesión.
- El diálogo de restablecer contraseña mostraba una contraseña vacía cuando el correo sí se
  enviaba.
- El texto «Mínimo 12 caracteres» del cambio de contraseña ignoraba la longitud configurada.

### Incluido también en esta versión (integrado en `main` tras la 1.1.0)

#### Añadido

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
  Documenta también las funciones incorporadas en la versión en curso: el **segundo
  factor por correo** (circuito completo con capturas, controles, límites de tasa y la
  decisión de riesgo que debe firmarse), el **restablecimiento administrativo con envío
  al titular**, los **avisos dinámicos por matriz de permisos** y el comando
  `avisar-rotacion`; más un **Anexo E** con los parches de seguridad de esta versión y
  su implicación operativa, y un **Anexo F** con la cobertura por interfaz, que deja
  constancia de que el OTP por correo y el aviso de envío del reset están hoy solo en la
  interfaz clásica y en la API, no en el frontend Next.js.

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

#### Cambiado

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

#### Seguridad

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

#### Añadido

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

[Sin publicar]: https://github.com/sr-juanchii/passwd/compare/v1.3.0...HEAD
[1.3.0]: https://github.com/sr-juanchii/passwd/compare/v1.2.1...v1.3.0
[1.2.1]: https://github.com/sr-juanchii/passwd/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/sr-juanchii/passwd/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/sr-juanchii/passwd/releases/tag/v1.1.0
[1.0.0]: https://github.com/sr-juanchii/passwd/releases/tag/v1.0.0
