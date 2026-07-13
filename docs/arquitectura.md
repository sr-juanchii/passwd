# Arquitectura del sistema

**Sistema:** Gestor de Contraseñas de Servidores
**Propósito de este documento:** explicar **cómo está construido** el sistema, **de qué se
compone** y **cómo fluye una petición** de extremo a extremo, para que cualquier persona técnica
entienda el conjunto antes de entrar al código o al despliegue.

> Complementa a [`modelo-datos.md`](modelo-datos.md) (esquema relacional),
> [`control-acceso.md`](control-acceso.md) (autorización) y a las guías de despliegue
> ([`guia-implementacion.md`](guia-implementacion.md), [`guia-nginx-tls.md`](guia-nginx-tls.md),
> [`ambientes.md`](ambientes.md)).

---

## 1. Visión general

El sistema es una aplicación web para **custodiar las credenciales de la infraestructura de
servidores** con un inventario relacional, autenticación reforzada (contraseña + MFA obligatorio),
control de acceso por rol y por objeto, cifrado en reposo y auditoría completa.

Tiene **dos interfaces** que conviven sobre el **mismo backend y el mismo modelo de seguridad**:

1. **Web clásica (Jinja2):** servida por la propia aplicación FastAPI. Cero dependencias de
   JavaScript de terceros; compatible con una CSP estricta.
2. **Frontend moderno (Next.js + shadcn/ui):** una SPA/SSR que consume una **API JSON** (`/api/web`)
   del backend.

Además expone una **API REST de solo lectura** (`/api/v1`) con tokens Bearer para SIEM y
automatización, que nunca devuelve secretos.

---

## 2. Componentes

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Cliente (navegador) — web Jinja  ó  frontend Next.js                      │
└───────────────────────────────┬────────────────────────────────────────────┘
                                 │ HTTPS / 443
                                 ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  nginx (terminación TLS, obligatorio en producción)                        │
