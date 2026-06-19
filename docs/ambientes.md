# Ambientes y despliegue (desarrollo · calidad · pre-producción · producción)

Esta guía explica cómo configurar passwd para distintos propósitos usando una
plantilla `.env` por ambiente, y cómo resolver el TLS de nginx **sin dominio**
(red interna por IP).

## 1. Plantillas por ambiente

Solo se versionan las plantillas `*.example`. El `.env` real de cada servidor
**nunca** se versiona (está en `.gitignore`, igual que `.env.<ambiente>`).

| Plantilla | Propósito | BD | Cookies / TLS | Correo |
| --- | --- | --- | --- | --- |
| `.env.desarrollo.example` | Local del desarrollador | SQLite | `COOKIE_SECURE=false`, sin TLS | off |
| `.env.calidad.example` | QA / pruebas funcionales | MySQL (o SQLite) | TLS recomendado | off por defecto |
| `.env.preproduccion.example` | Staging (réplica de prod) | MySQL | TLS (`true`) | on |
| `.env.produccion.example` | Producción | MySQL | TLS (`true`) | on |
| `.env.example` | **Referencia completa** de todas las variables | — | — | — |

## 2. Flujo de despliegue (un servidor por ambiente)

El `docker-compose.yml` carga las variables desde el archivo **`.env`** del
directorio (`env_file: .env`). Por eso el patrón es: en cada servidor, **copia
la plantilla del ambiente a `.env`**, rellena los secretos y despliega.

```bash
# En el servidor de PRODUCCIÓN, por ejemplo:
cp .env.produccion.example .env
nano .env                       # rellena claves, contraseñas, dominio/IP

# Genera y pega las claves cripto (ÚNICAS por ambiente):
python3 -c "import secrets; print('PASSWD_SECRET_KEY='+secrets.token_urlsafe(48))"
python3 -c "from cryptography.fernet import Fernet; print('PASSWD_ENCRYPTION_KEY='+Fernet.generate_key().decode())"

# TLS de nginx (ver sección 4 si no tienes dominio):
./infrastructure/nginx/generar-cert-ip.sh 192.168.1.50

# Arranque (backend + frontend Next + nginx + MySQL):
docker compose -f docker-compose.yml \
               -f docker-compose.frontend.yml \
               -f docker-compose.mysql.yml up -d --build
```

Para calidad o pre-producción, idéntico pero copiando
`.env.calidad.example` / `.env.preproduccion.example`.

Variantes de stack:
- **Solo web Jinja (sin frontend Next):** usa `-f docker-compose.nginx.yml` en
  lugar de `-f docker-compose.frontend.yml`.
- **Sin MySQL (SQLite):** omite `-f docker-compose.mysql.yml`.
- **Desarrollo local:** `cp .env.desarrollo.example .env && docker compose up -d --build`
  (backend en `127.0.0.1:8000`; el frontend se levanta aparte con `pnpm dev`).

## 3. Reglas de oro (multi-ambiente)

- **Claves distintas por ambiente.** Nunca compartas `PASSWD_SECRET_KEY` ni
  `PASSWD_ENCRYPTION_KEY` entre prod/preprod/calidad. Si se filtra una de prod,
  los demás ambientes siguen aislados.
- **Fija las claves en prod/preprod.** Si se dejan vacías se autogeneran en el
  volumen de datos; si ese volumen se pierde o escalas a varias réplicas, **todo
  lo cifrado en MySQL queda ilegible**. En desarrollo/calidad puedes dejarlas
  autogenerar (datos desechables).
- **BD, admin, dominio y destinatarios de correo propios** por ambiente.
- **`PASSWD_COOKIE_SECURE=true`** siempre que haya HTTPS (prod/preprod, y QA si
  va tras TLS). Solo `false` en desarrollo local sin TLS.
- **MySQL ≥ 8.0.16 / MariaDB ≥ 10.2** (restricciones `CHECK`), charset
  `utf8mb4`. El aislamiento `READ COMMITTED` lo fija la app automáticamente.
- **Varias réplicas de la app** contra la misma BD → `PASSWD_RATE_LIMIT_BACKEND=bd`.

## 4. TLS de nginx SIN dominio (red interna por IP)

nginx ya viene configurado para TLS; **no se edita**. Solo necesita los dos
archivos `infrastructure/nginx/certs/{fullchain,privkey}.pem` (se montan en el
contenedor como solo-lectura) y que `PASSWD_DOMAIN` valga la IP/hostname.

### Opción A — Autofirmado para la IP (rápido, con aviso del navegador)

```bash
./infrastructure/nginx/generar-cert-ip.sh 192.168.1.50
# en .env:  PASSWD_DOMAIN=192.168.1.50
```

Abre `https://192.168.1.50` y acepta la advertencia (esperado en autofirmados).
Las cookies `Secure` viajan bien sobre ese HTTPS.

> El script `generar-cert-autofirmado.sh` (existente) sirve para `localhost`;
> usa `generar-cert-ip.sh` cuando entres por **IP** (mete la IP en el SAN como
> `IP:`, lo correcto).

### Opción B — CA interna propia (sin avisos en toda la intranet)

```bash
./infrastructure/nginx/generar-ca-interna.sh 192.168.1.50
# en .env:  PASSWD_DOMAIN=192.168.1.50
```

Genera la CA, firma el cert del servidor y deja `certs/ca.crt`. Distribuye e
instala **`ca.crt`** (nunca la `ca.key`) como entidad raíz de confianza en cada
cliente (Windows `certlm.msc`, macOS Llavero, Linux `update-ca-certificates`,
Firefox almacén propio). Tras eso, `https://192.168.1.50` carga sin advertencias.

### Opción C — Cert público gratis sin comprar dominio

Si el servidor tiene IP pública, usa un hostname tipo `sslip.io`/`nip.io`
(p. ej. `203-0-113-7.sslip.io`) y emite Let's Encrypt con el overlay
`docker-compose.certbot.yml`. Requiere puertos 80/443 accesibles desde Internet.

## 5. Archivos generados que NO se versionan

`.gitignore` ya protege:

- `.env`, `.env.*` (reales) — solo se versionan los `*.example`.
- `infrastructure/nginx/certs/*.pem`, `*.crt`, `*.srl`.
- `infrastructure/nginx/ca/` (incluida la **clave privada de la CA**).
