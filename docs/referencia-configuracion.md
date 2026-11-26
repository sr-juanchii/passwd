# Referencia de configuración (variables de entorno)

Toda la configuración **base** se hace por **variables de entorno con prefijo `PASSWD_`** (más
`MYSQL_PASSWORD`, exclusiva del overlay de MySQL). Se leen en
[`app/config.py`](../app/config.py) al arrancar. Salvo el administrador inicial, **todas tienen un
valor por defecto razonable**.

> **Configuración en caliente (sin reiniciar).** Un administrador puede modificar muchos de estos
> parámetros operativos desde la pantalla **Configuración** de la propia aplicación (o la API
> `/api/web/configuracion`), sin editar el `.env` ni redeplegar. Esos *overrides* se guardan en la
> base de datos y **tienen prioridad** sobre la variable de entorno. Los parámetros que **no** son
> editables en caliente (claves, base de datos, arranque, cabeceras/limite de petición…) siguen
> siendo exclusivos de entorno. El detalle está en la sección
> [«Configuración en tiempo de ejecución»](#12-configuración-en-tiempo-de-ejecución-editable-por-el-administrador)
> al final de este documento.

> Para empezar, copie la plantilla del ambiente que corresponda a `.env` y rellene los secretos:
> [`.env.desarrollo.example`](../.env.desarrollo.example),
> [`.env.calidad.example`](../.env.calidad.example),
> [`.env.preproduccion.example`](../.env.preproduccion.example),
> [`.env.produccion.example`](../.env.produccion.example). La referencia con todos los valores está
> en [`.env.example`](../.env.example) y la guía por ambiente en [`ambientes.md`](ambientes.md).

---

## 1. Administrador inicial

Solo se usan **si la base de datos está vacía** (no hay usuarios). Tras el primer arranque, retire
`PASSWD_ADMIN_PASSWORD` del `.env`.

| Variable | Por defecto | Descripción |
|---|---|---|
| `PASSWD_ADMIN_USERNAME` | `""` | Usuario del administrador de arranque. |
| `PASSWD_ADMIN_EMAIL` | `""` | Correo del administrador de arranque. |
| `PASSWD_ADMIN_PASSWORD` | `""` | Contraseña **de un solo uso**: el sistema fuerza su cambio y el enrolamiento MFA en el primer acceso. |

---

## 2. Claves criptográficas (secretos)

Si se omiten, se **generan automáticamente** y se guardan con permisos `0600` en el directorio de
datos (`.secret_key`, `.encryption_key`). En **producción y preproducción** conviene **fijarlas y
custodiarlas** en un gestor de secretos, y usar **claves distintas por ambiente**.

| Variable | Por defecto | Descripción |
|---|---|---|
| `PASSWD_SECRET_KEY` | autogenerada | Clave para firmar/derivar material de sesión. Genérela con `python -c "import secrets; print(secrets.token_urlsafe(48))"`. |
| `PASSWD_ENCRYPTION_KEY` | autogenerada | Clave **Fernet** para el cifrado en reposo (contraseñas, semillas TOTP, notas). Genérela con `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Admite **varias claves separadas por comas** para la rotación: la **primera** cifra y todas descifran (ver [`referencia-cli.md`](referencia-cli.md), comando `recifrar`). |
| `PASSWD_AUDIT_KEY` | autogenerada | Clave de **firma de la bitácora** (HMAC-SHA256). Sin ella el encadenamiento sería un SHA-256 público, recalculable por quien tenga escritura en la base de datos. Genérela con `python -c "import secrets; print(secrets.token_urlsafe(48))"`. |
| `PASSWD_REQUIRE_ENV_KEYS` | `false` | **Modo estricto de producción**: con `true`, la aplicación **no arranca** si `SECRET_KEY` y `ENCRYPTION_KEY` no llegan por variable de entorno y nunca las autogenera en el directorio de datos. |

> `PASSWD_AUDIT_KEY` **no entra todavía** en `REQUIRE_ENV_KEYS`: exigirla dejaría sin arrancar a una
> instalación que hoy funciona en modo estricto, y eso sería una rotura en una versión menor. Si el
> modo estricto está activo y la clave no llega por entorno, el arranque lo advierte y la
> autogenera. **Defínala por entorno igualmente**: la evidencia de auditoría no debería compartir
> volumen con la base de datos que atestigua. La 2.0 la incorpora al grupo obligatorio.

> **Docker secrets:** cualquiera de estos secretos (`SECRET_KEY`, `ENCRYPTION_KEY`, `AUDIT_KEY`, `SMTP_PASSWORD`)
> puede proveerse por fichero con la variante **`PASSWD_<NOMBRE>_FILE`** (ruta a un fichero montado,
> p. ej. `/run/secrets/...`), que tiene prioridad sobre la variable en claro. Ver
> [`docker-compose.secrets.yml`](../docker-compose.secrets.yml).

> ⚠️ **Perder `PASSWD_ENCRYPTION_KEY` = perder todas las contraseñas guardadas** (salvo que tenga un
> respaldo cifrado con frase). Si autogenera las claves en MySQL y el volumen de datos se pierde,
> lo cifrado queda ilegible.
>
> La autogeneración a archivo es un modo **solo para desarrollo**: la clave queda en el mismo
> directorio que la base de datos, y un compromiso del volumen (o de sus copias) expondría ambas.
> En producción provea las claves por entorno desde su gestor de secretos y active
> `PASSWD_REQUIRE_ENV_KEYS=true` (así vienen las plantillas de prod/preprod).

---

## 3. Aplicación y datos

| Variable | Por defecto | Descripción |
|---|---|---|
| `PASSWD_APP_NAME` | `Gestor de Contraseñas de Servidores` | Nombre mostrado en la interfaz. |
| `PASSWD_DATA_DIR` | `./data` (en Docker, `/srv/passwd/data`) | Directorio de datos: BD SQLite y archivos de claves. |
| `PASSWD_DATABASE_URL` | SQLite en `PASSWD_DATA_DIR` | URL SQLAlchemy. Para MySQL: `mysql+pymysql://usuario:clave@host:3306/passwd`. |
| `PASSWD_DB_POOL_SIZE` | `5` | Tamaño del pool de conexiones (solo motores cliente/servidor como MySQL). |
| `PASSWD_DB_MAX_OVERFLOW` | `10` | Conexiones adicionales por encima del pool bajo carga. |
| `PASSWD_DB_POOL_RECYCLE_SECONDS` | `1800` | Recicla conexiones antes del `wait_timeout` del servidor. |
| `PASSWD_ACTIVITY_THROTTLE_SECONDS` | `60` | Amortigua las escrituras de «última actividad» de sesión y «último uso» de token (no se reescriben en cada petición). Solo por entorno; nunca supera la mitad de la ventana de inactividad. |

---

## 4. Sesiones y cookies

| Variable | Por defecto | Descripción |
|---|---|---|
| `PASSWD_SESSION_IDLE_MINUTES` | `15` | Expiración de sesión por **inactividad** (CIS 4.3). |
| `PASSWD_SESSION_MAX_HOURS` | `8` | Vida **máxima absoluta** de una sesión. |
| `PASSWD_COOKIE_SECURE` | `true` | Cookie con atributo `Secure` (requiere HTTPS). Ponga `false` **solo** en desarrollo local sin TLS; con `true` activa también HSTS. |

---

## 5. Política de cuentas y contraseñas

| Variable | Por defecto | Descripción |
|---|---|---|
| `PASSWD_PASSWORD_MIN_LENGTH` | `12` | Longitud mínima de contraseña de usuario. |
| `PASSWD_MAX_FAILED_ATTEMPTS` | `5` | Intentos fallidos antes de bloquear la cuenta. |
| `PASSWD_LOCKOUT_MINUTES` | `15` | Duración del bloqueo de cuenta. |

---

## 6. Límites de tasa y anti-abuso (OWASP)

| Variable | Por defecto | Descripción |
|---|---|---|
| `PASSWD_LOGIN_RATE_LIMIT` | `15` | Intentos de login permitidos por IP en la ventana. |
| `PASSWD_LOGIN_RATE_WINDOW_MINUTES` | `5` | Ventana del límite de login. |
| `PASSWD_REVEAL_RATE_LIMIT` | `20` | **Anti-exfiltración**: revelados/copiados de contraseñas por usuario en la ventana. |
| `PASSWD_REVEAL_RATE_WINDOW_MINUTES` | `5` | Ventana del límite de revelados. |
| `PASSWD_MAX_REQUEST_BYTES` | `65536` | Tamaño máximo del cuerpo de una petición (OWASP API4). |
| `PASSWD_RATE_LIMIT_BACKEND` | `memoria` | `memoria` (un proceso) o `bd` (compartido entre varias instancias, sin Redis). Con `memoria` el presupuesto se **multiplica** por cada worker/réplica: en producción use `bd` (la app avisa al arrancar; las plantillas de prod/preprod ya lo traen). |
| `PASSWD_TRUSTED_PROXIES` | *(vacío)* | Proxies de confianza para `X-Forwarded-For` (CSV de IPs o `*`). Si se define, la auditoría y el límite de tasa usan la **IP real del cliente** en lugar de la del proxy, confiando en la cabecera **solo** cuando la conexión procede de esas IPs. `*` es seguro cuando únicamente nginx puede alcanzar la app (red interna de compose). Equivale a `--proxy-headers --forwarded-allow-ips` de uvicorn (los overlays de nginx ya pasan esas banderas; esta variable cubre además los despliegues sin overlay). |

---

## 7. Auditoría y rotación

| Variable | Por defecto | Descripción |
|---|---|---|
| `PASSWD_AUDIT_RETENTION_DAYS` | `365` | Retención de la bitácora. **Nunca baja de 90 días** aunque se configure menos (CIS 8.10). |
| `PASSWD_ROTATION_MAX_DAYS` | `90` | Días sin rotar una credencial antes de mostrar la alerta de rotación. |
| `PASSWD_PASSWORD_HISTORY_MAX` | `5` | Contraseñas anteriores conservadas por credencial. |

### Gobernanza de rotación (desde la 1.3.0)

`PASSWD_ROTATION_MAX_DAYS` es además el **intervalo de política** con el que se calcula la fecha
programada de cada credencial y la desviación al rotar. No existe un segundo ajuste con el mismo
significado, a propósito: dos verdades sobre lo mismo acaban divergiendo.

| Variable | Por defecto | Descripción |
|---|---|---|
| `PASSWD_ROTACION_TEMPRANA_PCT` | `25` | Porcentaje de la vigencia por debajo del cual una rotación se marca **temprana** y exige motivo reforzado. Con 90 días, 25 % son 22 días. |
| `PASSWD_ROTACION_EMERGENCIA_VENTANA_MIN` | `60` | Minutos, desde la solicitud, en los que un único administrador puede autorizar su propia solicitud **de emergencia**. Fuera de la ventana vuelve a exigirse la regla de dos personas. |
| `PASSWD_ROTACION_EMERGENCIA_MAX_POR_MES` | `3` | Emergencias sin segundo par admitidas en 30 días antes de señalarlo como patrón de abuso. Nunca bloquea una contención en curso: solo la señala. |
| `PASSWD_ROTACION_PATRONES_MODO_OBSERVACION` | `true` | Las reglas de patrón se evalúan y se ven en métricas, pero **no envían avisos**. Déjelo activo hasta calibrar los umbrales con datos reales. |

### Agentes de rotación (desde la 1.4.0)

Un agente instalado en un servidor Linux aplica la rotación **ya autorizada** por dos personas, la
verifica y la revierte si falla. Todo queda tras un interruptor **apagado por defecto**: con
`AGENTES_ENABLED=false` el prefijo `/api/agent` responde 404, no se dan de alta agentes y toda
rotación sigue el flujo manual de la 1.3.0. Arquitectura en
[`arquitectura-agentes.md`](arquitectura-agentes.md) e instalación en
[`guia-instalacion-agente-linux.md`](guia-instalacion-agente-linux.md).

Los diez son editables en caliente desde **Configuración → Agentes de rotación** (columna «En
caliente»); el interruptor surte efecto en la siguiente petición, sin reiniciar.

| Variable | Tipo | Por defecto | En caliente | Descripción |
|---|---|---|:-:|---|
| `PASSWD_AGENTES_ENABLED` | booleano | `false` | ✔ | **Interruptor general.** Apagado, ningún agente se enrola ni recibe trabajos, la API del agente no existe (404) y toda rotación es manual. Al apagarlo con agentes instalados, sus peticiones reciben 404 y no pueden renovar su identidad: si sigue apagado más que `AGENTES_TOKEN_VIDA_HORAS`, al volver a encenderlo habrá que reinstalarlos. Las rotaciones que se autoricen mientras tanto quedan **autorizadas sin despachar** (la decisión de dos personas se conserva). |
| `PASSWD_ROTACION_VENTANA_JOB_MIN` | entero (1–1440 min) | `30` | ✔ | Validez de un trabajo despachado: minutos que tiene el agente para recogerlo y empezarlo. Debe ser claramente mayor que la cadencia del latido, o un trabajo despachado justo después de un latido vencería sin recogerse. Pasado el plazo sin recogerse, el trabajo expira y la rotación **vuelve a quedar autorizada**; el agente tampoco aplica un trabajo vencido. |
| `PASSWD_ROTACION_ANTI_THRASH_HORAS` | entero (0–720 h) | `24` | ✔ | Intervalo mínimo entre rotaciones por agente: una credencial rotada hace menos de estas horas no se despacha. Solo una solicitud de **emergencia** lo salta, y queda en la bitácora (`rotacion_anti_thrash_saltado`). `0` lo desactiva. |
| `PASSWD_AGENTES_TOKEN_VIDA_HORAS` | entero (1–720 h) | `24` | ✔ | Vida de la identidad de un agente. Se renueva sola en el latido cuando entra en su último cuarto de vida, y el token anterior vale 30 minutos más. Un agente apagado más tiempo que esto pasa a «Identidad caducada» y hay que reinstalarlo con un token nuevo. |
| `PASSWD_AGENTES_UMBRAL_SIN_CONTACTO_HORAS` | entero (1–720 h) | `1` | ✔ | Horas sin latido tras las cuales la insignia del agente pasa a «Sin contacto» y el mantenimiento periódico avisa al equipo de seguridad (una vez por silencio). Debe ser menor que `AGENTES_TOKEN_VIDA_HORAS`: la caducidad se comprueba antes, y con valores iguales el agente pasaría directamente a «Identidad caducada». |
| `PASSWD_AGENTES_TELEMETRIA_INTERVALO_MIN` | entero (1–1440 min) | `15` | ✔ | Cadencia de latido y telemetría que el servidor indica a los agentes al enrolarse y en cada latido. |
| `PASSWD_AGENTES_RETENCION_TELEMETRIA_DIAS` | entero (1–3650 días) | `30` | ✔ | Días que se conserva la telemetría (CPU, RAM, disco, tiempo encendido, sistema operativo). El mantenimiento periódico purga lo anterior. No afecta a la bitácora ni al libro mayor. |
| `PASSWD_AGENTES_VERSION_MINIMA` | texto (`X.Y.Z` o vacío) | `""` | ✔ | Versión mínima de agente que recibe trabajos. Vacío: cualquiera. Un agente por debajo sigue latiendo, pero no recibe trabajos al acabar la gracia. |
| `PASSWD_AGENTES_GRACIA_VERSION_DIAS` | entero (0–365 días) | `14` | ✔ | Días durante los que un agente por debajo de la mínima sigue recibiendo trabajos. **Cuentan desde que la mínima se fija en la consola**; fijada solo por entorno no hay fecha de la que contar y **rige sin gracia**. |
| `PASSWD_AGENTES_ALERTAR_IP_DISTINTA` | booleano | `true` | ✔ | Avisa por correo cuando un agente renueva su identidad desde una IP distinta de la renovación anterior dentro de la misma vida del token: puede ser un token copiado. Detrás de un NAT con varias salidas da falsos positivos. Apagado, el asiento `agente_anomalia_ip` **se sigue registrando**; solo deja de enviarse el correo. |

> **Topes del protocolo del agente (no configurables).** Además del límite global
> `PASSWD_MAX_REQUEST_BYTES`, la API `/api/agent` aplica topes propios, muy por debajo: como máximo
> **4 KiB** por petición y **16 KiB** en la telemetría (413 si se excede), y aplica límites de tasa propios (120 peticiones por agente y 300
> por IP cada 5 minutos; 10 intentos de enrolamiento por IP cada 15 minutos). Están fijados en
> [`app/api_agent/__init__.py`](../app/api_agent/__init__.py) y documentados en
> [`referencia-api-agent.md`](referencia-api-agent.md).

---

## 7 bis. Configuración obsoleta (se retira en la 2.0)

Estas variables se siguen aceptando en la serie 1.x, pero **la 2.0 dejará de leerlas** (rotura R4 de
[`plan-v2.0.md`](plan-v2.0.md)). Si alguna está fijando el valor de su sustituta —es decir, si la sustituta **no** está definida—,
la aplicación lo **avisa en el arranque** y pide definir la sustituta. Con las dos puestas manda la
nueva, no hay herencia que corregir y no se avisa nada; una instalación que no las use tampoco verá
nada.

El aviso habla de la **herencia**, no de la variable: `PASSWD_NOTIFY_ENABLED` conserva su
significado propio (las alertas de seguridad a administradores) y borrarla dejaría la instalación
sin ellas.

| Variable obsoleta | Sustituta | Qué hacer |
|---|---|---|
| `PASSWD_SMTP_TLS` | `PASSWD_SMTP_SECURITY` | `true` → `starttls`, `false` → `ninguna` |
| `PASSWD_NOTIFY_ENABLED` como interruptor del servicio de correo | `PASSWD_SMTP_ENABLED` | Defina `SMTP_ENABLED` explícitamente; `NOTIFY_ENABLED` queda solo para las alertas a administradores |

Lo mismo ocurre con la **interfaz clásica** (rotura R1): sus respuestas llevan ya la cabecera
`Deprecation: true` y sus páginas muestran un aviso. La funcionalidad equivalente está en la
interfaz nueva; la 2.0 retira las rutas HTML del backend.

---

## 8. MFA

| Variable | Por defecto | Descripción |
|---|---|---|
| `PASSWD_TOTP_ISSUER` | `Gestor-Passwd` | Nombre del emisor que aparece en la app autenticadora. Conviene distinguirlo por ambiente (p. ej. `passwd-PROD`). |

---

## 9. Correo saliente, notificaciones y verificación en dos pasos por correo

El **servicio de correo** es la base de todo lo que la aplicación envía: códigos de
verificación, contraseñas temporales, alertas y avisos. Tiene su propio interruptor
(`SMTP_ENABLED`); las alertas a administradores y los avisos a usuarios se activan aparte y
**ya no apagan el resto**. Los correos **nunca** llevan secretos del inventario.

**Servidor de correo (SMTP)**

| Variable | Por defecto | Descripción |
|---|---|---|
| `PASSWD_SMTP_ENABLED` | hereda `NOTIFY_ENABLED` | **Interruptor del servicio de correo.** Apagado, la aplicación no envía nada. Si no se define, toma el valor de `PASSWD_NOTIFY_ENABLED` (compatibilidad con versiones anteriores, donde esa variable hacía de interruptor general). |
| `PASSWD_SMTP_HOST` | `""` | Nombre o IP del servidor SMTP (sin `smtp://` ni puerto). |
| `PASSWD_SMTP_PORT` | `587` | Puerto: 587 con STARTTLS, 465 con SSL/TLS, 25 para relés internos. |
| `PASSWD_SMTP_SECURITY` | `starttls` | Cifrado de la conexión: `starttls`, `ssl` (TLS implícito, puerto 465) o `ninguna` (solo relés internos de confianza). Si no se define se deduce de la antigua `PASSWD_SMTP_TLS` (`true` → `starttls`, `false` → `ninguna`). |
| `PASSWD_SMTP_USER` | `""` | Usuario SMTP. Vacío = el servidor no exige autenticación. |
| `PASSWD_SMTP_PASSWORD` | `""` | Contraseña SMTP (secreto; admite `_FILE`). Solo tiene sentido con usuario. |
| `PASSWD_SMTP_FROM` | `SMTP_USER` si está vacía | Dirección remitente. Debe ser una dirección de correo. |
| `PASSWD_SMTP_TLS` | — | **Obsoleta**; se sigue aceptando. Use `PASSWD_SMTP_SECURITY`. |

**Notificaciones** (requieren el servicio de correo activo)

| Variable | Por defecto | Descripción |
|---|---|---|
| `PASSWD_NOTIFY_ENABLED` | `false` | **Alertas de seguridad a administradores** (cuenta bloqueada, posible exfiltración, alta de usuario, acceso por el método de respaldo, fallo de respaldo). |
| `PASSWD_NOTIFY_TO` | `""` | Destinatarios de esas alertas, separados por coma. Obligatorio si las alertas están activas. |
| `PASSWD_NOTIFY_USERS_ENABLED` | `true` | **Avisos a cada usuario** en su propio buzón (inicios de sesión, actividad sensible, cambios en sus permisos, credenciales compartidas y rotación). Ver [`notificaciones-y-mfa-correo.md`](notificaciones-y-mfa-correo.md). |
| `PASSWD_ROTATION_WARNING_DAYS` | `14` | Antelación del aviso de rotación obligatoria (comando `avisar-rotacion`). |

**Verificación en dos pasos**

| Variable | Por defecto | Descripción |
|---|---|---|
| `PASSWD_TOTP_ISSUER` | `Gestor-Passwd` | Nombre de la instalación en las aplicaciones autenticadoras y en el asunto de los correos. |
| `PASSWD_EMAIL_OTP_PRIMARY_ENABLED` | `true` | Permite que cada usuario **elija el correo como método principal** (sin aplicación autenticadora). Factor **más débil** que el TOTP: depende de la seguridad del buzón. Requiere el servicio de correo. |
| `PASSWD_MFA_TOTP_REQUIRED_ADMIN` | `true` | Las cuentas de **administrador** deben usar aplicación autenticadora: el correo no les vale como método principal. |
| `PASSWD_EMAIL_OTP_ENABLED` | `true` | Permite el correo como **respaldo** de quien usa aplicación autenticadora (cada uso se audita y alerta). Requiere el servicio de correo. |
| `PASSWD_EMAIL_OTP_TTL_MINUTES` | `10` | Minutos de validez del código enviado por correo. |

---

## 10. Respaldos automatizados

| Variable | Por defecto | Descripción |
|---|---|---|
| `PASSWD_BACKUP_PASSPHRASE` | `""` | Frase para `python -m app.cli respaldo` sin interacción (cron). Custódiela **fuera** del servidor; sin ella el respaldo es irrecuperable. |

---

## 11. Despliegue (nginx / MySQL)

| Variable | Por defecto | Descripción |
|---|---|---|
| `PASSWD_DOMAIN` | — | Dominio o IP con el que nginx sirve la aplicación (`server_name` y CN del certificado). En pruebas, `localhost`. |
| `MYSQL_PASSWORD` | — | **Solo** con el overlay `docker-compose.mysql.yml`. Contraseña del usuario `passwd` de MySQL. Descoméntela en el `.env` y **no deje espacios alrededor del `=`**. |

---

## Recomendaciones por ambiente (resumen)

| Aspecto | Desarrollo | Calidad | Preproducción | Producción |
|---|---|---|---|---|
| Base de datos | SQLite | SQLite/MySQL | MySQL | MySQL |
| `PASSWD_COOKIE_SECURE` | `false` | `true` | `true` | `true` |
| Claves cripto | autogeneradas | autogeneradas | **fijadas** | **fijadas** |
| Notificaciones | off | off | on | on |
| Límites de tasa | holgados | moderados | estrictos (defecto) | estrictos (defecto) |
| Auditoría | corta | 90 d | 365 d | 365 d |

Detalle y plantillas listas para copiar en [`ambientes.md`](ambientes.md).

---

## 12. Configuración en tiempo de ejecución (editable por el administrador)

Además de las variables de entorno (que fijan los valores **base** al arrancar), la aplicación
incluye una pantalla de **Configuración** (menú superior, solo administradores; API
`/api/web/configuracion`) que permite ajustar parámetros operativos **en caliente**, sin editar el
`.env` ni reiniciar. Implementada en [`app/ajustes.py`](../app/ajustes.py) sobre la tabla
`configuracion`.

**Cómo funciona**

- Cada ajuste editable parte de su valor **base** (variable de entorno si está definida, o el valor
  por defecto). Si el administrador lo cambia, se guarda un *override* en la base de datos que
  **tiene prioridad** sobre la variable de entorno. «Restablecer» borra el override y vuelve a la base.
- Los cambios se **aplican al instante** en el proceso que los realiza y se propagan al resto de
  *workers*/instancias en pocos segundos (refresco periódico). **Toda modificación queda auditada**
  (`configuracion_cambiada` / `configuracion_restablecida`); el valor de los secretos nunca se
  registra.
- La **contraseña SMTP** se guarda **cifrada** (Fernet) y **nunca** se devuelve en claro a la
  interfaz (solo se indica si está configurada). Dejar su campo vacío al guardar la **conserva**.
- Cada ajuste indica **de qué depende** (p. ej. los destinatarios solo surten efecto con las
  alertas activas y el servicio de correo encendido); la pantalla lo deshabilita y explica por
  qué mientras no se cumpla. Al guardar se valida el formato (host, direcciones) y la coherencia
  entre ajustes (la inactividad no puede superar la duración máxima de la sesión; activar el
  correo exige servidor y remitente; activar las alertas exige destinatarios).
- **«Probar conexión»** comprueba la conexión y la autenticación SMTP con los valores del
  formulario **sin guardarlos y sin enviar nada**. **«Enviar prueba»** manda un mensaje con la
  configuración guardada (`correo_prueba_enviado`). Los errores se explican sin exponer detalles
  internos del servidor.
- El panel **«Estado del correo»** muestra qué funciones dependen del correo y cuáles están
  operativas.

**Parámetros editables en caliente** (por grupo). La columna indica la variable de entorno que
fija su valor base:

| Grupo | Ajuste (variable de entorno base) |
|---|---|
| Sesión | `SESSION_IDLE_MINUTES`, `SESSION_MAX_HOURS` |
| Cuentas y contraseñas | `PASSWORD_MIN_LENGTH` (mín. 8), `MAX_FAILED_ATTEMPTS`, `LOCKOUT_MINUTES` |
| Verificación en dos pasos | `TOTP_ISSUER`, `EMAIL_OTP_PRIMARY_ENABLED`, `MFA_TOTP_REQUIRED_ADMIN`, `EMAIL_OTP_ENABLED`, `EMAIL_OTP_TTL_MINUTES` |
| Servidor de correo (SMTP) | `SMTP_ENABLED`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY`, `SMTP_USER`, `SMTP_PASSWORD` (cifrada), `SMTP_FROM` |
| Notificaciones | `NOTIFY_ENABLED`, `NOTIFY_TO`, `NOTIFY_USERS_ENABLED`, `ROTATION_WARNING_DAYS` |
| Límites anti-abuso | `LOGIN_RATE_LIMIT`, `LOGIN_RATE_WINDOW_MINUTES`, `REVEAL_RATE_LIMIT`, `REVEAL_RATE_WINDOW_MINUTES` |
| Inventario y auditoría | `ROTATION_MAX_DAYS`, `PASSWORD_HISTORY_MAX`, `AUDIT_RETENTION_DAYS` (mín. 90) |
| Gobernanza de rotación | `ROTACION_TEMPRANA_PCT`, `ROTACION_EMERGENCIA_VENTANA_MIN`, `ROTACION_EMERGENCIA_MAX_POR_MES`, `ROTACION_PATRONES_MODO_OBSERVACION` |
| Agentes de rotación (1.4.0) | `AGENTES_ENABLED`, `ROTACION_VENTANA_JOB_MIN`, `ROTACION_ANTI_THRASH_HORAS`, `AGENTES_TOKEN_VIDA_HORAS`, `AGENTES_UMBRAL_SIN_CONTACTO_HORAS`, `AGENTES_TELEMETRIA_INTERVALO_MIN`, `AGENTES_RETENCION_TELEMETRIA_DIAS`, `AGENTES_VERSION_MINIMA` (formato `X.Y.Z`), `AGENTES_GRACIA_VERSION_DIAS`, `AGENTES_ALERTAR_IP_DISTINTA` |

La **retención de auditoría** se aplica al arrancar y después cada 6 horas, de modo que un
cambio desde la consola surte efecto sin reiniciar. El mismo mantenimiento periódico purga la
**telemetría de los agentes**, cierra los trabajos vencidos y avisa de los agentes sin contacto.
La **gracia de la versión mínima** de los agentes cuenta desde que la mínima se guarda en esta
pantalla; fijada solo por entorno rige sin gracia. La **CLI** (`respaldo`, `avisar-rotacion`)
también aplica los ajustes guardados aquí.

`ACTIVITY_THROTTLE_SECONDS` dejó de ser editable en pantalla: es un ajuste técnico que se
define solo por entorno y que la aplicación acota a la mitad de la ventana de inactividad.

**NO editables en caliente** (exclusivos de entorno; requieren reinicio o son secretos de
despliegue): claves criptográficas (`SECRET_KEY`, `ENCRYPTION_KEY`, `AUDIT_KEY`, `REQUIRE_ENV_KEYS`), base de
datos (`DATABASE_URL`, pool), `COOKIE_SECURE`, `MAX_REQUEST_BYTES`, `TRUSTED_PROXIES`,
`RATE_LIMIT_BACKEND`, `DATA_DIR` y el arranque del administrador. Se muestran como **información de
solo lectura** en la misma pantalla.
</content>
