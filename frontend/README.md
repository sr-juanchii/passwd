# Frontend Next.js + shadcn/ui

Interfaz del **Gestor de Contraseñas de Servidores** reconstruida con
[Next.js](https://nextjs.org) (App Router, React 19), [Tailwind CSS v4](https://tailwindcss.com)
y [shadcn/ui](https://ui.shadcn.com). Consume la API JSON del backend FastAPI
(`/api/web`) preservando el modelo de seguridad: sesión por cookie HttpOnly,
CSRF por cabecera `X-CSRF-Token`, RBAC y control de acceso por objeto.

## Funcionalidad (paridad con la web Jinja)

- **Autenticación por etapas**: login → cambio de contraseña forzado → enrolamiento
  MFA (QR + códigos de recuperación) → verificación TOTP → sesión activa.
- **Inventario relacional**: árbol servidor físico → hipervisor → máquina virtual,
  con CRUD completo, estados, hardware, etiquetas y notas seguras cifradas.
- **Credenciales**: alta/edición/borrado, **generador** (CSPRNG, 20 caracteres),
  **copiar sin mostrar** (se limpia el portapapeles a los 30 s), **revelar** con
  auto-ocultado, **historial** de contraseñas anteriores. Cada acceso es auditado.
- **Control de acceso por objeto**: concesiones a analistas (nivel y caducidad).
- **Administración**: usuarios, tokens de API, **auditoría** con filtros y
  exportación CSV, **métricas** de seguridad, **importación CSV** y búsqueda global.
- **Tema claro/oscuro** persistente y diseño responsive.

## Desarrollo

Requisitos: Node >= 20 y el backend FastAPI corriendo.

    # 1) Backend (raíz del repo)
    export PASSWD_ADMIN_USERNAME=admin
    export PASSWD_ADMIN_EMAIL=admin@su-organizacion.tld
    export PASSWD_ADMIN_PASSWORD='UnaClaveInicialRobusta!'
    export PASSWD_COOKIE_SECURE=false   # solo en desarrollo sin HTTPS
    uvicorn app.main:app --port 8000

    # 2) Frontend (frontend/)
    pnpm install
    pnpm dev                            # http://localhost:3000

Next.js proxya `/api/web/*`, `/api/v1/*` y `/healthz` al backend (configurable
con `PASSWD_API_BASE`, por defecto `http://127.0.0.1:8000`). Gracias al proxy, el
navegador ve un único origen y la cookie de sesión `SameSite=Strict` viaja como
cookie de primera parte.

## Producción

### Con Docker (recomendado)

Desde la raíz del repositorio, un único comando levanta backend + frontend +
nginx (TLS); nginx enruta `/api/*` y `/healthz` al backend y el resto al
frontend Next.js:

    cp .env.example .env        # PASSWD_ADMIN_* y PASSWD_DOMAIN
    docker compose -f docker-compose.yml -f docker-compose.frontend.yml up -d --build

La imagen del frontend (`Dockerfile`) usa la salida `standalone` de Next.js
(imagen mínima, usuario sin privilegios). Certificados y rotación TLS en
`../docs/guia-nginx-tls.md`.

### Sin Docker

`pnpm build && pnpm start`, siempre detrás de un proxy TLS (nginx) que enrute
`/api/*` al backend y el resto al servidor Next.js. La cookie de sesión exige
HTTPS (`PASSWD_COOKIE_SECURE=true`, por defecto).

El contrato de la API está documentado en [`API_CONTRACT.md`](./API_CONTRACT.md).
