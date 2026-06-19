# Guía de despliegue en PRE-PRODUCCIÓN (servidor de laboratorio)

**Sistema:** Gestor de Contraseñas de Servidores
**Audiencia:** personal de TI que instala y opera el entorno de **pre-producción** (staging).
**Alcance:** runbook **secuencial y completo** para poner en marcha el sistema en un servidor de
laboratorio que replica producción — desde la **generación de certificados TLS** hasta la
**conexión con el SMTP** — con verificación en cada paso.

> Pre-producción es una **réplica fiel de producción** que sirve para validar despliegues,
> migraciones y el envío de correo **antes** del salto a prod. Usa **sus propias** claves, base de
> datos, dominio/IP y destinatarios: **nunca** compartas secretos con producción.

Esta guía es autocontenida. Para el detalle de cada pieza puedes apoyarte en:
[`ambientes.md`](ambientes.md) · [`guia-nginx-tls.md`](guia-nginx-tls.md) ·
[`referencia-configuracion.md`](referencia-configuracion.md) · [`referencia-cli.md`](referencia-cli.md) ·
[`guia-implementacion.md`](guia-implementacion.md).

---

## 0. Qué vamos a levantar

El stack de pre-producción combina **cuatro servicios** en Docker, idénticos a producción:

```
                         ┌──────────────────────────────────────────────┐
 Usuario ──HTTPS/443──►  │  nginx (TLS)   termina HTTPS, enruta:         │
            redirige 80→443 │   /api/* y /healthz ─► app (FastAPI :8000) │
                         │   el resto          ─► frontend (Next :3000)  │
                         └───────────────┬──────────────────────────────┘
                                         │  red interna Docker "red-passwd"
                         ┌───────────────▼───────────────┐
                         │  app (uvicorn) ──► db (MySQL 8) │
                         │  datos/claves en volumen        │
                         └─────────────────────────────────┘
```

| Servicio   | Imagen / origen                | Función                                                |
|------------|--------------------------------|--------------------------------------------------------|
| `app`      | build local (`Dockerfile`)     | Backend FastAPI: API JSON, MFA, RBAC, auditoría, CLI.  |
| `frontend` | build local (`frontend/`)      | Interfaz Next.js + shadcn/ui (paridad completa).       |
| `nginx`    | `nginx:1.27-alpine`            | Terminación TLS, HSTS, IP real del cliente, enrutado.  |
| `db`       | `mysql:8.4`                    | Base de datos relacional (réplica de prod).            |

**Comando de arranque** (lo ejecutaremos en el paso 8, no lo lances todavía):

```bash
docker compose -f docker-compose.yml \
               -f docker-compose.frontend.yml \
               -f docker-compose.mysql.yml up -d --build
```

> **Variante solo web Jinja** (sin el frontend Next.js): sustituye
> `-f docker-compose.frontend.yml` por `-f docker-compose.nginx.yml`. Todo lo demás de esta guía es
> idéntico (mismos certificados, mismo `.env`, mismo SMTP).

---

## 1. Requisitos previos

| Recurso        | Mínimo para laboratorio                                                            |
|----------------|------------------------------------------------------------------------------------|
| CPU / RAM      | 2 vCPU / 2 GB (app + frontend + MySQL en la misma máquina).                         |
| Disco          | 5 GB libres (imágenes Docker + BD + respaldos locales).                             |
| SO             | Linux con **Docker Engine 24+** y **Docker Compose v2** (`docker compose`, no `-`). |
| Reloj          | **NTP activo** y zona horaria correcta — el MFA TOTP depende de la hora.            |
| Red            | Puertos **80 y 443** alcanzables por los clientes de la red de laboratorio.         |
| Cliente TOTP   | App autenticadora en el móvil (Aegis, FreeOTP, Google/Microsoft Authenticator).     |
| SMTP           | Datos de un relay/buzón de correo de **pruebas** (host, puerto, usuario, clave).    |

Verifica las herramientas antes de empezar:

```bash
docker --version           # Docker Engine 24+
docker compose version     # Compose v2.x
timedatectl                # 'System clock synchronized: yes'
```

