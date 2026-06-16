# Guía de HTTPS con nginx y gestión de certificados

**Sistema:** Gestor de Contraseñas de Servidores
**Objetivo:** publicar la aplicación de forma totalmente cifrada (HTTPS) con nginx como
proxy de terminación TLS, y dejar documentada la **rotación de certificados** para que
renovarlos en el futuro sea una operación rutinaria y sin caídas.

> ¿Por qué es obligatorio? Las cookies de sesión se emiten con el atributo `Secure`: sin
> HTTPS el navegador las descarta y no se puede iniciar sesión. Además, todo el tráfico
> (contraseñas reveladas/copiadas, códigos MFA) debe viajar cifrado.

---

## 1. Cómo encaja en la arquitectura

```
Cliente ──HTTPS/443──> nginx (TLS)  ──HTTP interno──> app:8000 (uvicorn)
            ▲   redirección 80→443       red Docker "red-passwd"
            │
        Certificados en infrastructure/nginx/certs/{fullchain,privkey}.pem
```

- nginx termina TLS y reenvía a la app por la red interna de Docker; **la app deja de
  publicarse en el host** (con el override de nginx, `ports: !reset []`): el único punto de
  entrada es nginx por el puerto 443.
- **IP real del cliente:** nginx **sobrescribe** la cabecera `X-Forwarded-For` con la
  dirección que realmente observa (`$remote_addr`), descartando cualquier valor que el
  cliente intente inyectar. Así la bitácora de auditoría registra la IP verdadera y **no es
  falsificable**. La app se ejecuta con `--proxy-headers --forwarded-allow-ips=*`, seguro
  porque solo nginx puede alcanzarla.
- **Cabeceras de seguridad:** la aplicación ya emite CSP, X-Frame-Options, etc.; nginx es el
  único emisor de **HSTS** (oculta la de la app y fija la suya) para no duplicarla y cubrir
  también sus páginas de error.

### Ficheros de esta solución

| Ruta | Función |
|---|---|
| `docker-compose.nginx.yml` | Añade el servicio nginx y reconfigura la app para ir detrás del proxy |
| `docker-compose.certbot.yml` | (Opcional) renovación automática con Let's Encrypt |
| `infrastructure/nginx/templates/default.conf.template` | Configuración de nginx (TLS endurecido); `${PASSWD_DOMAIN}` se sustituye al arrancar |
| `infrastructure/nginx/certs/` | Aquí van `fullchain.pem` y `privkey.pem` (no se versionan) |
| `infrastructure/nginx/generar-cert-autofirmado.sh` | Certificado autofirmado para pruebas |

### Endurecimiento TLS aplicado (en la plantilla)

- **TLS 1.2 y 1.3 únicamente** (SSLv3, TLS 1.0 y 1.1 deshabilitados).
- Cifradores ECDHE (perfil *intermediate* de Mozilla); sin necesidad de `dhparam`.
- `ssl_session_tickets off`, caché de sesión compartida, **OCSP stapling** (con certificados
  de CA), `server_tokens off` (oculta la versión de nginx).
- **HSTS** `max-age=31536000; includeSubDomains`.
- Límite de tamaño de cuerpo y tiempos de espera de proxy acotados.

---

## 2. Puesta en marcha rápida (PRUEBAS, certificado autofirmado)

### Linux / macOS

```bash
cp .env.example .env          # definir PASSWD_ADMIN_* y PASSWD_DOMAIN (localhost para pruebas)
# Certificado de prueba (CN=localhost):
sh infrastructure/nginx/generar-cert-autofirmado.sh localhost

docker compose -f docker-compose.yml -f docker-compose.nginx.yml up -d --build
```

### Windows (PowerShell)

El script `.sh` no corre nativamente en Windows; use el equivalente PowerShell.
Prefiere el OpenSSL del sistema (el de Git para Windows sirve) y, si no lo
encuentra, ejecuta OpenSSL dentro de un contenedor Docker (sin instalar nada):

```powershell
Copy-Item .env.example .env    # definir PASSWD_ADMIN_* y PASSWD_DOMAIN
powershell -ExecutionPolicy Bypass -File .\infrastructure\nginx\generar-cert-autofirmado.ps1 localhost

docker compose -f docker-compose.yml -f docker-compose.nginx.yml up -d --build
```

Alternativa de una sola línea sin el script (solo Docker, sin OpenSSL local):

```powershell
docker run --rm -v "${PWD}\infrastructure\nginx\certs:/certs" alpine/openssl `
  req -x509 -nodes -newkey rsa:2048 -days 365 `
  -keyout /certs/privkey.pem -out /certs/fullchain.pem `
  -subj "/CN=localhost" -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
```

> Para el stack con el frontend Next.js, sustituya `docker-compose.nginx.yml`
> por `docker-compose.frontend.yml` en el comando `up` (el certificado y su
> ubicación son idénticos).

Abrir `https://localhost`. El navegador advertirá que el certificado no es de confianza
(normal en autofirmados): acéptelo solo en pruebas. Verificación rápida:

```bash
curl -kI https://localhost            # 200 y cabeceras de seguridad
curl -I  http://localhost             # 301 -> https
```