│   • 80 → 301 a 443 (y desafío ACME)                                        │
│   • /api/*  y  /healthz   →  app:8000   (backend FastAPI)                   │
│   • /  (resto)            →  frontend:3000  (solo en el stack con Next.js)  │
│   • HSTS, reescribe X-Forwarded-For con la IP real (anti-spoofing)         │
└───────────────┬──────────────────────────────────┬─────────────────────────┘
                │ HTTP interno                       │ HTTP interno
                ▼                                    ▼
┌───────────────────────────────────┐   ┌─────────────────────────────────────┐
│  app — FastAPI / uvicorn :8000     │   │  frontend — Next.js :3000           │
│   • routes/   web Jinja (HTML)     │   │   • App Router, React 19            │
│   • api_web/  API JSON del front   │   │   • proxy /api/* → backend          │
│   • routes/api.py  REST /api/v1    │   │   • salida "standalone" en Docker   │
│   • security/ Argon2, Fernet,      │   └─────────────────────────────────────┘
│     TOTP, sesiones, rate limit     │
│   • deps / rbac / access  (authz)  │
│   • audit / notifications / backup │
└───────────────┬────────────────────┘
                │ SQLAlchemy
                ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  Base de datos:  SQLite (por defecto)  ó  MySQL 8 (opcional)               │
│   • Secretos cifrados con Fernet (contraseñas, semillas TOTP, notas)       │
│   • Claves criptográficas FUERA de la BD (entorno o archivos 0600)         │
└──────────────────────────────────────────────────────────────────────────┘
```

| Componente | Tecnología | Función |
|---|---|---|
| **Backend** | FastAPI + uvicorn (Python 3.11+) | Lógica, autenticación, autorización, cifrado, auditoría; sirve la web Jinja, la API JSON y la API REST |
| **Frontend** | Next.js (App Router, React 19), Tailwind v4, shadcn/ui | Interfaz moderna que consume `/api/web` |
| **Proxy** | nginx 1.27 | Termina TLS, enruta, fija HSTS y la IP real del cliente |
| **Base de datos** | SQLite (defecto) o MySQL 8.4 | Persistencia; secretos cifrados en reposo |
| **CLI** | `python -m app.cli` | Alta de admin, respaldo y restauración cifrados |
| **Certbot** | certbot (opcional) | Emisión y renovación automática de Let's Encrypt |

---

## 3. Estructura del código backend (`app/`)

```
app/
├── main.py            # create_app(): monta routers, middlewares de seguridad, arranque
├── config.py          # Settings (todas las variables PASSWD_*) + carga/persistencia de claves
├── database.py        # motor SQLAlchemy (SQLite/MySQL), get_db(), init_db()
├── schema_sync.py     # reconciliación de esquema (ALTER ADD COLUMN aditivo) y migración de inventario
├── models.py          # modelo relacional completo (usuarios, inventario, credenciales, auditoría…)
├── exceptions.py      # RedirigirLogin (señal interna de redirección)
├── deps.py            # dependencias web: sesión activa, etapa, permisos, CSRF, render Jinja
├── rbac.py            # matriz de permisos por rol (estática)
├── access.py          # control de acceso por objeto (concesiones a analistas)
├── audit.py           # registrar() y purgar_antiguos() de la bitácora
├── notifications.py   # alertas por correo (opt-in, sin secretos)
├── backup.py          # exportar()/restaurar() cifrados (scrypt + Fernet)
├── cli.py             # comandos: init-db, crear-admin, respaldo, restaurar
├── security/          # crypto (Fernet), passwords (Argon2id), mfa (TOTP+QR),
│                      #   sessions, ratelimit, recovery (códigos MFA)
├── routes/            # interfaz web Jinja (auth, inventory, credentials, users,
│                      #   accesos, notes, search, metrics, audit_view, importer, tokens) + api.py (/api/v1)
├── api_web/           # API JSON (/api/web) que consume el frontend (mismos módulos + deps/serializers)
├── templates/         # plantillas Jinja2 (HTML) en español
└── static/            # CSS y JS compatibles con la CSP estricta
```

### Capas (de fuera hacia dentro)

1. **Routers** (`routes/`, `api_web/`, `routes/api.py`): definen los endpoints HTTP. Los de `routes/`
   devuelven HTML (Jinja) y redirigen a `/login`; los de `api_web/` devuelven JSON y responden con
   códigos HTTP (401/403/404…).
2. **Dependencias de seguridad** (`deps.py`, `api_web/deps.py`): resuelven la sesión activa, exigen
   la etapa correcta del login, comprueban el **permiso RBAC** y validan **CSRF**.
3. **Autorización**: `rbac.py` (qué puede hacer un rol) + `access.py` (sobre qué objetos concretos,
   para el analista).
4. **Servicios de seguridad** (`security/`): hashing, cifrado, TOTP, sesiones, límites de tasa.
5. **Modelo y persistencia** (`models.py`, `database.py`): ORM SQLAlchemy y motor.
6. **Transversales**: `audit.py` (registra cada acción), `notifications.py`, `backup.py`.

---

## 4. Modelo de seguridad (resumen arquitectónico)

| Capa | Mecanismo | Dónde |
|---|---|---|
| Transporte | TLS terminado por nginx; HSTS; cookie `Secure` | nginx + `app/main.py` |
| Autenticación | Argon2id (contraseña) + TOTP obligatorio + códigos de recuperación | `security/passwords.py`, `security/mfa.py`, `security/recovery.py` |
| Sesión | Token aleatorio en cookie `HttpOnly`+`SameSite=Strict`; en BD solo su **hash SHA-256**; doble expiración (15 min inactividad / 8 h absoluta); revocable | `security/sessions.py` |
| CSRF | Token por sesión; web Jinja lo envía en formulario, el frontend en cabecera `X-CSRF-Token`; login con doble cookie | `deps.py`, `api_web/deps.py` |
| Autorización | RBAC (4 roles) + control de acceso por objeto (default-deny para analista) | `rbac.py`, `access.py` |
| Cifrado en reposo | Fernet (AES-CBC + HMAC) para contraseñas, semillas TOTP y notas; clave fuera de la BD | `security/crypto.py`, `config.py` |
| Anti-abuso | Bloqueo de cuenta (5 fallos), rate limit por IP y **límite anti-exfiltración** por usuario | `security/ratelimit.py`, `routes/auth.py` |
| Endurecimiento | CSP estricta, X-Frame-Options, nosniff, COOP/CORP, límite de tamaño de petición, docs API ocultas | `app/main.py` |
| Auditoría | Cada evento con usuario, IP, agente y resultado; retención ≥ 90 días | `audit.py`, `models.py` |

Detalle de cumplimiento normativo en [`cumplimiento-cis-v8.1.md`](cumplimiento-cis-v8.1.md),
[`cumplimiento-iso-27003.md`](cumplimiento-iso-27003.md) y
[`cumplimiento-owasp.md`](cumplimiento-owasp.md).

---

## 5. Flujos clave

### 5.1 Autenticación por etapas

La sesión avanza por **etapas** (`SesionWeb.etapa`); ninguna página protegida es accesible hasta
llegar a `activa`:

```
login (usuario+contraseña)
   ├─ ¿debe cambiar contraseña?  → etapa cambio_password → /password/cambiar
   ├─ ¿MFA no enrolado?          → etapa mfa_enrolamiento → /mfa/configurar (QR + 8 códigos)
   └─ MFA enrolado               → etapa mfa_pendiente    → /mfa/verificar (TOTP o código de recuperación)
                                                          → etapa activa
```

En cada transición sensible (cambio de contraseña, completar MFA) **se rota el token de sesión**
(anti-fijación) y se revocan otras sesiones del usuario cuando procede.

### 5.2 Petición autenticada (web o JSON)

```
Cookie de sesión → buscar_sesion_valida() (hash, no revocada, no expirada; refresca actividad)
   → exigir etapa "activa"
   → requiere_permiso(rol, permiso)          [RBAC]
   → (analista) puede_ver / puede_revelar     [acceso por objeto]
   → (mutaciones) verificar CSRF
   → lógica + audit.registrar()
```

### 5.3 Revelar/copiar una contraseña

`/credenciales/{id}/revelar` y `/copiar` descifran en el servidor, aplican el **límite
anti-exfiltración** por usuario, responden con `Cache-Control: no-store` y **auditan** cada acceso
por separado. El frontend no recibe nunca la contraseña en listados ni en el detalle, solo por
estos endpoints dedicados.

---

## 6. Persistencia y esquema

- **Motor:** SQLAlchemy 2.x. En SQLite se activa `PRAGMA foreign_keys=ON`; en MySQL se fija
  `READ COMMITTED` (necesario para el flujo multi-paso del login).
- **Sesión por petición:** `get_db()` hace `commit` al final si no hubo excepción y `rollback` si
  la hubo — salvo `RedirigirLogin`, para que persistan revocaciones de sesión.
- **Arranque (`init_db()`):** migra el inventario de nivel superior si detecta el esquema antiguo,
  ejecuta `create_all()` y luego `reconciliar_esquema()` para añadir columnas nuevas que falten
  (`ALTER TABLE ADD COLUMN`, aditivo). Los cambios **no aditivos** se entregan como revisiones de
  **Alembic** (`migrations/`, ver [`guia-desarrollo.md`](guia-desarrollo.md) §7).
- **Inventario:** dos activos de nivel superior (servidor físico e hipervisor) y máquinas virtuales
  bajo el hipervisor; las credenciales cuelgan de exactamente uno de los tres (restricción CHECK).
  Esquema completo en [`modelo-datos.md`](modelo-datos.md).

---

## 7. Despliegue (topologías)

El despliegue se compone con **overlays de Docker Compose**, que se combinan según el escenario:

| Escenario | Comando |
|---|---|
| Desarrollo local (SQLite, sin TLS) | `docker compose up -d --build` (app en `127.0.0.1:8000`) |
| Producción web Jinja + TLS | `... -f docker-compose.yml -f docker-compose.nginx.yml ...` |
| Producción frontend Next.js + TLS | `... -f docker-compose.yml -f docker-compose.frontend.yml ...` |
| + MySQL | añadir `-f docker-compose.mysql.yml` |
| + Let's Encrypt automático | añadir `-f docker-compose.certbot.yml` |

Con cualquier overlay de nginx, la app **deja de publicar el 8000** (`ports: !reset []`): el único
punto de entrada es nginx por el 443. Guías: [`guia-implementacion.md`](guia-implementacion.md),
[`guia-nginx-tls.md`](guia-nginx-tls.md) y [`ambientes.md`](ambientes.md).

---

## 8. Calidad y verificación

- **Pruebas:** suite `pytest` (103 pruebas) que cubre auth/MFA, RBAC, acceso por objeto, CSRF,
  cifrado, respaldo, export CSV, métricas, búsqueda, importación, migraciones y endurecimiento OWASP.
- **Análisis estático:** `ruff` (incluye reglas de seguridad `S`) y `bandit` (SAST, severidad ≥ media).
- **Dependencias:** `pip-audit` contra avisos de PyPA.
- **CI:** `.github/workflows/ci.yml` ejecuta todo lo anterior en cada push y PR.
- **Verificación funcional de la API JSON:** `python scripts/verificar_api_web.py` ejercita la API
  `/api/web` de extremo a extremo.

Detalle y evidencia en [`verificacion-cumplimiento.md`](verificacion-cumplimiento.md) y
[`guia-desarrollo.md`](guia-desarrollo.md).
</content>
