# Desplegar solo el backend (VPS/PaaS) + frontend en Vercel/v0

Esta guía deja el **backend (API FastAPI) en un servidor propio** y el **frontend
Next.js en Vercel/v0**, para iterar el diseño del frontend contra una API real.

```
Navegador ──HTTPS──>  Vercel/v0 (frontend Next.js)
            │
            └──HTTPS (cross-site, CORS + cookie SameSite=None)──> https://api.tu-dominio  (backend en VPS/PaaS)
```

## 1. Dos formas de conectar frontend y backend

| Modo | Cómo | Cookies | CORS |
|---|---|---|---|
| **Proxy mismo-origen** (más seguro) | El frontend llama a rutas relativas `/api/web/*` y Next reescribe a `PASSWD_API_BASE` (ver `frontend/next.config.ts`). El navegador ve un único origen. | `SameSite=Strict` | No hace falta |
| **Cross-origin directo** (para v0/Vercel + VPS) | El frontend llama al backend por su URL absoluta vía `NEXT_PUBLIC_API_BASE`. | `SameSite=None; Secure` | Sí, en el backend |

Para el caso de esta guía (v0/Vercel + VPS) se usa el **modo cross-origin directo**.

## 2. Variables del backend

Mínimas para producción cross-site (en el `.env` del VPS o en el panel del PaaS):

```bash
PASSWD_ADMIN_USERNAME=admin
PASSWD_ADMIN_EMAIL=admin@tu-organizacion.tld
PASSWD_ADMIN_PASSWORD='UnaClaveInicialRobusta!'

PASSWD_COOKIE_SECURE=true                 # HTTPS obligatorio
PASSWD_COOKIE_SAMESITE=none               # permite la cookie cross-site
PASSWD_CORS_ORIGINS=https://TU-APP.vercel.app   # uno o varios, separados por coma

# Fija estos secretos para NO perder los datos cifrados entre redeploys
# (genéralos una vez y guárdalos en el gestor de secretos del proveedor):
PASSWD_SECRET_KEY=...            # python -c "import secrets;print(secrets.token_urlsafe(48))"
PASSWD_ENCRYPTION_KEY=...        # python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"
```

> **Importante**: añade a `PASSWD_CORS_ORIGINS` también los dominios de *preview* de
> Vercel si quieres usarlos (p. ej. `https://tu-app-git-rama-usuario.vercel.app`).
> `SameSite=None` relaja la protección CSRF del navegador; el backend sigue exigiendo
> el token anti-CSRF por cabecera (`X-CSRF-Token`), así que el modelo se mantiene.

## 3A. Opción recomendada: VPS con dominio + Caddy (HTTPS automático)

Sirve para cualquier VPS gratuito con IP pública y un (sub)dominio apuntándole
(p. ej. **Oracle Cloud Always Free**, que da una VM gratuita de verdad). Caddy
obtiene y renueva el certificado TLS solo.

```bash
# en el VPS (con Docker y Docker Compose instalados)
git clone <tu-repo> && cd passwd
cp .env.example .env        # edita las variables de la sección 2 + PASSWD_API_DOMAIN
#   PASSWD_API_DOMAIN=api.tu-dominio.tld   (el dominio que apunta a este VPS)
docker compose -f docker-compose.backend.yml up -d --build
# La API queda en https://api.tu-dominio.tld  (healthcheck: /healthz)
```

Abre los puertos 80 y 443 en el firewall del VPS. Los datos (SQLite, claves,
auditoría) persisten en el volumen `datos-passwd`.

## 3B. Opción sin dominio: PaaS con subdominio HTTPS gratis

Plataformas que dan un subdominio HTTPS y construyen desde el `Dockerfile`
(respeta `$PORT` automáticamente):

- **Fly.io**: persistencia con *volumes* (monta el volumen en `/srv/passwd/data`).
- **Render** / **Koyeb**: el plan gratuito es **efímero** (sin disco persistente);
  el `Dockerfile` arranca, pero la BD SQLite se reinicia en cada redeploy. Útil
  solo para pruebas; para conservar datos usa un disco/volumen de pago o la opción 3A.

En todas: define las variables de la sección 2 (incluye `PASSWD_SECRET_KEY` y
`PASSWD_ENCRYPTION_KEY` para no perder lo cifrado). La URL pública del servicio
(p. ej. `https://passwd-api.fly.dev`) es la que usarás en el frontend.

## 4. Frontend en Vercel/v0

1. **Root Directory** del proyecto en Vercel: `frontend`.
2. Variable de entorno:
   ```
   NEXT_PUBLIC_API_BASE = https://api.tu-dominio.tld   (o https://passwd-api.fly.dev)
   ```
   Con esta variable el frontend llama al backend de forma directa (cross-origin).
   Si la dejas vacía, usa el proxy mismo-origen (`PASSWD_API_BASE` en `next.config.ts`).
3. Vuelve a desplegar. El primer acceso pedirá cambio de contraseña + enrolar MFA.

## 5. Comprobación rápida

```bash
curl -s https://api.tu-dominio.tld/healthz            # {"estado":"ok",...}
# Preflight CORS (debe devolver Access-Control-Allow-Origin con tu dominio):
curl -sI -X OPTIONS https://api.tu-dominio.tld/api/web/login \
  -H "Origin: https://TU-APP.vercel.app" \
  -H "Access-Control-Request-Method: POST" | grep -i access-control
```

Desde el frontend, el flujo `login → cambio de contraseña → MFA` debe funcionar y
la cookie de sesión debe quedar guardada (revisa que sea `Secure; SameSite=None`).

## 6. Notas de seguridad

- `SameSite=None` solo es aceptable sobre **HTTPS** (el backend lo fuerza a Secure).
- Restringe `PASSWD_CORS_ORIGINS` a tus dominios exactos; nunca uses `*` con credenciales.
- Conserva `PASSWD_SECRET_KEY` y `PASSWD_ENCRYPTION_KEY`: sin la de cifrado, las
  contraseñas y notas guardadas son irrecuperables.
- Para producción real (no solo iterar diseño), considera volver al modo
  mismo-origen (frontend y backend tras el mismo proxy) descrito en
  [`guia-nginx-tls.md`](guia-nginx-tls.md) y `docker-compose.frontend.yml`.
