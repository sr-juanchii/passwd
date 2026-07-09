# Guía de desarrollo

Cómo preparar el entorno, ejecutar la aplicación, las pruebas y las comprobaciones de calidad, y
qué convenciones sigue el proyecto. Para entender la estructura del sistema antes de tocar código,
lea primero [`arquitectura.md`](arquitectura.md).

## 1. Requisitos

- **Python 3.11+** (el backend).
- **Node.js ≥ 20** y **pnpm** (solo si trabaja en el frontend Next.js).
- Opcional: **Docker** y Docker Compose v2 para levantar el stack completo.

## 2. Backend: entorno local

```bash
python -m venv .venv && . .venv/bin/activate     # opcional pero recomendado
pip install -r requirements-dev.txt              # incluye runtime + herramientas de calidad

export PASSWD_ADMIN_USERNAME=admin
export PASSWD_ADMIN_EMAIL=admin@su-organizacion.tld
export PASSWD_ADMIN_PASSWORD='UnaClaveInicialRobusta!'
export PASSWD_COOKIE_SECURE=false                # solo para probar sin HTTPS

uvicorn app.main:app --reload --port 8000
```

La aplicación crea la base de datos SQLite en `./data/` al arrancar y, si no hay usuarios, da de
alta el administrador inicial. Endpoint de salud: `GET /healthz`.

> Las variables de configuración están documentadas en
> [`referencia-configuracion.md`](referencia-configuracion.md).

## 3. Frontend: entorno local

Con el backend corriendo en `:8000`:

```bash
cd frontend
pnpm install
pnpm dev                                          # http://localhost:3000
```

Next.js **proxya** `/api/web/*`, `/api/v1/*` y `/healthz` al backend (configurable con
`PASSWD_API_BASE`, por defecto `http://127.0.0.1:8000`). Gracias al proxy, el navegador ve un único
origen y la cookie de sesión `SameSite=Strict` funciona como cookie de primera parte.

Scripts (`frontend/package.json`): `pnpm dev`, `pnpm build`, `pnpm start`, `pnpm lint`.

## 4. Pruebas y calidad (backend)

```bash
pytest                                  # suite completa (103 pruebas)
ruff check app tests                    # lint + reglas de seguridad
bandit -r app --severity-level medium   # SAST
pip-audit -r requirements.txt           # dependencias vulnerables
```

- La configuración de `pytest` y `ruff` vive en [`pyproject.toml`](../pyproject.toml)
  (`testpaths=["tests"]`, `line-length=120`, reglas `E,F,W,I,B,UP,S`).
- Cada prueba se ejecuta **aislada**, con una base de datos SQLite temporal y claves autogeneradas
  (ver `tests/conftest.py` y sus *helpers*: `autenticar_admin`, `crear_usuario`, `enrolar_mfa`…).

### Verificación funcional de la API JSON

```bash
python scripts/verificar_api_web.py
```

Ejercita de extremo a extremo la API `/api/web` (auth+MFA, inventario, credenciales, rotación e
historial, notas, acceso por objeto, usuarios, tokens, auditoría con export CSV, métricas, búsqueda,
importación CSV y cascadas).

## 5. Integración continua

[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) ejecuta, en cada **push** y **pull
request**: `ruff` → `bandit` → `pip-audit` → `pytest` sobre Python 3.12. Antes de abrir un PR,
ejecute localmente los cuatro comandos de la §4.

## 6. Estructura del repositorio

```
app/            # backend FastAPI (ver arquitectura.md §3)
frontend/       # frontend Next.js (App Router, React 19, shadcn/ui)
tests/          # suite pytest (14 archivos de prueba + conftest.py)
scripts/        # verificar_api_web.py (verificación funcional de /api/web)
infrastructure/ # nginx (plantillas TLS) y scripts de certificados
docs/           # esta documentación
.github/        # workflow de CI
docker-compose*.yml  # base + overlays (nginx, frontend, mysql, certbot)
Dockerfile      # imagen del backend
.env*.example   # plantillas de configuración por ambiente
```

Mapa detallado del backend en [`arquitectura.md`](arquitectura.md) §3; del frontend, en
[`../frontend/README.md`](../frontend/README.md) y [`../frontend/API_CONTRACT.md`](../frontend/API_CONTRACT.md).

## 7. Convenciones

- **Idioma:** el código de dominio, las rutas, los mensajes y la documentación están **en español**
  (p. ej. `usuario`, `credencial`, `concesion`). Manténgalo al añadir código.
- **Seguridad primero:** toda ruta pasa por las dependencias de sesión/permiso/CSRF; toda acción
  relevante se **audita** (`app/audit.py`); los secretos se **cifran** antes de tocar la BD y
  **nunca** se serializan (salvo los endpoints de revelar/copiar, auditados y limitados).
- **Doble interfaz:** un cambio de comportamiento suele requerir tocar **tanto** la ruta Jinja
  (`app/routes/`) **como** la API JSON (`app/api_web/`) para mantener la paridad. Refleje los
  cambios de contrato en [`../frontend/API_CONTRACT.md`](../frontend/API_CONTRACT.md).
- **Migraciones:** los cambios de esquema **aditivos** (columnas/tablas nuevas) los aplica
  `app/schema_sync.py` al arrancar. Los **no aditivos** (eliminar/renombrar columnas, cambiar tipos
  o `CHECK`) se entregan como **revisiones de Alembic** (`alembic.ini` + `migrations/`, ligadas a
  la configuración real de la app): `alembic revision --autogenerate -m "descripcion"` para crear
  la migración, `alembic upgrade head` para aplicarla y `alembic stamp head` para marcar una base
  existente como al día. La revisión `0001` es la línea base del esquema completo, y una prueba
  (`tests/test_migraciones_alembic.py`) verifica que reproduce exactamente `Base.metadata`.
- **Pruebas:** acompañe cada cambio funcional o de seguridad con su prueba en `tests/`.
- **Política del proyecto:** **ninguna funcionalidad extra se incorpora sin consultarla antes**
  (ver README y [`hoja-de-ruta.md`](hoja-de-ruta.md)).

## 8. Documentos relacionados

- [`arquitectura.md`](arquitectura.md) — componentes y flujos.
- [`modelo-datos.md`](modelo-datos.md) — esquema relacional.
- [`verificacion-cumplimiento.md`](verificacion-cumplimiento.md) — evidencia de pruebas y SAST.
- [`hoja-de-ruta.md`](hoja-de-ruta.md) — estado y plan de evolución.
</content>