En Windows, el equivalente de `curl` en PowerShell es
`curl.exe -kI https://localhost` (use `curl.exe`, no el alias `Invoke-WebRequest`).

---

## 3. Producción A — Certificado de una CA interna o comercial (lo más común)

Para un sistema interno de inventario, lo habitual es un certificado emitido por la **CA
corporativa** (o un comercial). Procedimiento:

1. Definir el dominio real en `.env`:
   ```ini
   PASSWD_DOMAIN=passwd.su-organizacion.tld
   ```
2. Obtener de la CA dos ficheros y colocarlos en `infrastructure/nginx/certs/`:
   - **`fullchain.pem`** — el certificado del servidor **seguido de la cadena de
     intermedios** (en ese orden). Sin la cadena, algunos clientes fallan y el OCSP stapling
     no funciona.
   - **`privkey.pem`** — la clave privada (sin frase de paso).
   ```bash
   install -m 644 su-certificado-con-cadena.pem infrastructure/nginx/certs/fullchain.pem
   install -m 600 su-clave-privada.pem          infrastructure/nginx/certs/privkey.pem
   ```
3. Levantar:
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.nginx.yml up -d --build
   ```
4. Verificar (ver §5).

> Si la CA entrega el certificado y la cadena por separado, concaténelos en este orden:
> `cat servidor.crt intermedios.crt > fullchain.pem`.

---

## 4. Producción B — Let's Encrypt (si el servidor es accesible desde Internet)

Requiere que `PASSWD_DOMAIN` resuelva públicamente al servidor y el **puerto 80 abierto**
(para el desafío ACME por webroot).

### 4.1 Emisión inicial

```bash
# 1. Arrancar primero con un certificado autofirmado temporal para que nginx levante:
sh infrastructure/nginx/generar-cert-autofirmado.sh "$PASSWD_DOMAIN"
docker compose -f docker-compose.yml -f docker-compose.nginx.yml up -d

# 2. Emitir el certificado real validando por webroot (sustituya el correo):
docker compose -f docker-compose.yml -f docker-compose.nginx.yml -f docker-compose.certbot.yml \
  run --rm certbot certbot certonly --webroot -w /var/www/certbot \
  -d "$PASSWD_DOMAIN" --email admin@su-organizacion.tld --agree-tos --no-eff-email

# 3. Copiar el certificado emitido a la ruta que lee nginx y recargar:
docker compose -f docker-compose.yml -f docker-compose.nginx.yml -f docker-compose.certbot.yml \
  run --rm --entrypoint sh certbot -c \
  "cp /etc/letsencrypt/live/$PASSWD_DOMAIN/fullchain.pem /certs/fullchain.pem && \
   cp /etc/letsencrypt/live/$PASSWD_DOMAIN/privkey.pem /certs/privkey.pem"
docker compose -f docker-compose.yml -f docker-compose.nginx.yml exec nginx nginx -s reload
```

### 4.2 Renovación automática

Levante todo incluyendo el servicio `certbot`, que renueva en bucle y, al renovar, copia los
certificados a la ruta de nginx mediante un *deploy-hook*:

```bash
docker compose -f docker-compose.yml -f docker-compose.nginx.yml -f docker-compose.certbot.yml up -d
```

nginx debe recargarse para tomar el certificado renovado. Programe una recarga periódica
(los certificados de Let's Encrypt duran 90 días; recargar a diario es inofensivo):

```bash
# /etc/cron.d/passwd-nginx-reload
0 3 * * * root cd /srv/passwd && docker compose -f docker-compose.yml -f docker-compose.nginx.yml exec -T nginx nginx -s reload
```

---

## 5. Verificación

```bash
DOM=passwd.su-organizacion.tld   # o localhost en pruebas (añada -k a curl)

# Redirección HTTP -> HTTPS
curl -I http://$DOM                       # HTTP/1.1 301 ... Location: https://...

# HSTS y cabeceras presentes
curl -sI https://$DOM | grep -iE "strict-transport-security|content-security-policy"

# Solo TLS 1.2/1.3 (TLS 1.0 debe ser RECHAZADO)
openssl s_client -connect $DOM:443 -tls1   </dev/null 2>&1 | grep -i "no protocols\|alert\|handshake failure" && echo "TLS1.0 rechazado (correcto)"
openssl s_client -connect $DOM:443 -tls1_2 </dev/null 2>&1 | grep -i "Protocol\|Cipher" | head -2

# Fecha de caducidad del certificado en servicio
echo | openssl s_client -connect $DOM:443 -servername $DOM 2>/dev/null | openssl x509 -noout -dates -subject -issuer
```

Comprobación funcional: iniciar sesión completo (contraseña + MFA) y confirmar en
`/auditoria` que el evento registra la **IP real del cliente** (no la de un contenedor).

---

## 6. Rotación / cambio de certificados en el futuro

El diseño hace que **toda** rotación sea el mismo procedimiento, porque nginx siempre lee
los mismos dos ficheros (`fullchain.pem` y `privkey.pem`):

### 6.1 Procedimiento general (CA interna o comercial) — sin caída

```bash
cd /srv/passwd
CERTS=infrastructure/nginx/certs