> **Cortafuegos del anfitrión:** permite solo `443/tcp` (servicio), `80/tcp` (redirección y, si
> aplica, desafío ACME de Let's Encrypt) y tu puerto de administración (p. ej. SSH). **Nunca**
> expongas el `8000` ni el `3306`: con este stack no se publican fuera de la red interna de Docker.

---

## 2. Obtener el código en el servidor

```bash
sudo mkdir -p /srv && cd /srv
git clone <URL-del-repositorio> passwd
cd /srv/passwd
```

A partir de aquí, **todos los comandos se ejecutan desde `/srv/passwd`** (la raíz del repo), donde
están los `docker-compose*.yml` y la carpeta `infrastructure/`.

---

## 3. Generar los certificados TLS

HTTPS es **obligatorio**: las cookies de sesión llevan el atributo `Secure` y sin TLS el navegador
las descarta (no podrías iniciar sesión). nginx lee **siempre** los mismos dos archivos —
`infrastructure/nginx/certs/fullchain.pem` y `privkey.pem` — sea cual sea su origen. Elige **una**
de las tres opciones según tu laboratorio.

> Decide ahora el valor de `PASSWD_DOMAIN` (IP o hostname con el que entrarán los clientes), porque
> debe coincidir con el certificado **y** con el `.env` del paso 5.

### Opción A — CA interna propia (recomendada para pre-producción)

Genera tu propia autoridad, firma el certificado del servidor y produce un `ca.crt` para distribuir.
Una vez instalada la CA en los clientes, la intranet entra **sin avisos del navegador** (lo más
parecido a producción). Reemplaza `192.168.1.50` por la **IP o hostname real** del servidor:

```bash
./infrastructure/nginx/generar-ca-interna.sh 192.168.1.50
```

Esto crea:
- `infrastructure/nginx/certs/fullchain.pem` (servidor + CA) y `privkey.pem` → los usa nginx.
- `infrastructure/nginx/certs/ca.crt` → **la raíz a DISTRIBUIR** e instalar en cada cliente.
- `infrastructure/nginx/ca/ca.key` → clave privada de la CA (queda fuera de git; **custódiala**).

Instala `ca.crt` como **entidad de certificación raíz de confianza** en los equipos que accederán:
- **Windows:** `certlm.msc` → *Entidades de certificación raíz de confianza* → Importar.
- **macOS:** Llavero → *Sistema* → importar `ca.crt` → *Confiar siempre*.
- **Linux:** copiar a `/usr/local/share/ca-certificates/` y `sudo update-ca-certificates`.
- **Firefox:** usa su propio almacén (Ajustes → Certificados → Importar).

### Opción B — Autofirmado por IP (la más rápida, con aviso del navegador)

Para una prueba veloz; el navegador mostrará una advertencia que hay que aceptar:

```bash
./infrastructure/nginx/generar-cert-ip.sh 192.168.1.50
```

Mete la IP en el SAN como `IP:` (lo correcto al entrar por dirección). Para un **hostname** interno:
`./infrastructure/nginx/generar-cert-ip.sh passwd-preprod.interno`.

> Usa este script (`generar-cert-ip.sh`), **no** `generar-cert-autofirmado.sh`, salvo que entres por
> `localhost`. Las cookies `Secure` viajan igual de bien sobre un HTTPS autofirmado.

### Opción C — Let's Encrypt (solo si el servidor es accesible desde Internet)

Requiere que `PASSWD_DOMAIN` resuelva públicamente al servidor y el **puerto 80 abierto** a Internet.
Procedimiento completo (emisión inicial + renovación automática con el overlay
`docker-compose.certbot.yml`) en [`guia-nginx-tls.md`](guia-nginx-tls.md) §4. Si no tienes dominio
pero sí IP pública, puedes usar un hostname `sslip.io`/`nip.io`.

### Comprobar los certificados generados

```bash
ls -l infrastructure/nginx/certs/                 # fullchain.pem y privkey.pem presentes
openssl x509 -in infrastructure/nginx/certs/fullchain.pem -noout -subject -dates -ext subjectAltName
```

Confirma que el **SAN** contiene la IP/hostname que pondrás en `PASSWD_DOMAIN` y que las fechas son
correctas. Los `.pem`/`.crt`/`ca/` están en `.gitignore`: **nunca se versionan**.

---

## 4. Generar las claves criptográficas

En pre-producción las claves se **fijan** en el `.env` (no se autogeneran). Motivo: con MySQL, si el
volumen de datos se pierde o escalas a varias réplicas, **todo lo cifrado quedaría ilegible**.
Genera un par **único de preprod** (distinto del de prod):

```bash
python3 - <<'EOF'
import secrets
from cryptography.fernet import Fernet
print("PASSWD_SECRET_KEY=" + secrets.token_urlsafe(48))
print("PASSWD_ENCRYPTION_KEY=" + Fernet.generate_key().decode())
EOF
```

> Si el servidor no tiene Python con `cryptography`, genera las claves dentro de un contenedor:
> `docker run --rm python:3.12-slim sh -c "pip -q install cryptography >/dev/null 2>&1; python -c 'import secrets;from cryptography.fernet import Fernet;print(\"PASSWD_SECRET_KEY=\"+secrets.token_urlsafe(48));print(\"PASSWD_ENCRYPTION_KEY=\"+Fernet.generate_key().decode())'"`

Copia ambas líneas: las pegarás en el `.env` en el paso siguiente.

⚠️ **Perder `PASSWD_ENCRYPTION_KEY` = perder todas las contraseñas guardadas** (el respaldo cifrado
con frase es el único camino de recuperación). Custodia copia de ambas claves en el gestor de
secretos corporativo o en sobre sellado.

---

## 5. Configurar el archivo `.env`

Copia la **plantilla de pre-producción** a `.env` y endurece sus permisos:

```bash
cp .env.preproduccion.example .env
chmod 600 .env
nano .env        # o tu editor preferido
```

Edita los siguientes bloques. Compose lee este `.env` tanto para las variables del contenedor
(`env_file: .env`) como para interpolar `${PASSWD_DOMAIN}` y `${MYSQL_PASSWORD}`.

### 5.1 Identidad y administrador inicial

```ini
PASSWD_DOMAIN=192.168.1.50               # MISMO valor que el certificado del paso 3

PASSWD_ADMIN_USERNAME=admin
PASSWD_ADMIN_EMAIL=admin-preprod@empresa.tld
PASSWD_ADMIN_PASSWORD=CAMBIAR-Preprod-Unico-2026!   # de un solo uso; se cambia al primer acceso
```

El administrador inicial **solo** se crea si la base de datos está vacía. Tras el primer acceso
(paso 9) **retiraremos** `PASSWD_ADMIN_PASSWORD` del `.env`.

### 5.2 Claves criptográficas (las del paso 4)

```ini
PASSWD_SECRET_KEY=<pega aquí la generada>
PASSWD_ENCRYPTION_KEY=<pega aquí la generada>
```

### 5.3 Base de datos MySQL

```ini
MYSQL_PASSWORD=una_clave_fuerte_y_unica_de_preprod
```

- **Sin `#` delante** y **sin espacios** alrededor del `=` (el overlay de MySQL falla a propósito si
  falta, con un mensaje claro).
- No necesitas tocar `PASSWD_DATABASE_URL`: el overlay la construye automáticamente apuntando al
  servicio `db` (`mysql+pymysql://passwd:${MYSQL_PASSWORD}@db:3306/passwd`).

### 5.4 Sesiones, cuentas y auditoría (réplica de prod — dejar como vienen)

```ini
PASSWD_COOKIE_SECURE=true            # OBLIGATORIO: estamos detrás de HTTPS
PASSWD_SESSION_IDLE_MINUTES=15
PASSWD_SESSION_MAX_HOURS=8
PASSWD_AUDIT_RETENTION_DAYS=365
PASSWD_ROTATION_MAX_DAYS=90
PASSWD_TOTP_ISSUER=passwd-PREPROD    # distínguelo en la app autenticadora
```

> **Nunca** pongas `PASSWD_COOKIE_SECURE=false` aquí: como hay TLS, las cookies deben ser `Secure` y
> con ello se activa además HSTS.

### 5.5 Notificaciones por correo (SMTP) — se detalla en el paso 6

La plantilla ya trae las variables SMTP; las **configuramos y probamos** en el paso 6.

### 5.6 Frase de respaldo

```ini
PASSWD_BACKUP_PASSPHRASE=frase_larga_y_unica_para_respaldos_preprod
```

Mínimo 12 caracteres. Custódiala **fuera del servidor**: sin ella los respaldos son irrecuperables.

---

## 6. Configurar y verificar la conexión con el SMTP

Las **alertas por correo** (cuenta bloqueada, posible exfiltración, alta de usuario, fallo de
respaldo) son *opt-in*. Los mensajes **nunca** contienen contraseñas ni secretos: solo el hecho y su
contexto. En pre-producción las activamos para **validar el envío** antes de prod.

### 6.1 Variables SMTP en `.env`

```ini
PASSWD_NOTIFY_ENABLED=true
PASSWD_SMTP_HOST=smtp.empresa.tld
PASSWD_SMTP_PORT=587
PASSWD_SMTP_USER=passwd-alertas-preprod@empresa.tld
PASSWD_SMTP_PASSWORD=clave_del_buzon_smtp
PASSWD_SMTP_FROM=passwd-alertas-preprod@empresa.tld
PASSWD_SMTP_TLS=true
PASSWD_NOTIFY_TO=equipo-preprod@empresa.tld     # varios: separados por coma
```

| Variable                | Notas                                                                            |
|-------------------------|----------------------------------------------------------------------------------|
| `PASSWD_NOTIFY_ENABLED` | `true` para enviar; si es `false`, nada se envía aunque el resto esté configurado.|
| `PASSWD_SMTP_HOST`      | Host del relay/servidor SMTP.                                                     |
| `PASSWD_SMTP_PORT`      | **`587` (STARTTLS)** recomendado, o `25` interno sin cifrar. Ver aviso del 465.   |
| `PASSWD_SMTP_USER`      | Usuario de autenticación. Si lo dejas vacío, se envía **sin** `login` (relay abierto interno). |
| `PASSWD_SMTP_PASSWORD`  | Secreto del buzón.                                                                |
| `PASSWD_SMTP_FROM`      | Remitente; si se omite, se usa `PASSWD_SMTP_USER`.                                |
| `PASSWD_SMTP_TLS`       | `true` ⇒ STARTTLS sobre el puerto indicado.                                       |
| `PASSWD_NOTIFY_TO`      | Destinatarios separados por coma.                                                 |

> ⚠️ **Puerto 587/STARTTLS, no 465/SSL implícito.** La app usa `SMTP` + `starttls()`
> (ver [`app/notifications.py`](../app/notifications.py)), por lo que **no** soporta el modo SMTPS
> implícito del puerto 465. Usa **587 con `PASSWD_SMTP_TLS=true`** (STARTTLS) o, en una red interna
> de confianza, **25 con `PASSWD_SMTP_TLS=false`**.

> **Certificado del propio SMTP:** STARTTLS valida el certificado del servidor de correo con las CA
> del sistema (`ssl.create_default_context()`). Si tu SMTP usa un certificado de **CA interna o
> autofirmado**, el envío fallará por verificación TLS; usa un SMTP con certificado de confianza o el
> puerto 25 sin TLS dentro de la red de laboratorio.

### 6.2 Probar el envío end-to-end

La forma más limpia de validar el SMTP es **después** de arrancar el stack (paso 8), invocando la
función real de alertas dentro del contenedor de la app:

```bash
docker compose -f docker-compose.yml -f docker-compose.frontend.yml -f docker-compose.mysql.yml \
  exec app python -c "from app.notifications import enviar_alerta; \
  print('OK: correo enviado' if enviar_alerta('Prueba SMTP preprod', \
  'Mensaje de prueba del despliegue de pre-produccion.') else 'NO enviado: revise PASSWD_NOTIFY_* y SMTP')"
```

- **`OK: correo enviado`** → revisa la bandeja de `PASSWD_NOTIFY_TO`; el SMTP está bien.
- **`NO enviado`** → falta `PASSWD_NOTIFY_ENABLED=true`, `PASSWD_SMTP_HOST` o `PASSWD_NOTIFY_TO`, o el
  envío lanzó una excepción (el fallo se registra en los logs de la app: `docker compose ... logs app`).

> El envío es de **mejor esfuerzo**: un fallo de SMTP se registra pero nunca rompe la aplicación. Por
> eso conviene esta prueba explícita en lugar de confiar en que «ya funcionará».

Más adelante (paso 11) provocaremos una alerta **real** (un alta de usuario) para confirmar el
circuito completo de notificaciones.

---

## 7. Revisión previa al arranque (checklist)

Antes de levantar nada, confirma:

- [ ] `infrastructure/nginx/certs/fullchain.pem` y `privkey.pem` existen (paso 3).
- [ ] El SAN del certificado coincide con `PASSWD_DOMAIN`.
- [ ] `.env` con permisos `600`, `PASSWD_DOMAIN`, `PASSWD_ADMIN_*`, claves cripto fijadas.
- [ ] `MYSQL_PASSWORD` definido (sin `#`, sin espacios).
- [ ] `PASSWD_COOKIE_SECURE=true`.
- [ ] Variables SMTP completas si vas a usar notificaciones.
- [ ] NTP activo y puertos 80/443 abiertos en el cortafuegos.

---

## 8. Arrancar el stack

Desde `/srv/passwd`:

```bash
docker compose -f docker-compose.yml \
               -f docker-compose.frontend.yml \
               -f docker-compose.mysql.yml up -d --build
```

La primera vez tarda (construye las imágenes de `app` y `frontend` y descarga MySQL/nginx). Sigue el
progreso y comprueba el estado:

```bash
docker compose -f docker-compose.yml -f docker-compose.frontend.yml -f docker-compose.mysql.yml ps
docker compose -f docker-compose.yml -f docker-compose.frontend.yml -f docker-compose.mysql.yml logs -f app
```

Espera a que `db` quede *healthy* (la `app` arranca solo entonces, por su `depends_on`) y a que `app`
reporte *healthy*. Para abreviar los comandos siguientes, puedes definir un alias en la sesión:

```bash
alias dc='docker compose -f docker-compose.yml -f docker-compose.frontend.yml -f docker-compose.mysql.yml'
dc ps        # ahora basta con esto
```

> El esquema de la base de datos se crea **automáticamente** al arrancar la app (no hace falta
> `init-db` a mano).

---

## 9. Verificación posterior al despliegue (smoke test)

Sustituye `DOM` por tu `PASSWD_DOMAIN`. Con certificado autofirmado/CA aún no instalada en el
servidor, añade `-k` a `curl` para saltarte la validación **en estas pruebas locales**.

```bash
DOM=192.168.1.50

# 1) Salud del backend a través de nginx
curl -sk https://$DOM/healthz                       # {"estado":"ok","version":"..."}

# 2) Redirección HTTP -> HTTPS
curl -sI http://$DOM | grep -i location             # Location: https://...

# 3) HSTS y cabeceras de seguridad presentes
curl -skI https://$DOM/login | grep -iE "strict-transport-security|content-security-policy|x-frame-options"

# 4) Solo TLS 1.2/1.3 (TLS 1.0 debe ser RECHAZADO)
openssl s_client -connect $DOM:443 -tls1   </dev/null 2>&1 | grep -qi "alert\|handshake failure\|no protocols" \
  && echo "TLS1.0 rechazado (correcto)"

# 5) Docs de la API deshabilitadas (debe dar 404)
curl -sk -o /dev/null -w "%{http_code}\n" https://$DOM/docs       # 404
```

Abre por último `https://<PASSWD_DOMAIN>` en un navegador. Con la **CA interna instalada** (opción A)
debe cargar **sin advertencias**; con autofirmado, acepta el aviso (esperado en laboratorio).

---

## 10. Primer acceso y configuración inicial

1. Entra en `https://<PASSWD_DOMAIN>` con `PASSWD_ADMIN_USERNAME` / `PASSWD_ADMIN_PASSWORD`.
2. El sistema **fuerza el cambio de contraseña** (la inicial es de un solo uso).
3. **Enrola MFA**: escanea el QR con tu app autenticadora y confirma el código. **Guarda los 8
   códigos de recuperación** que se muestran una sola vez.
4. Crea el resto de usuarios de prueba desde **Usuarios** (cada uno pasará por cambio de contraseña +
   MFA en su primer ingreso). Asigna el menor rol necesario (operador, auditor, analista).
5. **Retira la contraseña inicial del `.env`** (ya solo se usaría si la BD estuviera vacía) y reinicia
   la app para aplicarlo:

   ```bash
   sed -i 's/^PASSWD_ADMIN_PASSWORD=.*/# PASSWD_ADMIN_PASSWORD= (retirada tras el primer acceso)/' .env
   dc up -d        # recrea la app con el .env actualizado
   ```

Confirma en **/auditoria** (o la sección de auditoría del frontend) que el login con MFA registró la
**IP real del cliente** (no una IP interna de Docker `172.x`). Si ves una IP de contenedor, revisa
que estás entrando por nginx (no directo a la app).

---

## 11. Confirmar el circuito de alertas SMTP (prueba real)

Más allá de la prueba directa del paso 6.2, valida una alerta **provocada por un evento**:

- **Alta de usuario:** crea un usuario nuevo desde **Usuarios** → debe llegar un correo de aviso a
  `PASSWD_NOTIFY_TO`.
- **Cuenta bloqueada:** falla 5 veces el login de un usuario de prueba → alerta de bloqueo.

Si los correos del paso 6.2 llegaban pero estos no, revisa que `PASSWD_NOTIFY_ENABLED=true` siga en el
`.env` **aplicado** al contenedor (`dc up -d` tras cualquier cambio del `.env`).

---

## 12. Respaldos cifrados programados

Valida el procedimiento de respaldo en preprod **antes** de confiarlo a producción. La frase se toma
de `PASSWD_BACKUP_PASSPHRASE` (paso 5.6), así que el cron es desatendido:

```bash
# /etc/cron.d/passwd-preprod-respaldo
30 2 * * * root cd /srv/passwd && docker compose -f docker-compose.yml -f docker-compose.frontend.yml -f docker-compose.mysql.yml exec -T app \
  python -m app.cli respaldo --salida /srv/passwd/data/respaldo-$(date +\%F).passwd --retener 30
```

- `--retener 30` conserva los 30 respaldos `*.passwd` más recientes y poda el resto.
- Copia el archivo a un destino **externo** al servidor (NAS/remoto), p. ej. añadiendo al cron
  `&& rsync -a /srv/passwd/data/respaldo-*.passwd usuario@nas:/respaldos/`.
- **Prueba de restauración** (en una máquina aparte) para cerrar el ciclo:

  ```bash
  dc exec app python -m app.cli restaurar --entrada /srv/passwd/data/respaldo-AAAA-MM-DD.passwd --sobrescribir
  ```

  Una frase incorrecta o un archivo manipulado → falla **sin tocar** los datos (lo detecta el HMAC de
  Fernet). Detalle de la CLI en [`referencia-cli.md`](referencia-cli.md).

---

## 13. Operación y mantenimiento

### 13.1 Comandos del día a día

Con el alias `dc` del paso 8:

```bash
dc ps                     # estado de los servicios
dc logs -f app            # logs del backend (incluye fallos de SMTP)
dc logs -f nginx          # logs del proxy TLS
dc restart app            # reiniciar solo la app
dc down                   # detener el stack (conserva volúmenes/datos)
dc up -d --build          # aplicar cambios de código/.env
```

### 13.2 Rotación de certificados (sin caída)

nginx siempre lee `fullchain.pem` y `privkey.pem`, así que rotar es siempre lo mismo: reemplazar esos
dos archivos y recargar en caliente. Reutiliza el script del paso 3 (regenera por IP/CA) o coloca los
nuevos `.pem`, y luego:

```bash
dc exec nginx nginx -t            # validar configuración
dc exec nginx nginx -s reload     # recargar SIN cortar conexiones
```

Procedimiento completo y vigilancia de caducidad en [`guia-nginx-tls.md`](guia-nginx-tls.md) §6.

### 13.3 Actualizar el sistema

```bash
cd /srv/passwd
dc exec app python -m app.cli respaldo --salida data/pre-actualizacion.passwd   # respaldo previo SIEMPRE
git pull
dc up -d --build
curl -sk https://$DOM/healthz
```

Reversión: vuelve al commit anterior, `dc up -d --build` y, solo si hubo corrupción de datos,
restaura `pre-actualizacion.passwd`.

---

## 14. Resolución de problemas

| Síntoma                                             | Causa probable                                  | Solución                                                                                 |
|----------------------------------------------------|-------------------------------------------------|------------------------------------------------------------------------------------------|
| `nginx ... cannot load certificate`                | Faltan o están mal nombrados los `.pem`         | Regenera con los scripts del paso 3; deben ser `fullchain.pem` y `privkey.pem`.          |
| No carga / Compose pide `MYSQL_PASSWORD`           | Variable comentada o con espacios               | En `.env`: `MYSQL_PASSWORD=...` sin `#` y sin espacios alrededor del `=`.                 |
| No puedo iniciar sesión (la cookie no se guarda)   | Sin HTTPS o `PASSWD_COOKIE_SECURE=false`        | Entra por `https://`; deja `PASSWD_COOKIE_SECURE=true`.                                   |
| La auditoría registra una IP `172.x` de Docker     | Entrando directo a la app, no por nginx          | Accede por `https://<PASSWD_DOMAIN>` (puerto 443); la app va con `--proxy-headers`.       |
| Navegador: «certificado no confiable»              | Autofirmado, o CA interna no instalada           | Instala `ca.crt` (opción A) en los clientes, o acepta el aviso en pruebas.                |
| SMTP: `NO enviado` en la prueba 6.2                | `NOTIFY_ENABLED`/`HOST`/`NOTIFY_TO` ausentes     | Complétalos y reaplica con `dc up -d`; mira `dc logs app` para la excepción exacta.       |
| SMTP falla con error de TLS/handshake              | Puerto 465 (SSL implícito) o cert. de CA interna | Usa 587 + STARTTLS con cert. de confianza, o 25 sin TLS en red interna.                   |
| `db` no llega a *healthy*                           | Primer arranque lento / clave cambiada           | `dc logs db`; si cambiaste `MYSQL_PASSWORD` tras crear el volumen, ver nota abajo.        |

> **Cambiar `MYSQL_PASSWORD` después del primer arranque** no reconfigura un volumen MySQL ya
> inicializado. En laboratorio, lo más simple es recrearlo (⚠️ **borra los datos de la BD**):
> `dc down && docker volume rm passwd_datos-mysql && dc up -d --build`. Haz un respaldo antes si hay
> datos que conserves.

---

## 15. Checklist final de aceptación de pre-producción

- [ ] Certificados generados y (opción A) `ca.crt` distribuido a los clientes.
- [ ] `.env` de preprod con claves **únicas**, `MYSQL_PASSWORD` y `PASSWD_COOKIE_SECURE=true`.
- [ ] Stack arriba: `app`, `frontend`, `nginx` y `db` *healthy*.
- [ ] `/healthz` responde `ok`; redirección 80→443; HSTS y CSP presentes; `/docs` da 404.
- [ ] Primer admin con contraseña cambiada y MFA enrolado; códigos de recuperación custodiados.
- [ ] `PASSWD_ADMIN_PASSWORD` retirada del `.env` y app reiniciada.
- [ ] SMTP probado (paso 6.2) **y** alerta real recibida (paso 11).
- [ ] Respaldo cifrado generado, copiado fuera del servidor y **restaurado** con éxito en prueba.
- [ ] Auditoría registrando la **IP real** del cliente.

Superado este checklist, el entorno replica producción y queda listo para las pruebas de aceptación
(UAT) descritas en [`guia-implementacion.md`](guia-implementacion.md) §3.4 antes del paso a prod.

---

## Documentos relacionados

- [`ambientes.md`](ambientes.md) — plantillas por ambiente y TLS sin dominio (por IP).
- [`guia-nginx-tls.md`](guia-nginx-tls.md) — HTTPS, certificados y rotación sin caída (detalle).
- [`referencia-configuracion.md`](referencia-configuracion.md) — todas las variables `PASSWD_*`.
- [`referencia-cli.md`](referencia-cli.md) — `respaldo`, `restaurar`, `crear-admin`, `init-db`.
- [`guia-implementacion.md`](guia-implementacion.md) — plan de pruebas (UAT) y operación continua.
</content>
</invoke>
