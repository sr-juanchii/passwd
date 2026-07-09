# Referencia de configuración (variables de entorno)

Toda la configuración se hace por **variables de entorno con prefijo `PASSWD_`** (más
`MYSQL_PASSWORD`, exclusiva del overlay de MySQL). Se leen en
[`app/config.py`](../app/config.py) al arrancar. Salvo el administrador inicial, **todas tienen un
valor por defecto razonable**.

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
| `PASSWD_REQUIRE_ENV_KEYS` | `false` | **Modo estricto de producción**: con `true`, la aplicación **no arranca** si las dos claves no llegan por variable de entorno y nunca las autogenera en el directorio de datos. |

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

---

## 8. MFA

| Variable | Por defecto | Descripción |
|---|---|---|
| `PASSWD_TOTP_ISSUER` | `Gestor-Passwd` | Nombre del emisor que aparece en la app autenticadora. Conviene distinguirlo por ambiente (p. ej. `passwd-PROD`). |

---

## 9. Notificaciones por correo (opt-in)

Los correos **nunca** llevan secretos. Avisan de cuenta bloqueada, posible exfiltración, alta de
usuario y fallo de respaldo.

| Variable | Por defecto | Descripción |
|---|---|---|
| `PASSWD_NOTIFY_ENABLED` | `false` | Activa el envío de alertas. |
| `PASSWD_SMTP_HOST` | `""` | Servidor SMTP. |
| `PASSWD_SMTP_PORT` | `587` | Puerto SMTP. |
| `PASSWD_SMTP_USER` | `""` | Usuario SMTP. |
| `PASSWD_SMTP_PASSWORD` | `""` | Contraseña SMTP (secreto). |
| `PASSWD_SMTP_FROM` | `SMTP_USER` si está vacía | Dirección remitente. |
| `PASSWD_SMTP_TLS` | `true` | Usar STARTTLS. |
| `PASSWD_NOTIFY_TO` | `""` | Destinatarios, separados por coma. |

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
</content>