# 1. Respaldar los actuales por si hay que revertir
cp $CERTS/fullchain.pem $CERTS/fullchain.pem.bak
cp $CERTS/privkey.pem   $CERTS/privkey.pem.bak

# 2. Colocar los nuevos (mismos nombres)
install -m 644 nuevo-fullchain.pem $CERTS/fullchain.pem
install -m 600 nuevo-privkey.pem   $CERTS/privkey.pem

# 3. Validar la configuración ANTES de aplicar y recargar SIN cortar conexiones
docker compose -f docker-compose.yml -f docker-compose.nginx.yml exec nginx nginx -t
docker compose -f docker-compose.yml -f docker-compose.nginx.yml exec nginx nginx -s reload

# 4. Verificar la nueva fecha de caducidad (§5). Si todo está bien, borrar los .bak
```

`nginx -s reload` aplica el nuevo certificado **sin reiniciar** ni cerrar las sesiones en
curso (recarga en caliente). Si algo falla, restaure los `.bak` y recargue de nuevo.

### 6.2 Let's Encrypt

La renovación es automática (§4.2). Para forzarla puntualmente:

```bash
docker compose -f docker-compose.yml -f docker-compose.nginx.yml -f docker-compose.certbot.yml \
  run --rm certbot certbot renew --force-renewal
docker compose -f docker-compose.yml -f docker-compose.nginx.yml exec nginx nginx -s reload
```

### 6.3 Rotar también la clave privada (recomendado en cada renovación)

Genere siempre la nueva clave al pedir el certificado (no reutilice `privkey.pem`). Con
Let's Encrypt esto es el comportamiento por defecto; con una CA, solicite el certificado a
partir de un CSR con clave nueva.

### 6.4 Buenas prácticas de vigilancia

- **Alerta de caducidad:** monitoree los días restantes y avise con ≥ 30 días de margen.
  ```bash
  # Devuelve 1 si caduca en menos de 30 días (úselo en un cron con notificación)
  DOM=passwd.su-organizacion.tld
  fin=$(echo | openssl s_client -connect $DOM:443 -servername $DOM 2>/dev/null | openssl x509 -noout -enddate | cut -d= -f2)
  fin_ts=$(date -d "$fin" +%s); ahora=$(date +%s)
  [ $(( (fin_ts - ahora) / 86400 )) -lt 30 ] && echo "ATENCIÓN: el certificado caduca pronto"
  ```
- Custodie la clave privada con permisos `600` y nunca la versione (ya está en `.gitignore`).
- Tras cualquier sospecha de compromiso de la clave, **revoque** el certificado en la CA y
  emita uno nuevo con clave nueva.

---

## 7. Resolución de problemas

| Síntoma | Causa probable | Solución |
|---|---|---|
| nginx no arranca: `cannot load certificate` | Faltan los `.pem` o están mal nombrados | Coloque `fullchain.pem` y `privkey.pem` en `infrastructure/nginx/certs/` (§3) |
| `nginx -t` da `[emerg] ... [::]` | Host sin IPv6 | La plantilla es IPv4 por defecto; no añada `listen [::]` salvo que tenga doble pila |
| Navegador: «certificado no confiable» | Certificado autofirmado o falta la cadena de intermedios | En producción use CA/Let's Encrypt y concatene la cadena en `fullchain.pem` |
| La auditoría registra una IP de Docker (172.x) | La app no recibe las cabeceras de reenvío | Use el override de nginx (incluye `--proxy-headers`); no exponga la app directamente |
| `aviso ssl_stapling ignored` | Certificado autofirmado (sin emisor OCSP) | Normal en pruebas; desaparece con un certificado de CA |
| Cambié el certificado pero sigue el viejo | nginx no recargó | `docker compose ... exec nginx nginx -s reload` |
| Quiero IPv6 (doble pila) | — | Añada `listen [::]:80;` y `listen [::]:443 ssl;` a la plantilla y recree el contenedor nginx |

---

## 8. Resumen de comandos

```bash
# Pruebas (autofirmado) — Linux/macOS
sh infrastructure/nginx/generar-cert-autofirmado.sh localhost
docker compose -f docker-compose.yml -f docker-compose.nginx.yml up -d --build

# Pruebas (autofirmado) — Windows PowerShell
#   powershell -ExecutionPolicy Bypass -File .\infrastructure\nginx\generar-cert-autofirmado.ps1 localhost
#   docker compose -f docker-compose.yml -f docker-compose.nginx.yml up -d --build

# Producción (CA): colocar certs en infrastructure/nginx/certs/ y:
docker compose -f docker-compose.yml -f docker-compose.nginx.yml up -d --build

# Producción (Let's Encrypt, con renovación automática)
docker compose -f docker-compose.yml -f docker-compose.nginx.yml -f docker-compose.certbot.yml up -d

# Rotar certificado (sin caída)
docker compose -f docker-compose.yml -f docker-compose.nginx.yml exec nginx nginx -t
docker compose -f docker-compose.yml -f docker-compose.nginx.yml exec nginx nginx -s reload
```
