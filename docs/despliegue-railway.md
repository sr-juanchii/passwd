# Desplegar TODO el proyecto en Railway (backend + frontend + BD)

Railway permite tener las tres piezas en **un mismo proyecto** con servicios
separados, build por Dockerfile y red privada entre ellos:

```
Proyecto Railway
├── 🗄️  Base de datos (plugin MySQL o PostgreSQL — persistente)
├── ⚙️  backend   (FastAPI; usa railway.json de la raíz + Dockerfile)
└── 🖥️  frontend  (Next.js; Root Directory = frontend, usa frontend/railway.json)
```

El repo ya trae la configuración:
- `railway.json` (raíz): servicio **backend** (Dockerfile, `$PORT`, `--proxy-headers`,
  healthcheck `/healthz`, `PASSWD_DATABASE_URL` cableado al plugin MySQL,
  `PASSWD_COOKIE_SECURE=true`, `PASSWD_RATE_LIMIT_BACKEND=bd`).
- `frontend/railway.json` + `frontend/Dockerfile`: servicio **frontend** (build
  standalone; acepta `PASSWD_API_BASE` / `NEXT_PUBLIC_API_BASE` como build args).

## 1. Crear el proyecto y la base de datos

1. Railway → **New Project → Deploy from GitHub repo** → elige `sr-juanchii/passwd`.
   Railway detecta `railway.json` y crea el servicio **backend**.
2. En el proyecto: **New → Database → Add MySQL** (el `railway.json` ya mapea
   `PASSWD_DATABASE_URL` a `${{MYSQLUSER}}…`). *(Alternativa PostgreSQL: añade
   Postgres y cambia esa variable a `postgresql://${{PGUSER}}:${{PGPASSWORD}}@${{PGHOST}}:${{PGPORT}}/${{PGDATABASE}}` — el backend ya soporta ambos.)*

## 2. Configurar el backend

En el servicio **backend → Variables**, define (las demás ya vienen del `railway.json`):

```
PASSWD_ADMIN_USERNAME=admin
PASSWD_ADMIN_EMAIL=admin@tu.tld
PASSWD_ADMIN_PASSWORD=UnaClaveInicialRobusta!
PASSWD_SECRET_KEY=...          # secrets.token_urlsafe(48)
PASSWD_ENCRYPTION_KEY=...      # Fernet.generate_key()  (¡fíjala para no perder lo cifrado!)
```

En **backend → Settings → Networking → Generate Domain** para obtener su URL
pública `https://passwd-backend-xxxx.up.railway.app` (la usará el frontend).
Comprueba `…/healthz` → `{"estado":"ok",…}`.

## 3. Añadir el frontend como segundo servicio

1. **New → GitHub Repo → el mismo repo**.
2. En ese servicio → **Settings → Root Directory = `frontend`** (así usa
   `frontend/railway.json` y `frontend/Dockerfile`).
3. **Variables** del frontend — modo recomendado (**proxy mismo-origen, sin CORS**):
   ```
   PASSWD_API_BASE=https://passwd-backend-xxxx.up.railway.app
   ```
   El frontend (Next) reenvía `/api/web/*` al backend; el navegador ve un único
   origen → cookies de primera parte (`SameSite=Strict`) y **no hace falta CORS**.
   - *Más eficiente (red privada interna):* `PASSWD_API_BASE=http://${{backend.RAILWAY_PRIVATE_DOMAIN}}:${{backend.PORT}}`
     (sustituye `backend` por el nombre real del servicio).
4. **Generate Domain** para el frontend → esa es la URL que abren los usuarios.

> Importante: Next "hornea" la URL del backend en el **build**. Al cambiarla,
> Railway reconstruye el servicio (la variable se pasa como build arg). Si en su
> lugar prefieres llamadas **cross-origin directas**, usa `NEXT_PUBLIC_API_BASE`
> en el frontend y define en el backend `PASSWD_CORS_ORIGINS=https://<frontend>.up.railway.app`
> y `PASSWD_COOKIE_SAMESITE=none`.

## 4. Primer acceso

Abre la URL del frontend → login con el admin inicial → cambio de contraseña
forzado → enrolar MFA. Listo.

## 5. Eficiencia y notas

- **Builds por Dockerfile** (deterministas) en ambos servicios; el frontend usa la
  salida *standalone* de Next (imagen mínima). `.dockerignore`/`.gcloudignore`
  mantienen el contexto pequeño.
- **Red privada** entre frontend y backend (punto 3) evita salida a Internet y es
  más rápida.
- **Persistencia**: la BD vive en el plugin gestionado (no en el contenedor), así
  que los redeploys no pierden datos. Aun así, **fija** `PASSWD_SECRET_KEY` y
  `PASSWD_ENCRYPTION_KEY` por entorno.
- **Rate limit** compartido entre instancias con `PASSWD_RATE_LIMIT_BACKEND=bd`
  (ya incluido en `railway.json`).
- Railway free/trial puede **dormir** servicios por inactividad; el primer acceso
  tras dormir tarda unos segundos.
- Solo-backend (frontend en Vercel/v0): despliega únicamente el servicio backend y
  apunta el frontend externo a su dominio (ver `docs/despliegue-backend-vps.md`).
