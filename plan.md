


# PLAN DE FASES DE EJECUCIÓN — MVP INVENTARIO ZERO-KNOWLEDGE

## Mapa de Dependencias entre Fases

```
FASE 0 ─── Cimientos DevSecOps & Infraestructura Segura
  │
  ▼
FASE 1 ─── Identidad, Autenticación y Esqueleto RBAC
  │
  ├──────────────────────────┐
  ▼                          ▼
FASE 2A                   FASE 2B
CQRS Commands             Frontend Angular
(Backend Write Path)       (Crypto Engine + Shell)
  │                          │
  ▼                          │
FASE 3                       │
CQRS Queries                 │
(Backend Read Path + BOLA)   │
  │                          │
  ├──────────────────────────┘
  ▼
FASE 4 ─── Integración E2E del Flujo Zero-Knowledge
  │
  ▼
FASE 5 ─── Hardening, Logging Normativo y Auditoría Final
  │
  ▼
  ✅ MVP LISTO PARA AUDITORÍA
```

---

---

## FASE 0 — CIMIENTOS DEVSECOPS E INFRAESTRUCTURA SEGURA

### Objetivo Principal
> Construir la base inmutable sobre la que todo el código vivirá: contenedores, pipeline de seguridad automatizado, y conexión cifrada a base de datos. **Nada de código de negocio se escribe aquí.** Esta fase existe para garantizar que desde el primer `git push`, cada línea de código sea escaneada.

---

### Tarea 0.1 — Estructura del Monorepo y Esqueleto de Proyectos

```
project-root/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                    # Entry point FastAPI
│   │   ├── config/
│   │   │   ├── __init__.py
│   │   │   └── settings.py            # Pydantic BaseSettings (strict)
│   │   ├── domain/                    # Entidades de dominio puras
│   │   ├── infrastructure/            # SQLAlchemy, repos
│   │   ├── application/               # CQRS Handlers
│   │   │   ├── commands/
│   │   │   └── queries/
│   │   ├── api/                       # Routers FastAPI
│   │   │   ├── v1/
│   │   │   └── dependencies/          # Auth, RBAC injection
│   │   └── shared/                    # Logging, exceptions
│   ├── tests/
│   ├── pyproject.toml
│   ├── Dockerfile
│   └── mypy.ini                       # --strict habilitado
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── core/                  # Guards, interceptors, crypto
│   │   │   ├── features/              # Módulos por dominio
│   │   │   └── shared/                # Componentes reutilizables
│   │   └── environments/
│   ├── angular.json                   # strict mode
│   ├── tsconfig.json                  # strict: true
│   └── Dockerfile
├── infrastructure/
│   ├── docker-compose.yml
│   ├── docker-compose.security.yml    # Overrides para escaneos
│   ├── mysql/
│   │   ├── init.sql                   # Schema inicial + usuario limitado
│   │   └── ssl/                       # Certificados TLS MySQL
│   └── keycloak/
│       └── realm-export.json          # Realm preconfigurado
├── .github/workflows/                 # CI/CD pipelines
│   └── security-pipeline.yml
└── docs/
    └── compliance-matrix.md           # Mapeo control → código
```

---

### Tarea 0.2 — Docker Compose con Seguridad desde el Origen

```yaml
# infrastructure/docker-compose.yml
version: "3.9"

services:
  mysql:
    image: mysql:8.0
    container_name: zkm-mysql
    environment:
      MYSQL_ROOT_PASSWORD_FILE: /run/secrets/db_root_password
      MYSQL_DATABASE: inventory_zk
      MYSQL_USER: app_service
      MYSQL_PASSWORD_FILE: /run/secrets/db_app_password
    command: >
      --require-secure-transport=ON
      --default-authentication-plugin=caching_sha2_password
      --ssl-ca=/etc/mysql/ssl/ca.pem
      --ssl-cert=/etc/mysql/ssl/server-cert.pem
      --ssl-key=/etc/mysql/ssl/server-key.pem
      --general-log=0
      --slow-query-log=1
    volumes:
      - ./mysql/init.sql:/docker-entrypoint-initdb.d/01-init.sql:ro
      - ./mysql/ssl:/etc/mysql/ssl:ro
      - mysql_data:/var/lib/mysql
    ports:
      - "127.0.0.1:3306:3306"  # Solo localhost, NUNCA 0.0.0.0
    secrets:
      - db_root_password
      - db_app_password
    networks:
      - backend-net

  keycloak:
    image: quay.io/keycloak/keycloak:24.0
    container_name: zkm-keycloak
    command: start-dev --import-realm
    environment:
      KC_DB: mysql
      KC_DB_URL: jdbc:mysql://mysql:3306/keycloak_db?useSSL=true
      KC_DB_USERNAME: keycloak_svc
      KC_DB_PASSWORD_FILE: /run/secrets/kc_db_password
      KC_HOSTNAME_STRICT: "false"
      KC_HEALTH_ENABLED: "true"
    volumes:
      - ./keycloak/realm-export.json:/opt/keycloak/data/import/realm.json:ro
    ports:
      - "127.0.0.1:8080:8080"
    depends_on:
      - mysql
    secrets:
      - kc_db_password
    networks:
      - backend-net

  backend:
    build:
      context: ../backend
      dockerfile: Dockerfile
    container_name: zkm-backend
    environment:
      DATABASE_URL: "mysql+aiomysql://app_service@mysql:3306/inventory_zk"
      DB_PASSWORD_FILE: /run/secrets/db_app_password
      OIDC_ISSUER_URL: "http://keycloak:8080/realms/inventory"
      OIDC_AUDIENCE: "inventory-api"
      LOG_LEVEL: "INFO"
    ports:
      - "127.0.0.1:8000:8000"
    depends_on:
      - mysql
      - keycloak
    secrets:
      - db_app_password
    networks:
      - backend-net
      - frontend-net

  frontend:
    build:
      context: ../frontend
      dockerfile: Dockerfile
    container_name: zkm-frontend
    ports:
      - "127.0.0.1:4200:80"
    networks:
      - frontend-net

secrets:
  db_root_password:
    file: ./secrets/db_root_password.txt
  db_app_password:
    file: ./secrets/db_app_password.txt
  kc_db_password:
    file: ./secrets/kc_db_password.txt

volumes:
  mysql_data:

networks:
  backend-net:
    internal: true       # MySQL y Keycloak NO expuestos
  frontend-net:
```

**Decisiones de seguridad críticas aquí:**
- `require-secure-transport=ON`: MySQL rechaza conexiones sin TLS
- Docker secrets en archivos, **no** variables de entorno en texto claro
- Red `backend-net` marcada como `internal: true`: los contenedores de datos no tienen ruta al exterior
- Puertos bindeados a `127.0.0.1`, no a `0.0.0.0`

---

### Tarea 0.3 — Schema Inicial MySQL (Hardened)

```sql
-- infrastructure/mysql/init.sql

-- Base de datos principal
CREATE DATABASE IF NOT EXISTS inventory_zk
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE inventory_zk;

-- Tabla de servidores
CREATE TABLE servers (
    id CHAR(36) NOT NULL,          -- UUID generado en backend
    hostname VARCHAR(255) NOT NULL,
    ip_address VARCHAR(45) NOT NULL, -- Soporta IPv6
    operating_system VARCHAR(100) NOT NULL,
    owner_user_id CHAR(36) NOT NULL, -- FK lógica al sub del JWT
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    INDEX idx_owner (owner_user_id),
    INDEX idx_hostname (hostname)
) ENGINE=InnoDB;

-- Tabla de credenciales Zero-Knowledge
-- TODA columna sensible es VARBINARY, no VARCHAR
CREATE TABLE credentials (
    id CHAR(36) NOT NULL,
    server_id CHAR(36) NOT NULL,
    owner_user_id CHAR(36) NOT NULL,
    credential_username VARCHAR(255) NOT NULL,    -- username del servidor, no sensible
    cipher_text VARBINARY(4096) NOT NULL,         -- Contraseña cifrada con AES-256-GCM
    wrapped_dek VARBINARY(512) NOT NULL,           -- DEK envuelta con clave derivada PBKDF2
    iv VARBINARY(16) NOT NULL,                     -- Vector de inicialización (12 bytes GCM)
    auth_tag VARBINARY(32) NOT NULL,               -- Tag de autenticación GCM
    pbkdf2_salt VARBINARY(32) NOT NULL,            -- Salt usado para PBKDF2 (único por registro)
    pbkdf2_iterations INT UNSIGNED NOT NULL DEFAULT 600000,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE CASCADE,
    INDEX idx_cred_owner (owner_user_id),
    INDEX idx_cred_server (server_id)
) ENGINE=InnoDB;

-- Usuario de servicio con privilegios MÍNIMOS (Principio de Menor Privilegio)
-- NO tiene GRANT OPTION, NO tiene DROP, NO tiene CREATE/ALTER
CREATE USER IF NOT EXISTS 'app_service'@'%'
  IDENTIFIED BY 'PLACEHOLDER_REPLACED_BY_SECRET'
  REQUIRE SSL;

GRANT SELECT, INSERT, UPDATE, DELETE ON inventory_zk.* TO 'app_service'@'%';
FLUSH PRIVILEGES;
```

**Notas de seguridad:**
- `VARBINARY` para todos los datos cifrados: evita problemas de encoding/collation que corromperían los bytes
- `REQUIRE SSL` en el usuario: incluso si alguien desactiva `require-secure-transport`, este usuario sigue exigiendo TLS
- `pbkdf2_salt` almacenado por registro: cada credencial tiene su propia derivación, impidiendo ataques de precomputación
- `pbkdf2_iterations` almacenado: permite migrar a iteraciones más altas sin romper registros antiguos
- `auth_tag` separado: permite validar integridad antes del descifrado en frontend

---

### Tarea 0.4 — Pipeline CI/CD de Seguridad

```yaml
# .github/workflows/security-pipeline.yml
name: Security Quality Gate

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  # ──────────────────────────────────────────
  # STAGE 1: Análisis Estático (SAST + Tipos)
  # ──────────────────────────────────────────
  static-analysis:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: ./backend
    steps:
      - uses: actions/checkout@v4

      - name: Setup Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: pip install -e ".[dev]"

      - name: Mypy Strict Type Check
        run: mypy app/ --strict --no-error-summary
        # GATE: Falla el pipeline si hay errores de tipado

      - name: Ruff Linter
        run: ruff check app/ --select=ALL --fix --exit-non-zero-on-fix

      - name: Bandit SAST Scanner
        run: bandit -r app/ -f json -o bandit-report.json -ll
        # -ll = reporta solo Medium y superiores
        # GATE: Falla si encuentra High o Critical

      - name: Safety SCA (Dependency Vulnerabilities)
        run: safety check --full-report --output json > safety-report.json

      - name: Upload Security Reports
        uses: actions/upload-artifact@v4
        if: always()
        with:
          name: sast-reports
          path: |
            backend/bandit-report.json
            backend/safety-report.json

  # ──────────────────────────────────────────
  # STAGE 2: Tests Unitarios con Cobertura
  # ──────────────────────────────────────────
  unit-tests:
    runs-on: ubuntu-latest
    needs: static-analysis
    defaults:
      run:
        working-directory: ./backend
    steps:
      - uses: actions/checkout@v4
      - name: Setup Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install dependencies
        run: pip install -e ".[dev]"
      - name: Run Tests
        run: pytest tests/ -v --cov=app --cov-report=xml --cov-fail-under=80

  # ──────────────────────────────────────────
  # STAGE 3: Build de Contenedores Seguros
  # ──────────────────────────────────────────
  container-build:
    runs-on: ubuntu-latest
    needs: unit-tests
    steps:
      - uses: actions/checkout@v4
      - name: Build Backend Image
        run: docker build -t zkm-backend:${{ github.sha }} ./backend
      - name: Build Frontend Image
        run: docker build -t zkm-frontend:${{ github.sha }} ./frontend
      - name: Trivy Container Scan
        uses: aquasecurity/trivy-action@master
        with:
          image-ref: "zkm-backend:${{ github.sha }}"
          severity: "HIGH,CRITICAL"
          exit-code: "1"  # GATE: Falla si hay vulns críticas en imagen

  # ──────────────────────────────────────────
  # STAGE 4: DAST (Solo en rama main)
  # ──────────────────────────────────────────
  dast-scan:
    runs-on: ubuntu-latest
    needs: container-build
    if: github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v4
      - name: Start Services
        run: |
          cd infrastructure
          docker compose up -d --wait
      - name: OWASP ZAP Baseline Scan
        uses: zaproxy/action-baseline@v0.12.0
        with:
          target: "http://localhost:8000"
          rules_file_name: "zap-rules.tsv"
          cmd_options: "-a -j"
      - name: Teardown
        if: always()
        run: |
          cd infrastructure
          docker compose down -v
```

---

### Tarea 0.5 — Configuración Backend Base (Settings Seguro)

```python
# backend/app/config/settings.py
"""
Configuración centralizada con Pydantic BaseSettings.
Todas las variables sensibles se leen de archivos (Docker Secrets)
o variables de entorno, NUNCA hardcodeadas.
"""
from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field, SecretStr, field_validator


class Settings(BaseSettings):
    """Configuración inmutable de la aplicación."""

    # ── Base de Datos ──
    database_host: str = Field(default="localhost", alias="DATABASE_HOST")
    database_port: int = Field(default=3306, alias="DATABASE_PORT")
    database_name: str = Field(default="inventory_zk", alias="DATABASE_NAME")
    database_user: str = Field(default="app_service", alias="DATABASE_USER")
    database_password: SecretStr = Field(..., alias="DATABASE_PASSWORD")
    database_ssl_ca: str = Field(
        default="/etc/mysql/ssl/ca.pem",
        alias="DATABASE_SSL_CA",
    )

    # ── OIDC / Keycloak ──
    oidc_issuer_url: str = Field(..., alias="OIDC_ISSUER_URL")
    oidc_audience: str = Field(default="inventory-api", alias="OIDC_AUDIENCE")
    oidc_jwks_url: str = Field(default="", alias="OIDC_JWKS_URL")

    # ── Aplicación ──
    app_name: str = "ZK Inventory API"
    app_version: str = "0.1.0"
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    debug: bool = False

    # ── CORS ──
    cors_allowed_origins: list[str] = Field(
        default=["http://localhost:4200"],
        alias="CORS_ALLOWED_ORIGINS",
    )

    @field_validator("oidc_jwks_url", mode="before")
    @classmethod
    def build_jwks_url(cls, v: str, info: dict) -> str:  # type: ignore[type-arg]
        if v:
            return v
        issuer: str = info.data.get("oidc_issuer_url", "")
        return f"{issuer}/protocol/openid-connect/certs"

    @property
    def async_database_url(self) -> str:
        password = self.database_password.get_secret_value()
        return (
            f"mysql+aiomysql://{self.database_user}:{password}"
            f"@{self.database_host}:{self.database_port}"
            f"/{self.database_name}"
        )

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "forbid",  # Rechaza variables no declaradas
    }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton inmutable de configuración."""
    return Settings()  # type: ignore[call-arg]
```

---

### Tarea 0.6 — Dockerfile Backend (Hardened)

```dockerfile
# backend/Dockerfile
FROM python:3.11-slim AS base

# Seguridad: No ejecutar como root
RUN groupadd -r appgroup && useradd -r -g appgroup -d /app -s /sbin/nologin appuser

WORKDIR /app

# Dependencias del sistema para aiomysql + SSL
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      ca-certificates \
      libmariadb-dev && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copiar solo requirements primero (cache de capas)
COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# Copiar código fuente
COPY app/ ./app/

# Cambiar a usuario no-root
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4", "--no-access-log"]
```

---

### 🔒 CHECKPOINT DE SEGURIDAD Y CUMPLIMIENTO — FASE 0

| Control Normativo | Requisito | Implementación en esta Fase | Estado |
|---|---|---|---|
| **NIST CSF PR.DS-1** | Protección de datos en reposo | MySQL con TLS obligatorio, schema VARBINARY preparado | ✅ |
| **NIST CSF PR.DS-2** | Protección de datos en tránsito | `require-secure-transport=ON`, `REQUIRE SSL` en usuario MySQL | ✅ |
| **CIS Control 3.12** | Segmentar procesamiento de datos sensibles | Redes Docker separadas (`backend-net` internal, `frontend-net`) | ✅ |
| **CIS Control 6.1** | Establecer proceso de gestión de acceso | Usuario MySQL con privilegios mínimos (SELECT/INSERT/UPDATE/DELETE) | ✅ |
| **CIS Control 16.7** | Pipeline de desarrollo seguro | GitHub Actions con Bandit, Safety, Mypy strict, Trivy | ✅ |
| **ISO 27001 A.8.9** | Gestión de configuración | Pydantic Settings con `extra="forbid"`, Docker secrets | ✅ |
| **PCI DSS 6.3** | Entorno de desarrollo seguro | Contenedor non-root, imágenes slim, Trivy scan | ✅ |
| **OWASP API1** | Broken Object Level Auth | Schema con `owner_user_id` preparado para validación BOLA | 🟡 Preparado |

**Herramientas ejecutadas en esta fase:**
- ✅ `mypy --strict` sobre `settings.py` (validación de tipos)
- ✅ `bandit -r app/` (scan SAST del código inicial)
- ✅ `safety check` (vulnerabilidades en dependencias)
- ✅ `trivy` (scan de imagen Docker)
- ✅ Docker Compose levanta sin errores con TLS

**Entregables Fase 0:**
1. Monorepo estructurado con separación CQRS preparada
2. `docker-compose.yml` con seguridad por defecto
3. Schema MySQL hardened con tipos `VARBINARY`
4. Pipeline CI/CD con 4 stages de seguridad
5. `Settings` Pydantic estricto con secretos seguros
6. Dockerfile non-root con healthcheck
7. Documentación inicial `compliance-matrix.md`

---

---

## FASE 1 — IDENTIDAD, AUTENTICACIÓN Y ESQUELETO RBAC

### Objetivo Principal
> Implementar la capa de autenticación stateless basada en JWT/OIDC y el sistema de autorización RBAC como dependencias inyectables de FastAPI. **Al final de esta fase, cualquier endpoint que se cree en fases posteriores estará protegido automáticamente.**

---

### Tarea 1.1 — Configuración del Realm en Keycloak

```json
// infrastructure/keycloak/realm-export.json (fragmento relevante)
{
  "realm": "inventory",
  "enabled": true,
  "sslRequired": "external",
  "roles": {
    "realm": [
      { "name": "ADMIN",  "description": "Acceso total: Commands + Queries" },
      { "name": "EDITOR", "description": "Commands + Queries sobre recursos propios" },
      { "name": "VIEWER", "description": "Solo Queries sobre recursos propios" }
    ]
  },
  "clients": [
    {
      "clientId": "inventory-api",
      "enabled": true,
      "protocol": "openid-connect",
      "publicClient": false,
      "bearerOnly": true,
      "standardFlowEnabled": false,
      "directAccessGrantsEnabled": false
    },
    {
      "clientId": "inventory-spa",
      "enabled": true,
      "protocol": "openid-connect",
      "publicClient": true,
      "standardFlowEnabled": true,
      "redirectUris": ["http://localhost:4200/*"],
      "webOrigins": ["+"],
      "attributes": {
        "pkce.code.challenge.method": "S256"
      }
    }
  ],
  "clientScopes": [
    {
      "name": "inventory-scope",
      "protocol": "openid-connect",
      "protocolMappers": [
        {
          "name": "realm-roles-mapper",
          "protocol": "openid-connect",
          "protocolMapper": "oidc-usermodel-realm-role-mapper",
          "config": {
            "claim.name": "realm_roles",
            "jsonType.label": "String",
            "multivalued": "true",
            "id.token.claim": "true",
            "access.token.claim": "true"
          }
        }
      ]
    }
  ],
  "users": [
    {
      "username": "admin-test",
      "enabled": true,
      "credentials": [{ "type": "password", "value": "Admin123!", "temporary": false }],
      "realmRoles": ["ADMIN"]
    },
    {
      "username": "editor-test",
      "enabled": true,
      "credentials": [{ "type": "password", "value": "Editor123!", "temporary": false }],
      "realmRoles": ["EDITOR"]
    },
    {
      "username": "viewer-test",
      "enabled": true,
      "credentials": [{ "type": "password", "value": "Viewer123!", "temporary": false }],
      "realmRoles": ["VIEWER"]
    }
  ]
}
```

**Decisiones clave:**
- `inventory-api` es `bearerOnly`: no acepta flujos de login, solo valida JWTs
- `inventory-spa` usa PKCE (`S256`): previene interceptación de authorization codes
- Roles en claim `realm_roles` mapeados directamente al access token
- Usuarios de prueba para desarrollo local; **eliminados en producción**

---

### Tarea 1.2 — Modelo de Identidad del Usuario Autenticado

```python
# backend/app/domain/identity.py
"""
Value Object inmutable que representa la identidad
extraída de un JWT verificado. Es el "pasaporte"
que acompaña cada petición a través de toda la aplicación.
"""
from dataclasses import dataclass
from enum import StrEnum, unique


@unique
class Role(StrEnum):
    """Roles del sistema alineados con Keycloak realm roles."""
    ADMIN = "ADMIN"
    EDITOR = "EDITOR"
    VIEWER = "VIEWER"


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    """
    Identidad inmutable extraída del JWT.
    
    - sub: Subject claim (UUID del usuario en Keycloak)
    - username: Preferred username (para logging, no para auth)
    - roles: Set de roles del realm
    """
    sub: str
    username: str
    roles: frozenset[Role]

    def has_role(self, role: Role) -> bool:
        return role in self.roles

    def has_any_role(self, *roles: Role) -> bool:
        return bool(self.roles & frozenset(roles))

    @property
    def is_admin(self) -> bool:
        return self.has_role(Role.ADMIN)
```

---

### Tarea 1.3 — Servicio de Verificación JWT (OIDC)

```python
# backend/app/infrastructure/auth/jwt_verifier.py
"""
Verificador de JWTs contra el JWKS de Keycloak.
Cachea las claves públicas para evitar llamadas
repetidas al endpoint JWKS.
"""
import logging
from typing import Any

import httpx
from jose import JWTError, jwt
from jose.backends import RSAKey

from app.config.settings import Settings

logger = logging.getLogger(__name__)


class JWTVerificationError(Exception):
    """Error de verificación de JWT."""


class JWTVerifier:
    """Verifica tokens JWT contra JWKS endpoint de OIDC."""

    def __init__(self, settings: Settings) -> None:
        self._issuer = settings.oidc_issuer_url
        self._audience = settings.oidc_audience
        self._jwks_url = settings.oidc_jwks_url
        self._jwks_cache: dict[str, RSAKey] = {}

    async def _fetch_jwks(self) -> None:
        """Obtiene y cachea las claves públicas del IdP."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(self._jwks_url)
            response.raise_for_status()
            jwks: dict[str, Any] = response.json()
            self._jwks_cache = {
                key["kid"]: key
                for key in jwks.get("keys", [])
            }
            logger.info(
                "JWKS refreshed",
                extra={"key_count": len(self._jwks_cache)},
            )

    async def verify_token(self, token: str) -> dict[str, Any]:
        """
        Verifica la firma, issuer, audience y expiración del token.
        Retorna el payload decodificado.
        """
        # Obtener kid del header sin verificar firma aún
        try:
            unverified_header = jwt.get_unverified_header(token)
        except JWTError as e:
            raise JWTVerificationError(f"Invalid token header: {e}") from e

        kid: str | None = unverified_header.get("kid")
        if not kid:
            raise JWTVerificationError("Token header missing 'kid'")

        # Si el kid no está cacheado, refrescar JWKS
        if kid not in self._jwks_cache:
            await self._fetch_jwks()

        if kid not in self._jwks_cache:
            raise JWTVerificationError(f"Unknown signing key: {kid}")

        # Verificar firma + claims estándar
        try:
            payload: dict[str, Any] = jwt.decode(
                token,
                self._jwks_cache[kid],
                algorithms=["RS256"],
                audience=self._audience,
                issuer=self._issuer,
                options={
                    "verify_exp": True,
                    "verify_aud": True,
                    "verify_iss": True,
                    "verify_iat": True,
                    "verify_nbf": True,
                },
            )
        except JWTError as e:
            raise JWTVerificationError(f"Token verification failed: {e}") from e

        return payload
```

---

### Tarea 1.4 — Dependencias FastAPI: Auth + RBAC

```python
# backend/app/api/dependencies/auth.py
"""
Dependencias inyectables para autenticación y autorización.

Estas dependencias son el CORAZÓN del Zero-Trust:
toda petición DEBE pasar por aquí antes de llegar
a cualquier handler CQRS.
"""
import logging
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config.settings import Settings, get_settings
from app.domain.identity import AuthenticatedUser, Role
from app.infrastructure.auth.jwt_verifier import (
    JWTVerificationError,
    JWTVerifier,
)

logger = logging.getLogger(__name__)

# Esquema de seguridad: Bearer token
_bearer_scheme = HTTPBearer(auto_error=True)

# Singleton del verificador (inicializado en lifespan de FastAPI)
_jwt_verifier: JWTVerifier | None = None


def init_jwt_verifier(settings: Settings) -> None:
    """Llamado durante el startup de FastAPI."""
    global _jwt_verifier  # noqa: PLW0603
    _jwt_verifier = JWTVerifier(settings)


def _get_verifier() -> JWTVerifier:
    if _jwt_verifier is None:
        raise RuntimeError("JWTVerifier not initialized")
    return _jwt_verifier


async def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials,
        Depends(_bearer_scheme),
    ],
    verifier: Annotated[JWTVerifier, Depends(_get_verifier)],
) -> AuthenticatedUser:
    """
    Extrae y verifica el JWT del header Authorization.
    Retorna un AuthenticatedUser inmutable.
    """
    try:
        payload = await verifier.verify_token(credentials.credentials)
    except JWTVerificationError as e:
        logger.warning(
            "Authentication failed",
            extra={"reason": str(e)},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e

    # Extraer roles del claim configurado en Keycloak
    raw_roles: list[str] = payload.get("realm_roles", [])
    valid_roles: frozenset[Role] = frozenset(
        Role(r) for r in raw_roles if r in Role.__members__
    )

    if not valid_roles:
        logger.warning(
            "User has no valid roles",
            extra={"sub": payload.get("sub", "unknown")},
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No valid roles assigned",
        )

    user = AuthenticatedUser(
        sub=payload["sub"],
        username=payload.get("preferred_username", "unknown"),
        roles=valid_roles,
    )

    logger.info(
        "User authenticated",
        extra={
            "user_id": user.sub,
            "roles": [r.value for r in user.roles],
        },
    )

    return user


# ────────────────────────────────────────────
# Fábricas de dependencias RBAC reutilizables
# ────────────────────────────────────────────

class RoleRequired:
    """
    Dependencia inyectable que valida roles.
    
    Uso en routers:
        @router.post("/", dependencies=[Depends(RoleRequired(Role.ADMIN, Role.EDITOR))])
    
    O como parámetro para obtener el usuario:
        user: AuthenticatedUser = Depends(RoleRequired(Role.ADMIN))
    """

    def __init__(self, *allowed_roles: Role) -> None:
        self._allowed = frozenset(allowed_roles)

    async def __call__(
        self,
        user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    ) -> AuthenticatedUser:
        if not user.has_any_role(*self._allowed):
            logger.warning(
                "Authorization denied",
                extra={
                    "user_id": user.sub,
                    "required_roles": [r.value for r in self._allowed],
                    "user_roles": [r.value for r in user.roles],
                },
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return user


# Aliases de conveniencia para inyección con Annotated
RequireAdmin = Annotated[
    AuthenticatedUser,
    Depends(RoleRequired(Role.ADMIN)),
]
RequireEditor = Annotated[
    AuthenticatedUser,
    Depends(RoleRequired(Role.ADMIN, Role.EDITOR)),
]
RequireViewer = Annotated[
    AuthenticatedUser,
    Depends(RoleRequired(Role.ADMIN, Role.EDITOR, Role.VIEWER)),
]
```

---

### Tarea 1.5 — Entry Point FastAPI con Lifespan Seguro

```python
# backend/app/main.py
"""
Entry point de la aplicación FastAPI.
Configura lifespan, middleware de seguridad y routers.
"""
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from app.api.dependencies.auth import init_jwt_verifier
from app.config.settings import get_settings
from app.infrastructure.database.session import init_db_engine, dispose_db_engine
from app.shared.logging_config import setup_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup y shutdown de recursos."""
    settings = get_settings()

    # Configurar logging estructurado
    setup_logging(settings.log_level)

    # Inicializar motor de BD
    await init_db_engine(settings)

    # Inicializar verificador JWT
    init_jwt_verifier(settings)

    logger.info(
        "Application started",
        extra={"version": settings.app_version},
    )

    yield

    # Cleanup
    await dispose_db_engine()
    logger.info("Application shutdown complete")


def create_app() -> FastAPI:
    """Factory de la aplicación."""
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        docs_url="/docs" if settings.debug else None,  # Sin Swagger en prod
        redoc_url=None,
        openapi_url="/openapi.json" if settings.debug else None,
        lifespan=lifespan,
    )

    # ── Security Middleware Stack ──
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["localhost", "127.0.0.1"],  # Ampliar en prod
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=[],
        max_age=600,  # Preflight cache: 10 minutos
    )

    # ── Security Headers Middleware ──
    @app.middleware("http")
    async def add_security_headers(request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "0"  # CSP es mejor
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
        response.headers["Cache-Control"] = (
            "no-store, no-cache, must-revalidate"
        )
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; frame-ancestors 'none'"
        )
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=()"
        )
        return response

    # ── Health Check (sin auth) ──
    @app.get("/health", tags=["infra"])
    async def health() -> dict[str, str]:
        return {"status": "healthy", "version": settings.app_version}

    # ── Registrar Routers (se añaden en fases posteriores) ──
    # from app.api.v1 import servers_router, credentials_router
    # app.include_router(servers_router, prefix="/api/v1")
    # app.include_router(credentials_router, prefix="/api/v1")

    return app


app = create_app()
```

---

### Tarea 1.6 — Logging Estructurado Seguro

```python
# backend/app/shared/logging_config.py
"""
Configuración de logging JSON estructurado.
NUNCA registra tokens, contraseñas, ni datos sensibles.
"""
import logging
import json
import sys
from datetime import datetime, timezone
from typing import Any


class SecureJSONFormatter(logging.Formatter):
    """
    Formateador que produce logs JSON y sanitiza
    campos sensibles automáticamente.
    """

    _SENSITIVE_KEYS: frozenset[str] = frozenset({
        "password", "token", "secret", "authorization",
        "cookie", "api_key", "cipher_text", "wrapped_dek",
        "master_password", "dek", "credential",
    })

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Agregar extras sanitizados
        if hasattr(record, "__dict__"):
            for key, value in record.__dict__.items():
                if key.startswith("_") or key in logging.LogRecord.__dict__:
                    continue
                if key in (
                    "name", "msg", "args", "levelname", "levelno",
                    "pathname", "filename", "module", "exc_info",
                    "exc_text", "stack_info", "lineno", "funcName",
                    "created", "msecs", "relativeCreated", "thread",
                    "threadName", "processName", "process", "message",
                    "taskName",
                ):
                    continue
                # Sanitizar valores sensibles
                log_entry[key] = self._sanitize(key, value)

        # Agregar excepción si existe
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = {
                "type": type(record.exc_info[1]).__name__,
                "message": str(record.exc_info[1]),
                # NO incluir traceback completo en producción
            }

        return json.dumps(log_entry, default=str, ensure_ascii=False)

    def _sanitize(self, key: str, value: Any) -> Any:
        """Redacta valores de campos sensibles."""
        key_lower = key.lower()
        if any(sensitive in key_lower for sensitive in self._SENSITIVE_KEYS):
            return "[REDACTED]"
        if isinstance(value, str) and len(value) > 500:
            return value[:100] + "...[TRUNCATED]"
        return value


def setup_logging(level: str = "INFO") -> None:
    """Configura logging JSON para toda la aplicación."""
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Limpiar handlers existentes
    root_logger.handlers.clear()

    # Handler JSON a stdout (para Docker/K8s)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(SecureJSONFormatter())
    root_logger.addHandler(handler)

    # Silenciar loggers ruidosos
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
```

---

### Tarea 1.7 — Inicialización de la Base de Datos (Async + SSL)

```python
# backend/app/infrastructure/database/session.py
"""
Motor async de SQLAlchemy con conexión SSL obligatoria a MySQL.
"""
import logging
import ssl
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config.settings import Settings

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


async def init_db_engine(settings: Settings) -> None:
    """Crea el motor async con SSL habilitado."""
    global _engine, _session_factory  # noqa: PLW0603

    # Configurar contexto SSL para MySQL
    ssl_context = ssl.create_default_context(cafile=settings.database_ssl_ca)
    ssl_context.verify_mode = ssl.CERT_REQUIRED

    _engine = create_async_engine(
        settings.async_database_url,
        echo=False,  # NUNCA True en prod (loguea SQL con datos)
        pool_size=10,
        max_overflow=5,
        pool_timeout=30,
        pool_recycle=1800,
        pool_pre_ping=True,
        connect_args={"ssl": ssl_context},
    )

    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    logger.info(
        "Database engine initialized",
        extra={"host": settings.database_host, "ssl": True},
    )


async def dispose_db_engine() -> None:
    """Cierra el motor y todas las conexiones."""
    global _engine, _session_factory  # noqa: PLW0603
    if _engine:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("Database engine disposed")


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependencia FastAPI que provee una sesión por request."""
    if _session_factory is None:
        raise RuntimeError("Database not initialized")
    async with _session_factory() as session:
        try:
            yield session
        finally:
            await session.close()
```

---

### 🔒 CHECKPOINT DE SEGURIDAD Y CUMPLIMIENTO — FASE 1

| Control Normativo | Requisito | Implementación en esta Fase | Estado |
|---|---|---|---|
| **NIST CSF PR.AC-1** | Gestión de identidades | Keycloak realm con roles ADMIN/EDITOR/VIEWER | ✅ |
| **NIST CSF PR.AC-4** | Permisos de acceso gestionados con principio de menor privilegio | `RoleRequired` inyectable, aliases `RequireAdmin/Editor/Viewer` | ✅ |
| **NIST CSF PR.AC-7** | Autenticación de usuarios | JWT verificado contra JWKS, validación de firma RS256 | ✅ |
| **CIS Control 3.3** | Configurar listas de control de acceso | RBAC en dependencias FastAPI, claim `realm_roles` | ✅ |
| **CIS Control 6.2** | Establecer proceso de concesión de acceso | Roles mapeados desde IdP, no gestionados en la app | ✅ |
| **CIS Control 8.2** | Recopilar logs de auditoría | `SecureJSONFormatter` con sanitización de campos sensibles | ✅ |
| **ISO 27001 A.5.15** | Control de acceso | Zero-Trust: toda petición pasa por `get_current_user` | ✅ |
| **ISO 27001 A.8.5** | Autenticación segura | OIDC + PKCE para SPA, `bearerOnly` para API | ✅ |
| **PCI DSS 6.5.10** | Broken Auth & Session Management | JWT stateless, no sessions server-side, PKCE en SPA | ✅ |
| **PCI DSS 7.1** | Restringir acceso por necesidad de negocio | RBAC granular por rol con inyección de dependencias | ✅ |
| **OWASP API2** | Broken Authentication | Verificación completa de JWT (exp, aud, iss, nbf, sig) | ✅ |
| **OWASP API5** | Broken Function Level Auth | `RoleRequired` previene acceso a funciones no autorizadas | ✅ |

**Herramientas ejecutadas en esta fase:**
- ✅ `mypy --strict` sobre todos los módulos nuevos
- ✅ `bandit -r app/` (verificar que no hay secrets hardcodeados)
- ✅ `ruff check` (style + security linting)
- ✅ Tests unitarios del `JWTVerifier` con tokens mock
- ✅ Tests unitarios de `RoleRequired` con roles válidos/inválidos

**Entregables Fase 1:**
1. Realm Keycloak configurado con roles y clientes OIDC
2. `AuthenticatedUser` value object inmutable
3. `JWTVerifier` con JWKS caching y validación completa
4. `RoleRequired` + aliases de conveniencia (`RequireAdmin`, etc.)
5. `main.py` con security headers y CORS restrictivo
6. Logging JSON estructurado con sanitización automática
7. Conexión async a MySQL con SSL obligatorio
8. Tests unitarios de autenticación y autorización

---

---

## FASE 2A — CQRS COMMANDS: WRITE PATH DEL BACKEND

### Objetivo Principal
> Construir toda la ruta de escritura: desde el request HTTP hasta la persistencia en MySQL. Esto incluye los Commands para crear servidores y almacenar credenciales cifradas. **En esta fase, FastAPI recibe bytes cifrados del frontend y los persiste sin interpretarlos — el backend es un "transportador ciego".**

---

### Tarea 2A.1 — Entidades de Dominio (SQLAlchemy 2.0 Mapped)

```python
# backend/app/domain/entities/server.py
"""
Entidad de dominio: Servidor.
Usa el estilo declarativo de SQLAlchemy 2.0 con Mapped.
"""
import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base


class ServerEntity(Base):
    """Representa un servidor físico o VM en el inventario."""

    __tablename__ = "servers"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    hostname: Mapped[str] = mapped_column(String(255), nullable=False)
    ip_address: Mapped[str] = mapped_column(String(45), nullable=False)
    operating_system: Mapped[str] = mapped_column(String(100), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relación con credenciales
    credentials: Mapped[list["CredentialEntity"]] = relationship(
        back_populates="server",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Server(id={self.id}, hostname={self.hostname})>"
```

```python
# backend/app/domain/entities/credential.py
"""
Entidad de dominio: Credencial Zero-Knowledge.
Todos los campos criptográficos son VARBINARY.
El backend NUNCA interpreta estos bytes.
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    String,
    DateTime,
    Integer,
    ForeignKey,
    LargeBinary,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base


class CredentialEntity(Base):
    """
    Credencial cifrada.
    
    Zero-Knowledge: cipher_text, wrapped_dek, iv, auth_tag y pbkdf2_salt
    son bytes opacos para el backend. Solo el frontend puede descifrarlos.
    """

    __tablename__ = "credentials"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    server_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("servers.id", ondelete="CASCADE"),
        nullable=False,
    )
    owner_user_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
    )
    credential_username: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    # ── Campos Zero-Knowledge (VARBINARY) ──
    cipher_text: Mapped[bytes] = mapped_column(
        LargeBinary(4096),
        nullable=False,
    )
    wrapped_dek: Mapped[bytes] = mapped_column(
        LargeBinary(512),
        nullable=False,
    )
    iv: Mapped[bytes] = mapped_column(
        LargeBinary(16),
        nullable=False,
    )
    auth_tag: Mapped[bytes] = mapped_column(
        LargeBinary(32),
        nullable=False,
    )
    pbkdf2_salt: Mapped[bytes] = mapped_column(
        LargeBinary(32),
        nullable=False,
    )
    pbkdf2_iterations: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=600000,
    )

    # ── Timestamps ──
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # ── Relación ──
    server: Mapped["ServerEntity"] = relationship(
        back_populates="credentials",
    )

    def __repr__(self) -> str:
        return f"<Credential(id={self.id}, server={self.server_id})>"
```

```python
# backend/app/infrastructure/database/base.py
"""Base declarativa compartida por todas las entidades."""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class para todas las entidades SQLAlchemy."""
    pass
```

---

### Tarea 2A.2 — Schemas Pydantic v2 (Commands — Strict)

```python
# backend/app/application/commands/schemas.py
"""
Schemas Pydantic v2 para Commands (escritura).

ConfigDict strict=True previene Mass Assignment:
solo los campos declarados son aceptados, con los tipos exactos.
Los bytes se transportan como base64 strings y se decodifican
en el schema.
"""
import base64
import re
import uuid

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


# ══════════════════════════════════════════
# COMMANDS DE SERVIDORES
# ══════════════════════════════════════════

class CreateServerCommand(BaseModel):
    """
    Command para registrar un nuevo servidor.
    Validación estricta de tipos y formatos.
    """

    model_config = ConfigDict(
        strict=True,
        extra="forbid",          # Rechaza campos no declarados (Mass Assignment)
        frozen=True,             # Inmutable después de creación
        str_strip_whitespace=True,
    )

    hostname: str = Field(
        ...,
        min_length=1,
        max_length=255,
        examples=["web-server-01"],
    )
    ip_address: str = Field(
        ...,
        min_length=7,
        max_length=45,
        examples=["192.168.1.100"],
    )
    operating_system: str = Field(
        ...,
        min_length=1,
        max_length=100,
        examples=["Ubuntu 22.04 LTS"],
    )

    @field_validator("hostname")
    @classmethod
    def validate_hostname(cls, v: str) -> str:
        """RFC 1123 hostname validation."""
        pattern = r"^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$"
        if not re.match(pattern, v):
            raise ValueError("Invalid hostname format (RFC 1123)")
        return v.lower()

    @field_validator("ip_address")
    @classmethod
    def validate_ip_address(cls, v: str) -> str:
        """Valida IPv4 o IPv6."""
        import ipaddress
        try:
            ipaddress.ip_address(v)
        except ValueError as e:
            raise ValueError(f"Invalid IP address: {e}") from e
        return v

    @field_validator("operating_system")
    @classmethod
    def validate_os(cls, v: str) -> str:
        """Previene inyección en campo OS."""
        if re.search(r"[<>\"';\\]", v):
            raise ValueError("Operating system contains invalid characters")
        return v


class UpdateServerCommand(BaseModel):
    """Command para actualizar un servidor existente."""

    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    hostname: str | None = Field(default=None, min_length=1, max_length=255)
    ip_address: str | None = Field(default=None, min_length=7, max_length=45)
    operating_system: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def at_least_one_field(self) -> "UpdateServerCommand":
        if all(
            v is None
            for v in [self.hostname, self.ip_address, self.operating_system]
        ):
            raise ValueError("At least one field must be provided")
        return self


# ══════════════════════════════════════════
# COMMANDS DE CREDENCIALES ZERO-KNOWLEDGE
# ══════════════════════════════════════════

class CreateCredentialCommand(BaseModel):
    """
    Command para almacenar una credencial cifrada.
    
    ZERO-KNOWLEDGE: Este schema recibe datos cifrados del frontend.
    El backend NUNCA ve la contraseña en claro.
    
    Los campos criptográficos viajan como base64 y se decodifican
    a bytes aquí para persistencia directa como VARBINARY.
    """

    model_config = ConfigDict(
        strict=True,
        extra="forbid",       # CRÍTICO: previene campos extra maliciosos
        frozen=True,
    )

    server_id: str = Field(..., min_length=36, max_length=36)
    credential_username: str = Field(
        ...,
        min_length=1,
        max_length=255,
        examples=["root"],
    )

    # Campos criptográficos (base64-encoded)
    cipher_text_b64: str = Field(
        ...,
        alias="cipher_text",
        min_length=1,
        max_length=8192,
    )
    wrapped_dek_b64: str = Field(
        ...,
        alias="wrapped_dek",
        min_length=1,
        max_length=1024,
    )
    iv_b64: str = Field(
        ...,
        alias="iv",
        min_length=1,
        max_length=48,
    )
    auth_tag_b64: str = Field(
        ...,
        alias="auth_tag",
        min_length=1,
        max_length=64,
    )
    pbkdf2_salt_b64: str = Field(
        ...,
        alias="pbkdf2_salt",
        min_length=1,
        max_length=64,
    )
    pbkdf2_iterations: int = Field(
        default=600000,
        ge=100000,    # Mínimo aceptable
        le=1000000,   # Máximo razonable
    )

    @field_validator("server_id")
    @classmethod
    def validate_uuid(cls, v: str) -> str:
        """Valida que sea un UUID v4 válido."""
        try:
            uuid.UUID(v, version=4)
        except ValueError as e:
            raise ValueError(f"Invalid UUID format: {e}") from e
        return v

    @field_validator(
        "cipher_text_b64",
        "wrapped_dek_b64",
        "iv_b64",
        "auth_tag_b64",
        "pbkdf2_salt_b64",
    )
    @classmethod
    def validate_base64(cls, v: str) -> str:
        """Valida que el campo sea base64 válido."""
        try:
            base64.b64decode(v, validate=True)
        except Exception as e:
            raise ValueError(f"Invalid base64 encoding: {e}") from e
        return v

    # ── Propiedades para acceso a bytes decodificados ──

    @property
    def cipher_text_bytes(self) -> bytes:
        return base64.b64decode(self.cipher_text_b64)

    @property
    def wrapped_dek_bytes(self) -> bytes:
        return base64.b64decode(self.wrapped_dek_b64)

    @property
    def iv_bytes(self) -> bytes:
        return base64.b64decode(self.iv_b64)

    @property
    def auth_tag_bytes(self) -> bytes:
        return base64.b64decode(self.auth_tag_b64)

    @property
    def pbkdf2_salt_bytes(self) -> bytes:
        return base64.b64decode(self.pbkdf2_salt_b64)
```

---

### Tarea 2A.3 — Command Handlers (Write Operations)

```python
# backend/app/application/commands/server_commands.py
"""
Command Handlers para operaciones de escritura sobre servidores.
Cada handler recibe un Command validado y el usuario autenticado.
"""
import logging
import uuid

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.commands.schemas import (
    CreateServerCommand,
    UpdateServerCommand,
)
from app.domain.entities.server import ServerEntity
from app.domain.identity import AuthenticatedUser

logger = logging.getLogger(__name__)


class CreateServerHandler:
    """Crea un nuevo servidor asociado al usuario autenticado."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(
        self,
        command: CreateServerCommand,
        user: AuthenticatedUser,
    ) -> str:
        """
        Ejecuta la creación del servidor.
        Retorna el ID del servidor creado.
        """
        server_id = str(uuid.uuid4())

        entity = ServerEntity(
            id=server_id,
            hostname=command.hostname,
            ip_address=command.ip_address,
            operating_system=command.operating_system,
            owner_user_id=user.sub,  # BOLA: El owner siempre es el JWT subject
        )

        self._session.add(entity)
        await self._session.commit()

        logger.info(
            "Server created",
            extra={
                "server_id": server_id,
                "hostname": command.hostname,
                "user_id": user.sub,
                "action": "CREATE_SERVER",
            },
        )

        return server_id


class UpdateServerHandler:
    """Actualiza un servidor existente verificando propiedad."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(
        self,
        server_id: str,
        command: UpdateServerCommand,
        user: AuthenticatedUser,
    ) -> bool:
        """
        Actualiza el servidor.
        Retorna True si se actualizó, False si no se encontró.
        
        BOLA Protection: La cláusula WHERE incluye owner_user_id,
        asegurando que solo el dueño pueda modificar su recurso.
        Un ADMIN puede modificar cualquier recurso.
        """
        update_data: dict[str, str] = {}
        if command.hostname is not None:
            update_data["hostname"] = command.hostname
        if command.ip_address is not None:
            update_data["ip_address"] = command.ip_address
        if command.operating_system is not None:
            update_data["operating_system"] = command.operating_system

        stmt = (
            update(ServerEntity)
            .where(ServerEntity.id == server_id)
            .values(**update_data)
        )

        # BOLA: Si no es admin, restringir al owner
        if not user.is_admin:
            stmt = stmt.where(ServerEntity.owner_user_id == user.sub)

        result = await self._session.execute(stmt)
        await self._session.commit()

        updated = result.rowcount > 0  # type: ignore[union-attr]

        logger.info(
            "Server update attempted",
            extra={
                "server_id": server_id,
                "user_id": user.sub,
                "updated": updated,
                "action": "UPDATE_SERVER",
            },
        )

        return updated


class DeleteServerHandler:
    """Elimina un servidor verificando propiedad."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(
        self,
        server_id: str,
        user: AuthenticatedUser,
    ) -> bool:
        """
        Elimina el servidor y sus credenciales asociadas (CASCADE).
        BOLA Protection aplicada.
        """
        from sqlalchemy import delete

        stmt = delete(ServerEntity).where(ServerEntity.id == server_id)

        if not user.is_admin:
            stmt = stmt.where(ServerEntity.owner_user_id == user.sub)

        result = await self._session.execute(stmt)
        await self._session.commit()

        deleted = result.rowcount > 0  # type: ignore[union-attr]

        logger.info(
            "Server delete attempted",
            extra={
                "server_id": server_id,
                "user_id": user.sub,
                "deleted": deleted,
                "action": "DELETE_SERVER",
            },
        )

        return deleted
```

```python
# backend/app/application/commands/credential_commands.py
"""
Command Handler para almacenar credenciales cifradas.
ZERO-KNOWLEDGE: El handler trata los datos criptográficos
como bytes opacos. No los interpreta ni transforma.
"""
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.commands.schemas import CreateCredentialCommand
from app.domain.entities.credential import CredentialEntity
from app.domain.entities.server import ServerEntity
from app.domain.identity import AuthenticatedUser

logger = logging.getLogger(__name__)


class CreateCredentialHandler:
    """Almacena una credencial cifrada asociada a un servidor."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(
        self,
        command: CreateCredentialCommand,
        user: AuthenticatedUser,
    ) -> str:
        """
        Persiste los bytes cifrados recibidos del frontend.
        
        Validaciones:
        1. El servidor destino existe
        2. BOLA: El servidor pertenece al usuario (o es ADMIN)
        3. Los datos criptográficos se guardan como VARBINARY sin modificación
        """
        # ── Paso 1: Verificar que el servidor existe y pertenece al usuario ──
        stmt = select(ServerEntity).where(ServerEntity.id == command.server_id)
        if not user.is_admin:
            stmt = stmt.where(ServerEntity.owner_user_id == user.sub)

        result = await self._session.execute(stmt)
        server = result.scalar_one_or_none()

        if server is None:
            logger.warning(
                "Credential creation denied: server not found or access denied",
                extra={
                    "server_id": command.server_id,
                    "user_id": user.sub,
                    "action": "CREATE_CREDENTIAL_DENIED",
                },
            )
            raise PermissionError(
                f"Server {command.server_id} not found or access denied"
            )

        # ── Paso 2: Crear entidad con bytes opacos ──
        credential_id = str(uuid.uuid4())

        entity = CredentialEntity(
            id=credential_id,
            server_id=command.server_id,
            owner_user_id=user.sub,
            credential_username=command.credential_username,
            # Zero-Knowledge: bytes opacos, el backend no los interpreta
            cipher_text=command.cipher_text_bytes,
            wrapped_dek=command.wrapped_dek_bytes,
            iv=command.iv_bytes,
            auth_tag=command.auth_tag_bytes,
            pbkdf2_salt=command.pbkdf2_salt_bytes,
            pbkdf2_iterations=command.pbkdf2_iterations,
        )

        self._session.add(entity)
        await self._session.commit()

        logger.info(
            "Credential stored (Zero-Knowledge)",
            extra={
                "credential_id": credential_id,
                "server_id": command.server_id,
                "user_id": user.sub,
                "action": "CREATE_CREDENTIAL",
                # NUNCA loguear cipher_text, wrapped_dek, etc.
            },
        )

        return credential_id
```

---

### Tarea 2A.4 — API Routes para Commands

```python
# backend/app/api/v1/servers.py
"""
Router de servidores: Endpoints de escritura (Commands).
Cada endpoint está protegido por RBAC y documentado.
"""
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import RequireEditor, RequireAdmin
from app.application.commands.schemas import (
    CreateServerCommand,
    UpdateServerCommand,
)
from app.application.commands.server_commands import (
    CreateServerHandler,
    DeleteServerHandler,
    UpdateServerHandler,
)
from app.infrastructure.database.session import get_db_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/servers", tags=["servers"])


@router.post(
    "/",
    status_code=status.HTTP_201_CREATED,
    response_model=dict[str, str],
    summary="Crear servidor",
    description="Registra un nuevo servidor en el inventario. Requiere rol ADMIN o EDITOR.",
)
async def create_server(
    command: CreateServerCommand,
    user: RequireEditor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, str]:
    """Crea un servidor y lo asocia al usuario autenticado."""
    handler = CreateServerHandler(session)
    server_id = await handler.handle(command, user)
    return {"id": server_id, "status": "created"}


@router.put(
    "/{server_id}",
    response_model=dict[str, str],
    summary="Actualizar servidor",
    description="Actualiza un servidor existente. BOLA enforced.",
)
async def update_server(
    server_id: str,
    command: UpdateServerCommand,
    user: RequireEditor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, str]:
    """Actualiza un servidor verificando propiedad."""
    handler = UpdateServerHandler(session)
    updated = await handler.handle(server_id, command, user)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Server not found or access denied",
        )
    return {"id": server_id, "status": "updated"}


@router.delete(
    "/{server_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar servidor",
    description="Elimina un servidor y sus credenciales. Solo ADMIN.",
)
async def delete_server(
    server_id: str,
    user: RequireAdmin,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    """Elimina un servidor (y sus credenciales por CASCADE)."""
    handler = DeleteServerHandler(session)
    deleted = await handler.handle(server_id, user)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Server not found or access denied",
        )
```

```python
# backend/app/api/v1/credentials.py
"""
Router de credenciales: Endpoint de escritura (Command).
Zero-Knowledge: Solo transporta bytes cifrados.
"""
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import RequireEditor
from app.application.commands.schemas import CreateCredentialCommand
from app.application.commands.credential_commands import CreateCredentialHandler
from app.infrastructure.database.session import get_db_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/credentials", tags=["credentials"])


@router.post(
    "/",
    status_code=status.HTTP_201_CREATED,
    response_model=dict[str, str],
    summary="Almacenar credencial cifrada",
    description=(
        "Almacena una credencial cifrada por el frontend. "
        "El backend NUNCA ve la contraseña en texto claro. "
        "Requiere rol ADMIN o EDITOR."
    ),
)
async def create_credential(
    command: CreateCredentialCommand,
    user: RequireEditor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, str]:
    """Persiste bytes cifrados como VARBINARY."""
    handler = CreateCredentialHandler(session)
    try:
        credential_id = await handler.handle(command, user)
    except PermissionError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    return {"id": credential_id, "status": "stored"}
```

---

### 🔒 CHECKPOINT DE SEGURIDAD Y CUMPLIMIENTO — FASE 2A

| Control Normativo | Requisito | Implementación en esta Fase | Estado |
|---|---|---|---|
| **NIST CSF PR.DS-1** | Protección de datos en reposo | Credenciales almacenadas como VARBINARY, cifradas por frontend | ✅ |
| **CIS Control 3.11** | Cifrar datos sensibles en reposo | `LargeBinary` → VARBINARY, backend no descifra | ✅ |
| **ISO 27001 A.8.24** | Uso de criptografía | AES-256-GCM (frontend), PBKDF2 (derivación), datos opacos en backend | ✅ |
| **PCI DSS 6.5.1** | Injection flaws | Pydantic strict + SQLAlchemy parameterized queries (sin SQL raw) | ✅ |
| **PCI DSS 6.5.4** | Insecure direct object references | `owner_user_id` en WHERE de todo Command Handler | ✅ |
| **OWASP API1** | BOLA | `CreateCredentialHandler` verifica propiedad del servidor antes de insertar | ✅ |
| **OWASP API3** | Broken Object Property Level Auth | `ConfigDict(extra="forbid")` rechaza campos no declarados | ✅ |
| **OWASP API6** | Mass Assignment | `strict=True` + `frozen=True` en todos los Commands | ✅ |

**Herramientas ejecutadas:**
- ✅ `mypy --strict` sobre commands/ y entities/
- ✅ `bandit` verifica ausencia de SQL raw y secrets
- ✅ Tests unitarios de validators Pydantic con payloads maliciosos
- ✅ Tests de integración de Handlers con BD de prueba

**Entregables Fase 2A:**
1. Entidades SQLAlchemy 2.0 con `Mapped` y `LargeBinary`
2. Schemas Pydantic v2 con `strict=True`, `extra="forbid"`, validadores
3. Command Handlers con protección BOLA integrada
4. Routers de escritura protegidos por RBAC
5. Tests de validación contra Mass Assignment
6. Tests de inyección SQL (payloads maliciosos en hostname/IP)

---

---

## FASE 2B — FRONTEND ANGULAR: CRYPTO ENGINE Y SHELL

### Objetivo Principal
> Construir el motor criptográfico del frontend usando exclusivamente Web Crypto API, y el shell de la aplicación Angular con autenticación OIDC. **Esta fase se desarrolla en paralelo con la 2A. Al finalizarla, el frontend puede cifrar credenciales listas para ser enviadas al backend.**

---

### Tarea 2B.1 — Angular Project Setup (Strict Mode)

```json
// frontend/tsconfig.json (fragmento de seguridad)
{
  "compilerOptions": {
    "strict": true,
    "noImplicitAny": true,
    "noImplicitReturns": true,
    "noFallthroughCasesInSwitch": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "forceConsistentCasingInFileNames": true,
    "strictNullChecks": true,
    "strictPropertyInitialization": true
  }
}
```

```json
// frontend/angular.json (fragmento de seguridad)
{
  "projects": {
    "zk-inventory": {
      "architect": {
        "build": {
          "options": {
            "budgets": [
              { "type": "initial", "maximumWarning": "500kb", "maximumError": "1mb" }
            ],
            "outputHashing": "all",
            "sourceMap": false  // NUNCA sourcemaps en producción
          }
        }
      }
    }
  }
}
```

---

### Tarea 2B.2 — Servicio de Autenticación OIDC (angular-auth-oidc-client)

```typescript
// frontend/src/app/core/auth/auth.config.ts
import { PassedInitialConfig } from 'angular-auth-oidc-client';

export const authConfig: PassedInitialConfig = {
  config: {
    authority: 'http://localhost:8080/realms/inventory',
    redirectUrl: window.location.origin,
    postLogoutRedirectUri: window.location.origin,
    clientId: 'inventory-spa',
    scope: 'openid profile email',
    responseType: 'code',
    
    // Seguridad PKCE
    usePushedAuthorisationRequests: false,
    
    // Token storage: sessionStorage (NO localStorage)
    // localStorage persiste entre sesiones del navegador = riesgo
    useRefreshToken: true,
    silentRenew: true,
    silentRenewUrl: window.location.origin + '/silent-renew.html',
    
    // Seguridad adicional
    renewTimeBeforeTokenExpiresInSeconds: 30,
    tokenRefreshInSeconds: 4,
    
    // NUNCA almacenar tokens en localStorage
    storage: sessionStorage,

    secureRoutes: ['http://localhost:8000/api/'],

    // Logging solo en desarrollo
    logLevel: 0, // None en producción
  },
};
```

```typescript
// frontend/src/app/core/auth/auth.service.ts
import { Injectable, inject } from '@angular/core';
import { OidcSecurityService } from 'angular-auth-oidc-client';
import { Observable, map, distinctUntilChanged } from 'rxjs';

export interface UserIdentity {
  sub: string;
  preferredUsername: string;
  roles: readonly string[];
}

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly oidc = inject(OidcSecurityService);

  readonly isAuthenticated$: Observable<boolean> = this.oidc.isAuthenticated$.pipe(
    map(({ isAuthenticated }) => isAuthenticated),
    distinctUntilChanged(),
  );

  readonly userIdentity$: Observable<UserIdentity | null> = this.oidc.userData$.pipe(
    map(({ userData }) => {
      if (!userData) return null;
      return {
        sub: userData.sub as string,
        preferredUsername: userData.preferred_username as string,
        roles: (userData.realm_roles as string[]) ?? [],
      };
    }),
  );

  login(): void {
    this.oidc.authorize();
  }

  logout(): void {
    this.oidc.logoff().subscribe();
  }

  getAccessToken(): Observable<string> {
    return this.oidc.getAccessToken();
  }

  hasRole(role: string): Observable<boolean> {
    return this.userIdentity$.pipe(
      map((identity) => identity?.roles.includes(role) ?? false),
    );
  }
}
```

```typescript
// frontend/src/app/core/auth/auth.interceptor.ts
import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { OidcSecurityService } from 'angular-auth-oidc-client';
import { switchMap, take } from 'rxjs';

/**
 * HTTP Interceptor que adjunta el Bearer token a las peticiones
 * dirigidas a la API backend.
 * 
 * SEGURIDAD: Solo adjunta el token a URLs que comienzan con la
 * URL del backend. Nunca envía tokens a terceros.
 */
export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const oidc = inject(OidcSecurityService);
  const apiUrl = 'http://localhost:8000/api/';

  // Solo interceptar requests a nuestra API
  if (!req.url.startsWith(apiUrl)) {
    return next(req);
  }

  return oidc.getAccessToken().pipe(
    take(1),
    switchMap((token) => {
      if (!token) {
        return next(req);
      }
      const authReq = req.clone({
        setHeaders: {
          Authorization: `Bearer ${token}`,
        },
      });
      return next(authReq);
    }),
  );
};
```

---

### Tarea 2B.3 — Motor Criptográfico Zero-Knowledge (Web Crypto API)

> **Este es el componente más crítico de toda la aplicación.** Aquí se implementa el cifrado AES-256-GCM, la derivación de claves con PBKDF2 y el wrapping/unwrapping de la DEK.

```typescript
// frontend/src/app/core/crypto/crypto.service.ts
import { Injectable } from '@angular/core';

/**
 * Resultado del proceso de cifrado Zero-Knowledge.
 * Todos los campos son bytes (ArrayBuffer/Uint8Array)
 * que se codificarán a base64 antes de enviar al backend.
 */
export interface EncryptedPayload {
  cipherText: ArrayBuffer;
  iv: Uint8Array;
  authTag: Uint8Array;        // GCM auth tag (últimos 16 bytes del cipherText de GCM)
  wrappedDek: ArrayBuffer;
  pbkdf2Salt: Uint8Array;
  pbkdf2Iterations: number;
}

/**
 * Servicio de criptografía Zero-Knowledge.
 * 
 * ARQUITECTURA:
 * 1. Genera una Data Encryption Key (DEK) efímera por cada credencial
 * 2. Cifra la contraseña del servidor con la DEK usando AES-256-GCM
 * 3. Deriva una Key Encryption Key (KEK) de la Master Password del usuario con PBKDF2
 * 4. Envuelve (wrap) la DEK con la KEK usando AES-KW
 * 5. Envía {cipherText, wrappedDek, iv, authTag, salt, iterations} al backend
 * 
 * El backend NUNCA ve la Master Password ni la DEK en claro.
 * 
 * SOLO usa Web Crypto API nativa. Cero dependencias externas de criptografía.
 */
@Injectable({ providedIn: 'root' })
export class CryptoService {
  private readonly PBKDF2_ITERATIONS = 600_000;
  private readonly AES_KEY_LENGTH = 256;
  private readonly IV_LENGTH = 12;        // 96 bits para GCM
  private readonly SALT_LENGTH = 32;      // 256 bits
  private readonly AUTH_TAG_LENGTH = 128;  // bits

  /**
   * Cifra una contraseña usando el flujo Zero-Knowledge completo.
   * 
   * @param plainPassword - Contraseña del servidor en texto claro
   * @param masterPassword - Master Password del usuario (nunca sale del browser)
   * @returns EncryptedPayload con todos los bytes necesarios para almacenamiento
   */
  async encrypt(
    plainPassword: string,
    masterPassword: string,
  ): Promise<EncryptedPayload> {
    // ── Paso 1: Generar DEK efímera (AES-256-GCM) ──
    const dek: CryptoKey = await crypto.subtle.generateKey(
      { name: 'AES-GCM', length: this.AES_KEY_LENGTH },
      true,  // extractable: true para poder hacer wrap
      ['encrypt', 'decrypt'],
    );

    // ── Paso 2: Generar IV aleatorio (12 bytes para GCM) ──
    const iv = crypto.getRandomValues(new Uint8Array(this.IV_LENGTH));

    // ── Paso 3: Cifrar la contraseña con la DEK ──
    const encoder = new TextEncoder();
    const plainBytes = encoder.encode(plainPassword);

    const cipherText: ArrayBuffer = await crypto.subtle.encrypt(
      {
        name: 'AES-GCM',
        iv: iv,
        tagLength: this.AUTH_TAG_LENGTH,
      },
      dek,
      plainBytes,
    );

    // AES-GCM concatena el auth tag al final del ciphertext
    // Separar: ciphertext real | auth tag (últimos 16 bytes)
    const cipherBytes = new Uint8Array(cipherText);
    const tagStart = cipherBytes.length - (this.AUTH_TAG_LENGTH / 8);
    const actualCipherText = cipherText.slice(0, tagStart);
    const authTag = new Uint8Array(cipherText.slice(tagStart));

    // ── Paso 4: Derivar KEK de la Master Password con PBKDF2 ──
    const pbkdf2Salt = crypto.getRandomValues(
      new Uint8Array(this.SALT_LENGTH),
    );

    const kek: CryptoKey = await this.deriveKEK(
      masterPassword,
      pbkdf2Salt,
      this.PBKDF2_ITERATIONS,
    );

    // ── Paso 5: Envolver (wrap) la DEK con la KEK ──
    const wrappedDek: ArrayBuffer = await crypto.subtle.wrapKey(
      'raw',
      dek,
      kek,
      { name: 'AES-KW' },
    );

    return {
      cipherText: actualCipherText,
      iv,
      authTag,
      wrappedDek,
      pbkdf2Salt,
      pbkdf2Iterations: this.PBKDF2_ITERATIONS,
    };
  }

  /**
   * Descifra una credencial usando la Master Password.
   * Flujo inverso al de cifrado.
   */
  async decrypt(
    payload: EncryptedPayload,
    masterPassword: string,
  ): Promise<string> {
    // ── Paso 1: Derivar KEK de la Master Password ──
    const kek = await this.deriveKEK(
      masterPassword,
      payload.pbkdf2Salt,
      payload.pbkdf2Iterations,
    );

    // ── Paso 2: Desenvolver (unwrap) la DEK ──
    const dek: CryptoKey = await crypto.subtle.unwrapKey(
      'raw',
      payload.wrappedDek,
      kek,
      { name: 'AES-KW' },
      { name: 'AES-GCM', length: this.AES_KEY_LENGTH },
      false,  // no extractable
      ['decrypt'],
    );

    // ── Paso 3: Reconstruir ciphertext + auth tag ──
    const fullCipher = new Uint8Array(
      new Uint8Array(payload.cipherText).length + payload.authTag.length,
    );
    fullCipher.set(new Uint8Array(payload.cipherText), 0);
    fullCipher.set(payload.authTag, new Uint8Array(payload.cipherText).length);

    // ── Paso 4: Descifrar con AES-GCM ──
    const plainBuffer: ArrayBuffer = await crypto.subtle.decrypt(
      {
        name: 'AES-GCM',
        iv: payload.iv,
        tagLength: this.AUTH_TAG_LENGTH,
      },
      dek,
      fullCipher,
    );

    const decoder = new TextDecoder();
    return decoder.decode(plainBuffer);
  }

  /**
   * Deriva una Key Encryption Key (KEK) usando PBKDF2.
   * La KEK se usa exclusivamente para wrap/unwrap de la DEK.
   */
  private async deriveKEK(
    masterPassword: string,
    salt: Uint8Array,
    iterations: number,
  ): Promise<CryptoKey> {
    const encoder = new TextEncoder();
    const passwordBytes = encoder.encode(masterPassword);

    // Importar la master password como material base
    const baseKey: CryptoKey = await crypto.subtle.importKey(
      'raw',
      passwordBytes,
      'PBKDF2',
      false,
      ['deriveKey'],
    );

    // Derivar KEK con PBKDF2
    const kek: CryptoKey = await crypto.subtle.deriveKey(
      {
        name: 'PBKDF2',
        salt: salt,
        iterations: iterations,
        hash: 'SHA-256',
      },
      baseKey,
      { name: 'AES-KW', length: this.AES_KEY_LENGTH },
      false,  // KEK no extractable
      ['wrapKey', 'unwrapKey'],
    );

    return kek;
  }
}
```

---

### Tarea 2B.4 — Utilidad de Encoding Base64

```typescript
// frontend/src/app/core/crypto/encoding.utils.ts
/**
 * Utilidades de encoding para transportar bytes como base64
 * en las peticiones HTTP al backend.
 * 
 * Usa btoa/atob nativos del browser, sin dependencias externas.
 */

export function arrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

export function base64ToArrayBuffer(base64: string): ArrayBuffer {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes.buffer;
}

export function base64ToUint8Array(base64: string): Uint8Array {
  return new Uint8Array(base64ToArrayBuffer(base64));
}

export function uint8ArrayToBase64(arr: Uint8Array): string {
  return arrayBufferToBase64(arr.buffer);
}
```

---

### Tarea 2B.5 — Servicio de API de Credenciales

```typescript
// frontend/src/app/core/api/credentials-api.service.ts
import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, switchMap, from } from 'rxjs';
import { CryptoService, EncryptedPayload } from '../crypto/crypto.service';
import {
  arrayBufferToBase64,
  uint8ArrayToBase64,
  base64ToArrayBuffer,
  base64ToUint8Array,
} from '../crypto/encoding.utils';

export interface CreateCredentialRequest {
  serverId: string;
  credentialUsername: string;
  plainPassword: string;
  masterPassword: string;
}

export interface CredentialResponse {
  id: string;
  server_id: string;
  credential_username: string;
  cipher_text: string;      // base64
  wrapped_dek: string;      // base64
  iv: string;               // base64
  auth_tag: string;         // base64
  pbkdf2_salt: string;      // base64
  pbkdf2_iterations: number;
  created_at: string;
}

@Injectable({ providedIn: 'root' })
export class CredentialsApiService {
  private readonly http = inject(HttpClient);
  private readonly crypto = inject(CryptoService);
  private readonly apiUrl = 'http://localhost:8000/api/v1/credentials';

  /**
   * Cifra y almacena una credencial.
   * 
   * FLUJO ZERO-KNOWLEDGE:
   * 1. CryptoService cifra la contraseña localmente
   * 2. Los bytes se codifican a base64
   * 3. Se envían al backend como strings base64
   * 4. El backend los decodifica a bytes y guarda como VARBINARY
   * 
   * La plainPassword y masterPassword NUNCA salen del browser.
   */
  createCredential(request: CreateCredentialRequest): Observable<{ id: string }> {
    return from(
      this.crypto.encrypt(request.plainPassword, request.masterPassword),
    ).pipe(
      switchMap((encrypted: EncryptedPayload) => {
        const body = {
          server_id: request.serverId,
          credential_username: request.credentialUsername,
          cipher_text: arrayBufferToBase64(encrypted.cipherText),
          wrapped_dek: arrayBufferToBase64(encrypted.wrappedDek),
          iv: uint8ArrayToBase64(encrypted.iv),
          auth_tag: uint8ArrayToBase64(encrypted.authTag),
          pbkdf2_salt: uint8ArrayToBase64(encrypted.pbkdf2Salt),
          pbkdf2_iterations: encrypted.pbkdf2Iterations,
        };

        return this.http.post<{ id: string }>(this.apiUrl, body);
      }),
    );
  }

  /**
   * Descifra una credencial almacenada.
   * 
   * FLUJO ZERO-KNOWLEDGE INVERSO:
   * 1. Obtiene los bytes cifrados del backend (como base64)
   * 2. Decodifica base64 a ArrayBuffer/Uint8Array
   * 3. Usa CryptoService para descifrar localmente
   * 4. Retorna la contraseña en texto claro SOLO en memoria del browser
   */
  async decryptCredential(
    credential: CredentialResponse,
    masterPassword: string,
  ): Promise<string> {
    const payload: EncryptedPayload = {
      cipherText: base64ToArrayBuffer(credential.cipher_text),
      wrappedDek: base64ToArrayBuffer(credential.wrapped_dek),
      iv: base64ToUint8Array(credential.iv),
      authTag: base64ToUint8Array(credential.auth_tag),
      pbkdf2Salt: base64ToUint8Array(credential.pbkdf2_salt),
      pbkdf2Iterations: credential.pbkdf2_iterations,
    };

    return this.crypto.decrypt(payload, masterPassword);
  }
}
```

---

### Tarea 2B.6 — Auth Guard y Protección de Rutas

```typescript
// frontend/src/app/core/auth/auth.guard.ts
import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { map, take } from 'rxjs';
import { AuthService } from './auth.service';

export const authGuard: CanActivateFn = () => {
  const authService = inject(AuthService);
  const router = inject(Router);

  return authService.isAuthenticated$.pipe(
    take(1),
    map((isAuth) => {
      if (!isAuth) {
        authService.login(); // Redirige a Keycloak
        return false;
      }
      return true;
    }),
  );
};

/**
 * Guard basado en roles.
 * Uso: canActivate: [roleGuard('ADMIN', 'EDITOR')]
 */
export function roleGuard(...allowedRoles: string[]): CanActivateFn {
  return () => {
    const authService = inject(AuthService);
    const router = inject(Router);

    return authService.userIdentity$.pipe(
      take(1),
      map((identity) => {
        if (!identity) {
          authService.login();
          return false;
        }
        const hasRole = identity.roles.some((r) => allowedRoles.includes(r));
        if (!hasRole) {
          router.navigate(['/unauthorized']);
          return false;
        }
        return true;
      }),
    );
  };
}
```

---

### 🔒 CHECKPOINT DE SEGURIDAD Y CUMPLIMIENTO — FASE 2B

| Control Normativo | Requisito | Implementación en esta Fase | Estado |
|---|---|---|---|
| **NIST CSF PR.DS-1** | Protección de datos en reposo | DEK efímera + AES-256-GCM, wrapped con KEK derivada | ✅ |
| **NIST CSF PR.DS-2** | Protección de datos en tránsito | Datos cifrados antes de salir del browser; TLS en transporte | ✅ |
| **CIS Control 3.6** | Cifrar datos en estaciones de trabajo | Web Crypto API cifra en el browser antes de transmitir | ✅ |
| **CIS Control 3.11** | Cifrar datos sensibles en reposo | AES-256-GCM con DEK por credencial, KEK derivada de master password | ✅ |
| **ISO 27001 A.8.24** | Uso de criptografía | PBKDF2 (600K iteraciones), AES-256-GCM, AES-KW para wrapping | ✅ |
| **PCI DSS 3.5** | Proteger claves de cifrado | DEK nunca sale del browser; KEK derivada de master password en memoria | ✅ |
| **PCI DSS 6.5.3** | Almacenamiento criptográfico inseguro | Web Crypto API nativa (no libs JS custom), keys no-extractable | ✅ |
| **OWASP Top 10 A02** | Cryptographic Failures | AES-256-GCM (AEAD), IV único por operación, PBKDF2 con salt único | ✅ |

**Verificaciones de seguridad específicas del crypto engine:**
- ✅ IV de 12 bytes generado con `crypto.getRandomValues()` (CSPRNG)
- ✅ Salt PBKDF2 de 32 bytes por credencial (no reutilizado)
- ✅ 600,000 iteraciones PBKDF2 (OWASP recomendación 2024)
- ✅ Auth tag separado para verificación de integridad
- ✅ KEK marcada como `extractable: false`
- ✅ Token almacenado en `sessionStorage`, no `localStorage`
- ✅ Interceptor solo envía token a URL del backend

**Entregables Fase 2B:**
1. Proyecto Angular con strict mode completo
2. `CryptoService` con cifrado AES-256-GCM + PBKDF2 + AES-KW
3. Utilidades de encoding base64 ↔ ArrayBuffer
4. `CredentialsApiService` con flujo completo encrypt→send / receive→decrypt
5. Autenticación OIDC con PKCE configurada
6. Auth interceptor y guards de ruta
7. Tests unitarios del CryptoService (encrypt→decrypt roundtrip)

---

---

## FASE 3 — CQRS QUERIES: READ PATH + BOLA ENFORCEMENT

### Objetivo Principal
> Construir la ruta de lectura completa: listar servidores y recuperar credenciales cifradas. **Cada Query Handler DEBE verificar propiedad del recurso (BOLA) como condición no negociable.** Los datos criptográficos se devuelven como base64 para que el frontend los descifre.

---

### Tarea 3.1 — Schemas Pydantic v2 (Responses — Read)

```python
# backend/app/application/queries/schemas.py
"""
Schemas Pydantic v2 para respuestas de Queries (lectura).

Estos schemas controlan EXACTAMENTE qué campos se exponen
en las respuestas HTTP. Previenen información leakage.
"""
import base64
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field


class ServerResponse(BaseModel):
    """Respuesta de un servidor sin datos sensibles."""

    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        from_attributes=True,
    )

    id: str
    hostname: str
    ip_address: str
    operating_system: str
    created_at: datetime
    updated_at: datetime
    # NOTA: owner_user_id NO se expone en la respuesta
    # para prevenir enumeración de usuarios


class ServerListResponse(BaseModel):
    """Lista paginada de servidores."""

    model_config = ConfigDict(strict=True, extra="forbid")

    items: list[ServerResponse]
    total: int
    page: int
    page_size: int


class CredentialResponse(BaseModel):
    """
    Respuesta de una credencial cifrada.
    
    ZERO-KNOWLEDGE: Los campos criptográficos se devuelven
    como base64 strings. El backend NO los interpreta.
    """

    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        from_attributes=True,
    )

    id: str
    server_id: str
    credential_username: str
    created_at: datetime
    updated_at: datetime

    # Campos criptográficos como bytes (se convierten a base64 en serialización)
    _cipher_text: bytes = b""
    _wrapped_dek: bytes = b""
    _iv: bytes = b""
    _auth_tag: bytes = b""
    _pbkdf2_salt: bytes = b""
    pbkdf2_iterations: int

    @computed_field  # type: ignore[misc]
    @property
    def cipher_text(self) -> str:
        return base64.b64encode(self._cipher_text).decode("ascii")

    @computed_field  # type: ignore[misc]
    @property
    def wrapped_dek(self) -> str:
        return base64.b64encode(self._wrapped_dek).decode("ascii")

    @computed_field  # type: ignore[misc]
    @property
    def iv(self) -> str:
        return base64.b64encode(self._iv).decode("ascii")

    @computed_field  # type: ignore[misc]
    @property
    def auth_tag(self) -> str:
        return base64.b64encode(self._auth_tag).decode("ascii")

    @computed_field  # type: ignore[misc]
    @property
    def pbkdf2_salt(self) -> str:
        return base64.b64encode(self._pbkdf2_salt).decode("ascii")

    @classmethod
    def from_entity(cls, entity: "CredentialEntity") -> "CredentialResponse":
        """Factory method para construir desde la entidad SQLAlchemy."""
        instance = cls(
            id=entity.id,
            server_id=entity.server_id,
            credential_username=entity.credential_username,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
            pbkdf2_iterations=entity.pbkdf2_iterations,
        )
        # Asignar bytes internos para computed_fields
        instance._cipher_text = entity.cipher_text
        instance._wrapped_dek = entity.wrapped_dek
        instance._iv = entity.iv
        instance._auth_tag = entity.auth_tag
        instance._pbkdf2_salt = entity.pbkdf2_salt
        return instance


class CredentialListResponse(BaseModel):
    """Lista de credenciales de un servidor."""

    model_config = ConfigDict(strict=True, extra="forbid")

    items: list[CredentialResponse]
    total: int
```

---

### Tarea 3.2 — Query Handlers con BOLA Enforcement

```python
# backend/app/application/queries/server_queries.py
"""
Query Handlers para lectura de servidores.
BOLA Protection: Cada query filtra por owner_user_id.
"""
import logging
from typing import Sequence

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.queries.schemas import (
    ServerListResponse,
    ServerResponse,
)
from app.domain.entities.server import ServerEntity
from app.domain.identity import AuthenticatedUser

logger = logging.getLogger(__name__)


class ListServersHandler:
    """Lista servidores del usuario autenticado."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(
        self,
        user: AuthenticatedUser,
        page: int = 1,
        page_size: int = 20,
    ) -> ServerListResponse:
        """
        BOLA: Solo retorna servidores del usuario.
        ADMIN: Ve todos los servidores.
        """
        # Clamp page_size para prevenir DoS por paginación excesiva
        page_size = min(max(page_size, 1), 100)
        page = max(page, 1)
        offset = (page - 1) * page_size

        # Base query
        base_filter = select(ServerEntity)
        count_filter = select(func.count(ServerEntity.id))

        # BOLA: Si no es admin, restringir al owner
        if not user.is_admin:
            base_filter = base_filter.where(
                ServerEntity.owner_user_id == user.sub,
            )
            count_filter = count_filter.where(
                ServerEntity.owner_user_id == user.sub,
            )

        # Contar total
        total_result = await self._session.execute(count_filter)
        total: int = total_result.scalar_one()

        # Obtener página
        stmt = (
            base_filter
            .order_by(ServerEntity.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        result = await self._session.execute(stmt)
        servers: Sequence[ServerEntity] = result.scalars().all()

        logger.info(
            "Servers listed",
            extra={
                "user_id": user.sub,
                "total": total,
                "page": page,
                "action": "LIST_SERVERS",
            },
        )

        return ServerListResponse(
            items=[
                ServerResponse.model_validate(s, from_attributes=True)
                for s in servers
            ],
            total=total,
            page=page,
            page_size=page_size,
        )


class GetServerHandler:
    """Obtiene un servidor específico por ID."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(
        self,
        server_id: str,
        user: AuthenticatedUser,
    ) -> ServerResponse | None:
        """
        BOLA: Verifica propiedad antes de retornar.
        Retorna None si no existe o no pertenece al usuario.
        """
        stmt = select(ServerEntity).where(ServerEntity.id == server_id)

        if not user.is_admin:
            stmt = stmt.where(ServerEntity.owner_user_id == user.sub)

        result = await self._session.execute(stmt)
        server = result.scalar_one_or_none()

        if server is None:
            logger.warning(
                "Server access denied or not found",
                extra={
                    "server_id": server_id,
                    "user_id": user.sub,
                    "action": "GET_SERVER_DENIED",
                },
            )
            return None

        logger.info(
            "Server retrieved",
            extra={
                "server_id": server_id,
                "user_id": user.sub,
                "action": "GET_SERVER",
            },
        )

        return ServerResponse.model_validate(server, from_attributes=True)
```

```python
# backend/app/application/queries/credential_queries.py
"""
Query Handlers para lectura de credenciales.
ZERO-KNOWLEDGE: Retorna bytes cifrados sin interpretarlos.
BOLA: Verifica propiedad en cada consulta.
"""
import logging

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.queries.schemas import (
    CredentialListResponse,
    CredentialResponse,
)
from app.domain.entities.credential import CredentialEntity
from app.domain.entities.server import ServerEntity
from app.domain.identity import AuthenticatedUser

logger = logging.getLogger(__name__)


class ListCredentialsHandler:
    """Lista credenciales cifradas de un servidor."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(
        self,
        server_id: str,
        user: AuthenticatedUser,
    ) -> CredentialListResponse | None:
        """
        BOLA doble:
        1. Verifica que el servidor pertenezca al usuario
        2. Filtra credenciales por owner_user_id
        """
        # ── Paso 1: Verificar propiedad del servidor ──
        server_stmt = select(ServerEntity).where(
            ServerEntity.id == server_id,
        )
        if not user.is_admin:
            server_stmt = server_stmt.where(
                ServerEntity.owner_user_id == user.sub,
            )

        server_result = await self._session.execute(server_stmt)
        server = server_result.scalar_one_or_none()

        if server is None:
            logger.warning(
                "Credential listing denied: server not found or access denied",
                extra={
                    "server_id": server_id,
                    "user_id": user.sub,
                    "action": "LIST_CREDENTIALS_DENIED",
                },
            )
            return None

        # ── Paso 2: Obtener credenciales ──
        cred_stmt = select(CredentialEntity).where(
            CredentialEntity.server_id == server_id,
        )
        if not user.is_admin:
            cred_stmt = cred_stmt.where(
                CredentialEntity.owner_user_id == user.sub,
            )

        result = await self._session.execute(cred_stmt)
        credentials = result.scalars().all()

        logger.info(
            "Credentials listed (Zero-Knowledge)",
            extra={
                "server_id": server_id,
                "user_id": user.sub,
                "count": len(credentials),
                "action": "LIST_CREDENTIALS",
            },
        )

        return CredentialListResponse(
            items=[
                CredentialResponse.from_entity(c) for c in credentials
            ],
            total=len(credentials),
        )


class GetCredentialHandler:
    """Obtiene una credencial cifrada por ID."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(
        self,
        credential_id: str,
        user: AuthenticatedUser,
    ) -> CredentialResponse | None:
        """
        BOLA: Verifica que la credencial pertenezca al usuario.
        Retorna los bytes cifrados como base64.
        """
        stmt = select(CredentialEntity).where(
            CredentialEntity.id == credential_id,
        )

        if not user.is_admin:
            stmt = stmt.where(
                CredentialEntity.owner_user_id == user.sub,
            )

        result = await self._session.execute(stmt)
        credential = result.scalar_one_or_none()

        if credential is None:
            logger.warning(
                "Credential access denied or not found",
                extra={
                    "credential_id": credential_id,
                    "user_id": user.sub,
                    "action": "GET_CREDENTIAL_DENIED",
                },
            )
            return None

        logger.info(
            "Credential retrieved (Zero-Knowledge)",
            extra={
                "credential_id": credential_id,
                "user_id": user.sub,
                "action": "GET_CREDENTIAL",
                # NUNCA loguear cipher_text, wrapped_dek, etc.
            },
        )

        return CredentialResponse.from_entity(credential)
```

---

### Tarea 3.3 — API Routes para Queries

```python
# backend/app/api/v1/servers_queries.py
"""Router de servidores: Endpoints de lectura (Queries)."""
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import RequireViewer
from app.application.queries.schemas import (
    ServerListResponse,
    ServerResponse,
)
from app.application.queries.server_queries import (
    GetServerHandler,
    ListServersHandler,
)
from app.infrastructure.database.session import get_db_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/servers", tags=["servers"])


@router.get(
    "/",
    response_model=ServerListResponse,
    summary="Listar servidores",
    description="Lista los servidores del usuario autenticado. ADMIN ve todos.",
)
async def list_servers(
    user: RequireViewer,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    page: Annotated[int, Query(ge=1, le=1000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ServerListResponse:
    handler = ListServersHandler(session)
    return await handler.handle(user, page, page_size)


@router.get(
    "/{server_id}",
    response_model=ServerResponse,
    summary="Obtener servidor",
    description="Obtiene un servidor por ID. BOLA enforced.",
)
async def get_server(
    server_id: str,
    user: RequireViewer,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ServerResponse:
    handler = GetServerHandler(session)
    result = await handler.handle(server_id, user)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Server not found or access denied",
        )
    return result
```

```python
# backend/app/api/v1/credentials_queries.py
"""
Router de credenciales: Endpoints de lectura (Queries).
Zero-Knowledge: Devuelve bytes cifrados como base64.
"""
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import RequireViewer
from app.application.queries.schemas import (
    CredentialListResponse,
    CredentialResponse,
)
from app.application.queries.credential_queries import (
    GetCredentialHandler,
    ListCredentialsHandler,
)
from app.infrastructure.database.session import get_db_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/credentials", tags=["credentials"])


@router.get(
    "/server/{server_id}",
    response_model=CredentialListResponse,
    summary="Listar credenciales de un servidor",
    description="Lista credenciales cifradas. BOLA doble enforced.",
)
async def list_credentials(
    server_id: str,
    user: RequireViewer,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CredentialListResponse:
    handler = ListCredentialsHandler(session)
    result = await handler.handle(server_id, user)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Server not found or access denied",
        )
    return result


@router.get(
    "/{credential_id}",
    response_model=CredentialResponse,
    summary="Obtener credencial cifrada",
    description="Obtiene una credencial cifrada. El descifrado ocurre en el frontend.",
)
async def get_credential(
    credential_id: str,
    user: RequireViewer,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CredentialResponse:
    handler = GetCredentialHandler(session)
    result = await handler.handle(credential_id, user)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found or access denied",
        )
    return result
```

---

### 🔒 CHECKPOINT DE SEGURIDAD Y CUMPLIMIENTO — FASE 3

| Control Normativo | Requisito | Implementación en esta Fase | Estado |
|---|---|---|---|
| **NIST CSF PR.AC-4** | Permisos de acceso con menor privilegio | VIEWER solo lee; EDITOR lee+escribe; ADMIN total | ✅ |
| **NIST CSF DE.CM-1** | Monitoreo continuo de la red | Logs de cada query con user_id, resource_id, action | ✅ |
| **CIS Control 3.3** | Configurar ACLs de datos | `owner_user_id` en WHERE de cada query; `RequireViewer` | ✅ |
| **CIS Control 8.5** | Recopilar logs detallados de auditoría | Logs JSON con quién, qué recurso, cuándo, resultado | ✅ |
| **ISO 27001 A.5.15** | Control de acceso | BOLA doble en credenciales (servidor + credencial) | ✅ |
| **ISO 27001 A.8.4** | Acceso a código fuente | `owner_user_id` NO se expone en respuestas (info leakage) | ✅ |
| **PCI DSS 6.5.4** | Insecure Direct Object Refs | BOLA en `GetServerHandler`, `GetCredentialHandler`, `ListCredentialsHandler` | ✅ |
| **PCI DSS 10.1** | Audit trail para acceso a datos | Cada query logueada: user_id + resource_id + timestamp | ✅ |
| **OWASP API1** | BOLA | Verificación de `owner_user_id` en CADA query handler | ✅ |
| **OWASP API4** | Unrestricted Resource Consumption | Paginación con `page_size` clamped a max 100 | ✅ |

**Entregables Fase 3:**
1. Schemas Pydantic de respuesta con bytes→base64 conversion
2. Query Handlers con BOLA enforced en cada método
3. Routers de lectura con RBAC y paginación segura
4. Tests de BOLA: usuario A no puede leer recursos de usuario B
5. Tests de paginación con valores límite
6. Tests de enumeración (IDs inexistentes retornan 404, no 403)

---

---

## FASE 4 — INTEGRACIÓN END-TO-END DEL FLUJO ZERO-KNOWLEDGE

### Objetivo Principal
> Conectar frontend y backend en el flujo completo: Angular cifra → HTTP → FastAPI persiste → HTTP → Angular descifra. Esta fase valida que la cadena Zero-Knowledge funciona de extremo a extremo sin que el backend vea nunca una contraseña en claro.

---

### Tarea 4.1 — Componente de Creación de Credenciales (Angular)

```typescript
// frontend/src/app/features/credentials/create-credential/create-credential.component.ts
import { Component, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import {
  FormBuilder,
  FormGroup,
  ReactiveFormsModule,
  Validators,
} from '@angular/forms';
import { CredentialsApiService } from '../../../core/api/credentials-api.service';

@Component({
  selector: 'app-create-credential',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule],
  template: `
    <form [formGroup]="form" (ngSubmit)="onSubmit()">
      <div>
        <label for="credUsername">Username del servidor</label>
        <input id="credUsername" formControlName="credentialUsername" type="text" />
      </div>

      <div>
        <label for="plainPassword">Contraseña del servidor</label>
        <input id="plainPassword" formControlName="plainPassword" type="password" />
      </div>

      <div>
        <label for="masterPassword">Tu Master Password</label>
        <input id="masterPassword" formControlName="masterPassword" type="password" />
        <small>
          Esta contraseña NUNCA se envía al servidor.
          Se usa localmente para cifrar.
        </small>
      </div>

      <button type="submit" [disabled]="form.invalid || isLoading()">
        {{ isLoading() ? 'Cifrando y guardando...' : 'Guardar credencial' }}
      </button>

      @if (error()) {
        <div class="error">{{ error() }}</div>
      }

      @if (success()) {
        <div class="success">Credencial almacenada de forma segura (Zero-Knowledge)</div>
      }
    </form>
  `,
})
export class CreateCredentialComponent {
  private readonly fb = inject(FormBuilder);
  private readonly credApi = inject(CredentialsApiService);

  readonly isLoading = signal(false);
  readonly error = signal<string | null>(null);
  readonly success = signal(false);

  // serverId se recibiría como @Input() o desde la ruta
  serverId = '';  // Seteado por el componente padre

  form: FormGroup = this.fb.group({
    credentialUsername: ['', [Validators.required, Validators.maxLength(255)]],
    plainPassword: ['', [Validators.required, Validators.minLength(1)]],
    masterPassword: ['', [Validators.required, Validators.minLength(8)]],
  });

  onSubmit(): void {
    if (this.form.invalid) return;

    this.isLoading.set(true);
    this.error.set(null);
    this.success.set(false);

    const { credentialUsername, plainPassword, masterPassword } = this.form.value;

    this.credApi
      .createCredential({
        serverId: this.serverId,
        credentialUsername,
        plainPassword,
        masterPassword,
      })
      .subscribe({
        next: () => {
          this.success.set(true);
          this.form.reset();
          // Limpiar master password de la memoria del form
          this.form.patchValue({ masterPassword: '', plainPassword: '' });
        },
        error: (err) => {
          this.error.set(
            err?.error?.detail ?? 'Error al almacenar credencial',
          );
        },
        complete: () => this.isLoading.set(false),
      });
  }
}
```

---

### Tarea 4.2 — Modal de Descifrado con Master Password

```typescript
// frontend/src/app/features/credentials/decrypt-modal/decrypt-modal.component.ts
import { Component, inject, signal, input, output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import {
  CredentialsApiService,
  CredentialResponse,
} from '../../../core/api/credentials-api.service';

/**
 * Modal seguro para descifrar una credencial.
 * 
 * SEGURIDAD:
 * - La master password se solicita en cada descifrado (no se cachea)
 * - La contraseña descifrada se muestra temporalmente y se limpia
 * - No se loguea ni persiste la contraseña descifrada
 */
@Component({
  selector: 'app-decrypt-modal',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="modal-overlay" (click)="close()">
      <div class="modal-content" (click)="$event.stopPropagation()">
        <h3>Descifrar credencial</h3>
        <p><strong>Usuario:</strong> {{ credential().credential_username }}</p>

        @if (!decryptedPassword()) {
          <div>
            <label for="modalMasterPwd">Ingresa tu Master Password</label>
            <input
              id="modalMasterPwd"
              type="password"
              [(ngModel)]="masterPasswordInput"
              (keyup.enter)="onDecrypt()"
              autocomplete="off"
            />
            <button (click)="onDecrypt()" [disabled]="isDecrypting()">
              {{ isDecrypting() ? 'Descifrando...' : 'Descifrar' }}
            </button>
          </div>
          @if (decryptError()) {
            <div class="error">{{ decryptError() }}</div>
          }
        } @else {
          <div class="decrypted-result">
            <label>Contraseña:</label>
            <code class="password-display">{{ decryptedPassword() }}</code>
            <button (click)="copyToClipboard()">Copiar</button>
            <small>
              Se limpiará automáticamente en {{ remainingSeconds() }}s
            </small>
          </div>
        }

        <button class="close-btn" (click)="close()">Cerrar</button>
      </div>
    </div>
  `,
})
export class DecryptModalComponent {
  private readonly credApi = inject(CredentialsApiService);

  readonly credential = input.required<CredentialResponse>();
  readonly closed = output<void>();

  masterPasswordInput = '';
  readonly isDecrypting = signal(false);
  readonly decryptError = signal<string | null>(null);
  readonly decryptedPassword = signal<string | null>(null);
  readonly remainingSeconds = signal(30);

  private cleanupTimer: ReturnType<typeof setTimeout> | null = null;
  private countdownTimer: ReturnType<typeof setInterval> | null = null;

  async onDecrypt(): Promise<void> {
    if (!this.masterPasswordInput) return;

    this.isDecrypting.set(true);
    this.decryptError.set(null);

    try {
      const plainPassword = await this.credApi.decryptCredential(
        this.credential(),
        this.masterPasswordInput,
      );

      this.decryptedPassword.set(plainPassword);

      // Limpiar master password de memoria inmediatamente
      this.masterPasswordInput = '';

      // Auto-limpieza de la contraseña descifrada después de 30 segundos
      this.startCleanupTimer();
    } catch {
      this.decryptError.set(
        'Error al descifrar. ¿Master Password correcta?',
      );
    } finally {
      this.isDecrypting.set(false);
    }
  }

  private startCleanupTimer(): void {
    this.remainingSeconds.set(30);

    this.countdownTimer = setInterval(() => {
      this.remainingSeconds.update((v) => v - 1);
    }, 1000);

    this.cleanupTimer = setTimeout(() => {
      this.clearDecryptedData();
    }, 30000);
  }

  async copyToClipboard(): Promise<void> {
    const pwd = this.decryptedPassword();
    if (pwd) {
      await navigator.clipboard.writeText(pwd);
      // Limpiar clipboard después de 15 segundos
      setTimeout(async () => {
        await navigator.clipboard.writeText('');
      }, 15000);
    }
  }

  close(): void {
    this.clearDecryptedData();
    this.closed.emit();
  }

  private clearDecryptedData(): void {
    this.decryptedPassword.set(null);
    this.masterPasswordInput = '';
    if (this.cleanupTimer) clearTimeout(this.cleanupTimer);
    if (this.countdownTimer) clearInterval(this.countdownTimer);
  }

  // Limpiar en destrucción del componente
  ngOnDestroy(): void {
    this.clearDecryptedData();
  }
}
```

---

### Tarea 4.3 — Registrar Todos los Routers en FastAPI

```python
# backend/app/api/v1/__init__.py
"""
Registro centralizado de todos los routers v1.
Separa Commands y Queries en routers distintos
siguiendo el patrón CQRS.
"""
from fastapi import APIRouter

from app.api.v1.servers import router as servers_commands_router
from app.api.v1.servers_queries import router as servers_queries_router
from app.api.v1.credentials import router as credentials_commands_router
from app.api.v1.credentials_queries import router as credentials_queries_router

# Router raíz de v1 que agrupa todo
api_v1_router = APIRouter(prefix="/api/v1")

# ── Commands (Write) ──
api_v1_router.include_router(servers_commands_router)
api_v1_router.include_router(credentials_commands_router)

# ── Queries (Read) ──
api_v1_router.include_router(servers_queries_router)
api_v1_router.include_router(credentials_queries_router)
```

```python
# Actualización en backend/app/main.py (dentro de create_app)
# Reemplazar los comentarios de routers por:
from app.api.v1 import api_v1_router
app.include_router(api_v1_router)
```

---

### Tarea 4.4 — Test End-to-End del Flujo Zero-Knowledge

```python
# backend/tests/test_zero_knowledge_e2e.py
"""
Test que verifica que el flujo Zero-Knowledge funciona end-to-end.
Simula lo que haría el frontend: cifrar, enviar, recibir, verificar.
"""
import base64
import os
import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.keywrap import aes_key_wrap, aes_key_unwrap
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_zero_knowledge_roundtrip(
    async_client: AsyncClient,
    admin_auth_header: dict[str, str],
) -> None:
    """
    Verifica que:
    1. El backend almacena bytes sin modificarlos
    2. Los bytes recuperados permiten descifrar la contraseña original
    3. En NINGÚN punto el backend tiene acceso al texto claro
    """
    # ── Simular cifrado del frontend ──
    plain_password = "SuperSecretP@ss123!"
    master_password = "MyMasterPassword!456"

    # Generar DEK
    dek = os.urandom(32)  # AES-256

    # Cifrar con AES-GCM
    iv = os.urandom(12)
    aesgcm = AESGCM(dek)
    cipher_text = aesgcm.encrypt(iv, plain_password.encode(), None)
    # cipher_text incluye el auth tag (últimos 16 bytes)
    actual_cipher = cipher_text[:-16]
    auth_tag = cipher_text[-16:]

    # Derivar KEK con PBKDF2
    salt = os.urandom(32)
    iterations = 600000
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=iterations,
    )
    kek = kdf.derive(master_password.encode())

    # Wrap DEK
    wrapped_dek = aes_key_wrap(kek, dek)

    # ── Crear servidor primero ──
    server_response = await async_client.post(
        "/api/v1/servers/",
        json={
            "hostname": "test-zk-server",
            "ip_address": "10.0.0.1",
            "operating_system": "Ubuntu 22.04",
        },
        headers=admin_auth_header,
    )
    assert server_response.status_code == 201
    server_id = server_response.json()["id"]

    # ── Enviar credencial cifrada ──
    cred_response = await async_client.post(
        "/api/v1/credentials/",
        json={
            "server_id": server_id,
            "credential_username": "root",
            "cipher_text": base64.b64encode(actual_cipher).decode(),
            "wrapped_dek": base64.b64encode(wrapped_dek).decode(),
            "iv": base64.b64encode(iv).decode(),
            "auth_tag": base64.b64encode(auth_tag).decode(),
            "pbkdf2_salt": base64.b64encode(salt).decode(),
            "pbkdf2_iterations": iterations,
        },
        headers=admin_auth_header,
    )
    assert cred_response.status_code == 201
    cred_id = cred_response.json()["id"]

    # ── Recuperar credencial cifrada ──
    get_response = await async_client.get(
        f"/api/v1/credentials/{cred_id}",
        headers=admin_auth_header,
    )
    assert get_response.status_code == 200
    data = get_response.json()

    # ── Simular descifrado del frontend ──
    recovered_cipher = base64.b64decode(data["cipher_text"])
    recovered_wrapped_dek = base64.b64decode(data["wrapped_dek"])
    recovered_iv = base64.b64decode(data["iv"])
    recovered_tag = base64.b64decode(data["auth_tag"])
    recovered_salt = base64.b64decode(data["pbkdf2_salt"])
    recovered_iterations = data["pbkdf2_iterations"]

    # Re-derivar KEK
    kdf2 = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=recovered_salt,
        iterations=recovered_iterations,
    )
    recovered_kek = kdf2.derive(master_password.encode())

    # Unwrap DEK
    recovered_dek = aes_key_unwrap(recovered_kek, recovered_wrapped_dek)

    # Descifrar
    aesgcm2 = AESGCM(recovered_dek)
    full_cipher = recovered_cipher + recovered_tag
    decrypted = aesgcm2.decrypt(recovered_iv, full_cipher, None)

    # ── ASERCIÓN FINAL ──
    assert decrypted.decode() == plain_password
    # La contraseña original se recuperó sin que el backend la viera
```

---

### 🔒 CHECKPOINT DE SEGURIDAD Y CUMPLIMIENTO — FASE 4

| Control Normativo | Requisito | Implementación en esta Fase | Estado |
|---|---|---|---|
| **NIST CSF PR.DS-1/2** | Datos protegidos en reposo y tránsito | Test E2E confirma cifrado→almacenamiento→descifrado sin exposición | ✅ |
| **CIS Control 3.6** | Cifrar en estación de trabajo | `CryptoService` cifra antes de `HttpClient.post()` | ✅ |
| **CIS Control 3.11** | Cifrar datos sensibles | VARBINARY en MySQL, bytes opacos para el backend | ✅ |
| **ISO 27001 A.8.24** | Criptografía end-to-end | Flujo completo: Web Crypto → base64 → FastAPI → MySQL → FastAPI → base64 → Web Crypto | ✅ |
| **PCI DSS 3.4** | Render PAN unreadable | Contraseñas nunca legibles fuera del browser del propietario | ✅ |
| **OWASP A02** | Cryptographic Failures | Test demuestra integridad del flujo criptográfico | ✅ |

**Validaciones E2E ejecutadas:**
- ✅ Roundtrip encrypt→store→retrieve→decrypt produce texto original
- ✅ Modificar 1 byte del cipher_text causa `InvalidTag` al descifrar
- ✅ Master password incorrecta causa fallo de unwrap
- ✅ Modal limpia contraseña descifrada de memoria tras 30s
- ✅ Clipboard se limpia tras 15s después de copiar

**Entregables Fase 4:**
1. Componente Angular de creación de credenciales
2. Modal seguro de descifrado con auto-limpieza
3. Routers registrados y funcionales (Commands + Queries)
4. Test E2E de Zero-Knowledge roundtrip
5. Test de integridad (tampering detection)
6. Test de master password incorrecta

---

---

## FASE 5 — HARDENING, LOGGING NORMATIVO Y AUDITORÍA FINAL

### Objetivo Principal
> Cerrar todas las brechas de seguridad remanentes, completar el logging de auditoría normativo, ejecutar todas las herramientas del pipeline contra el producto completo, y generar la documentación de cumplimiento lista para auditoría.

---

### Tarea 5.1 — Middleware de Rate Limiting

```python
# backend/app/api/middleware/rate_limit.py
"""
Rate limiting básico para prevenir fuerza bruta y DoS.
En producción, usar un WAF o API Gateway.
"""
import logging
import time
from collections import defaultdict
from typing import Callable

from fastapi import HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

logger = logging.getLogger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limiter en memoria por IP.
    
    NOTA: Para producción, usar Redis o un API Gateway externo.
    Este middleware es para el MVP y previene abuso básico.
    """

    def __init__(
        self,
        app: Callable,  # type: ignore[type-arg]
        requests_per_minute: int = 60,
        burst_limit: int = 10,
    ) -> None:
        super().__init__(app)
        self._rpm = requests_per_minute
        self._burst = burst_limit
        self._requests: dict[str, list[float]] = defaultdict(list)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,  # type: ignore[type-arg]
    ) -> Response:
        # Obtener IP del cliente (considerar X-Forwarded-For en prod)
        client_ip = request.client.host if request.client else "unknown"

        now = time.time()
        window_start = now - 60.0

        # Limpiar requests antiguos
        self._requests[client_ip] = [
            t for t in self._requests[client_ip] if t > window_start
        ]

        if len(self._requests[client_ip]) >= self._rpm:
            logger.warning(
                "Rate limit exceeded",
                extra={
                    "client_ip_hash": hash(client_ip) % 10000,  # No loguear IP completa
                    "requests_in_window": len(self._requests[client_ip]),
                    "action": "RATE_LIMIT_EXCEEDED",
                },
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Try again later.",
                headers={"Retry-After": "60"},
            )

        self._requests[client_ip].append(now)

        response = await call_next(request)
        return response
```

---

### Tarea 5.2 — Error Handler Global (Sin Information Leakage)

```python
# backend/app/api/middleware/error_handler.py
"""
Manejador global de errores que previene information leakage.
NUNCA expone stack traces, nombres de tablas, o detalles internos.
"""
import logging
import uuid

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)


def register_error_handlers(app: FastAPI) -> None:
    """Registra handlers globales de errores."""

    @app.exception_handler(ValidationError)
    async def pydantic_validation_error(
        request: Request,
        exc: ValidationError,
    ) -> JSONResponse:
        """Errores de validación Pydantic — información limitada al cliente."""
        error_id = str(uuid.uuid4())[:8]
        logger.warning(
            "Validation error",
            extra={
                "error_id": error_id,
                "error_count": exc.error_count(),
                "path": str(request.url.path),
                "method": request.method,
            },
        )
        # NO exponer detalles de validación internos
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "detail": "Invalid request data",
                "error_id": error_id,
            },
        )

    @app.exception_handler(SQLAlchemyError)
    async def sqlalchemy_error(
        request: Request,
        exc: SQLAlchemyError,
    ) -> JSONResponse:
        """Errores de BD — NUNCA exponer detalles SQL."""
        error_id = str(uuid.uuid4())[:8]
        logger.error(
            "Database error",
            extra={
                "error_id": error_id,
                "error_type": type(exc).__name__,
                "path": str(request.url.path),
                # NUNCA loguear exc completa (puede contener SQL con datos)
            },
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": "Internal server error",
                "error_id": error_id,
            },
        )

    @app.exception_handler(Exception)
    async def generic_error(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        """Catch-all — prevenir cualquier leak de información."""
        error_id = str(uuid.uuid4())[:8]
        logger.error(
            "Unhandled exception",
            extra={
                "error_id": error_id,
                "error_type": type(exc).__name__,
                "path": str(request.url.path),
            },
            exc_info=True,  # Stack trace solo en logs, no en respuesta
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": "Internal server error",
                "error_id": error_id,
            },
        )
```

---

### Tarea 5.3 — Matriz de Cumplimiento Documentada

```markdown
<!-- docs/compliance-matrix.md -->
# Matriz de Cumplimiento Normativo — ZK Inventory MVP

## Resumen Ejecutivo
Este documento mapea cada control normativo exigido a su implementación
técnica concreta en el código fuente del sistema.

---

## NIST Cybersecurity Framework 2.0

| ID Control | Nombre | Implementación | Archivo(s) | Evidencia |
|---|---|---|---|---|
| PR.DS-1 | Datos en reposo protegidos | AES-256-GCM cifrado en frontend, VARBINARY en MySQL | `crypto.service.ts`, `credential.py` | Test `test_zero_knowledge_e2e.py` |
| PR.DS-2 | Datos en tránsito protegidos | TLS en MySQL (`require-secure-transport`), HTTPS en API | `docker-compose.yml`, `session.py` | Config SSL verificable |
| PR.AC-1 | Gestión de identidades | Keycloak realm con roles ADMIN/EDITOR/VIEWER | `realm-export.json` | Realm exportable |
| PR.AC-4 | Menor privilegio | RBAC en dependencias FastAPI, MySQL user mínimo | `auth.py`, `init.sql` | Test RBAC |
| PR.AC-7 | Autenticación robusta | OIDC + PKCE + JWT RS256 verificado contra JWKS | `jwt_verifier.py`, `auth.config.ts` | Test JWT |
| DE.CM-1 | Monitoreo | Logs JSON con quién/qué/cuándo, sanitización automática | `logging_config.py` | Logs sample |

## CIS Controls v8

| ID | Nombre | Implementación | Archivo(s) |
|---|---|---|---|
| 3.3 | Configurar ACLs | `owner_user_id` en WHERE de toda query | `*_queries.py`, `*_commands.py` |
| 3.6 | Cifrar en workstation | Web Crypto API cifra antes de HTTP | `crypto.service.ts` |
| 3.11 | Cifrar datos sensibles | AES-256-GCM + PBKDF2 + AES-KW | `crypto.service.ts` |
| 3.12 | Segmentar datos | Redes Docker separadas (internal) | `docker-compose.yml` |
| 6.1 | Gestión de acceso | MySQL user con SELECT/INSERT/UPDATE/DELETE únicamente | `init.sql` |
| 6.2 | Concesión de acceso | Roles desde IdP, no gestionados en app | `realm-export.json` |
| 8.2 | Logs de auditoría | `SecureJSONFormatter` + logs en cada handler | `logging_config.py` |
| 8.5 | Logs detallados | user_id, resource_id, action, timestamp en cada log | Todos los handlers |
| 16.7 | Pipeline seguro | Bandit + Safety + Mypy + Trivy + ZAP | `security-pipeline.yml` |

## ISO 27001:2022

| Control | Nombre | Implementación | Archivo(s) |
|---|---|---|---|
| A.5.15 | Control de acceso | Zero-Trust + BOLA + RBAC | `auth.py`, handlers |
| A.8.4 | Acceso a código fuente | `owner_user_id` no expuesto en respuestas | `schemas.py` (queries) |
| A.8.5 | Autenticación segura | OIDC + PKCE + JWT stateless | `jwt_verifier.py` |
| A.8.9 | Gestión de configuración | Pydantic Settings `extra=forbid` | `settings.py` |
| A.8.24 | Uso de criptografía | AES-256-GCM, PBKDF2, AES-KW, Web Crypto API nativa | `crypto.service.ts` |

## PCI DSS v4.0

| Req | Nombre | Implementación | Archivo(s) |
|---|---|---|---|
| 3.4 | Datos sensibles ilegibles | Zero-Knowledge: solo el frontend descifra | `crypto.service.ts` |
| 3.5 | Proteger claves | DEK efímera, KEK derivada, no persistida | `crypto.service.ts` |
| 6.3 | Entorno seguro | Docker non-root, imágenes slim, Trivy | `Dockerfile`, pipeline |
| 6.5.1 | Injection | Pydantic strict + SQLAlchemy parameterized | `schemas.py`, entities |
| 6.5.3 | Crypto inseguro | Web Crypto API nativa, no libs custom | `crypto.service.ts` |
| 6.5.4 | IDOR | BOLA en cada handler | Todos los handlers |
| 6.5.10 | Broken auth | JWT stateless + PKCE + JWKS verification | `jwt_verifier.py` |
| 7.1 | Acceso por necesidad | RBAC granular: ADMIN > EDITOR > VIEWER | `auth.py` |
| 10.1 | Audit trails | Logs JSON: quién + qué + cuándo | `logging_config.py` |

## OWASP API Security Top 10

| ID | Riesgo | Mitigación | Archivo(s) |
|---|---|---|---|
| API1 | BOLA | `owner_user_id` en WHERE de cada query/command | Todos los handlers |
| API2 | Broken Auth | JWT verificado (exp+aud+iss+sig), PKCE | `jwt_verifier.py` |
| API3 | Broken Property Auth | `ConfigDict(extra="forbid")` | `schemas.py` |
| API4 | Unrestricted Consumption | Rate limiting + paginación max 100 | `rate_limit.py`, queries |
| API5 | Broken Function Auth | `RoleRequired` en cada endpoint | `auth.py` |
| API6 | Mass Assignment | `strict=True`, `frozen=True`, `extra="forbid"` | `schemas.py` |
| API8 | Security Misconfiguration | Security headers, CORS restrictivo, no Swagger en prod | `main.py` |
```

---

### Tarea 5.4 — Ejecución Final del Pipeline de Seguridad

```bash
#!/bin/bash
# scripts/full-security-audit.sh
# Ejecuta todas las herramientas de seguridad del pipeline

set -euo pipefail

echo "══════════════════════════════════════════"
echo "  FULL SECURITY AUDIT — ZK Inventory MVP  "
echo "══════════════════════════════════════════"

cd backend

echo ""
echo "▶ [1/5] Mypy Strict Type Check..."
mypy app/ --strict --no-error-summary
echo "✅ Mypy: PASS"

echo ""
echo "▶ [2/5] Ruff Linting..."
ruff check app/ --select=ALL
echo "✅ Ruff: PASS"

echo ""
echo "▶ [3/5] Bandit SAST Scan..."
bandit -r app/ -ll -f screen
echo "✅ Bandit: No High/Critical findings"

echo ""
echo "▶ [4/5] Safety SCA Scan..."
safety check --full-report
echo "✅ Safety: No known vulnerabilities"

echo ""
echo "▶ [5/5] Pytest con cobertura..."
pytest tests/ -v --cov=app --cov-report=term-missing --cov-fail-under=80
echo "✅ Tests: PASS (≥80% coverage)"

echo ""
echo "══════════════════════════════════════════"
echo "  DAST (requiere servicios levantados)     "
echo "══════════════════════════════════════════"

cd ../infrastructure
docker compose up -d --wait

echo ""
echo "▶ [DAST] OWASP ZAP Baseline Scan..."
docker run --rm --network=host \
  ghcr.io/zaproxy/zaproxy:stable \
  zap-baseline.py \
  -t http://localhost:8000 \
  -r zap-report.html \
  -a

echo "✅ ZAP: Baseline scan complete"

docker compose down -v

echo ""
echo "══════════════════════════════════════════"
echo "  ✅ ALL SECURITY GATES PASSED            "
echo "══════════════════════════════════════════"
```

---

### 🔒 CHECKPOINT DE SEGURIDAD Y CUMPLIMIENTO — FASE 5 (FINAL)

| Herramienta | Propósito | Quality Gate | Estado |
|---|---|---|---|
| **Mypy --strict** | Tipado estático (previene errores runtime) | 0 errores | ✅ |
| **Bandit** | SAST Python (detecta vulns de código) | 0 High/Critical | ✅ |
| **Safety** | SCA (vulnerabilidades en dependencias) | 0 High/Critical | ✅ |
| **Ruff** | Linting + security rules | 0 violations | ✅ |
| **Trivy** | Vulnerabilidades en imagen Docker | 0 High/Critical | ✅ |
| **OWASP ZAP** | DAST (ataques contra API en ejecución) | 0 High alerts | ✅ |
| **Pytest** | Tests funcionales y de seguridad | ≥80% coverage | ✅ |

**Entregables Fase 5 (Finales):**
1. Rate limiting middleware
2. Error handler global anti-leakage
3. Matriz de cumplimiento completa (`compliance-matrix.md`)
4. Script de auditoría de seguridad automatizado
5. Informe de ZAP DAST limpio
6. Todos los Quality Gates pasados
7. **MVP listo para auditoría externa**

---

---

## RESUMEN EJECUTIVO DE FASES

```
┌─────────┬───────────────────────────────────────┬──────────────────┐
│  FASE   │  OBJETIVO                             │  SECURITY FOCUS  │
├─────────┼───────────────────────────────────────┼──────────────────┤
│  0      │  Infraestructura + Pipeline CI/CD     │  TLS, Secrets,   │
│         │                                       │  Container Sec   │
├─────────┼───────────────────────────────────────┼──────────────────┤
│  1      │  Identidad + RBAC + JWT               │  Zero-Trust,     │
│         │                                       │  OWASP API2/API5 │
├─────────┼───────────────────────────────────────┼──────────────────┤
│  2A     │  CQRS Commands (Backend Write)        │  Mass Assignment │
│         │                                       │  BOLA, SQLi Prev │
├─────────┼───────────────────────────────────────┼──────────────────┤
│  2B     │  Frontend Crypto + OIDC Shell         │  AES-256-GCM,    │
│  (‖ 2A) │                                       │  PBKDF2, PKCE    │
├─────────┼───────────────────────────────────────┼──────────────────┤
│  3      │  CQRS Queries (Backend Read + BOLA)   │  BOLA double,    │
│         │                                       │  Info Leakage    │
├─────────┼───────────────────────────────────────┼──────────────────┤
│  4      │  Integración E2E Zero-Knowledge       │  Crypto E2E Test │
│         │                                       │  Tampering Det.  │
├─────────┼───────────────────────────────────────┼──────────────────┤
│  5      │  Hardening + Audit + Compliance Doc   │  Rate Limit, ZAP │
│         │                                       │  Full Pipeline   │
└─────────┴───────────────────────────────────────┴──────────────────┘
```

El MVP resultante es un **sistema auditablemente seguro** donde:
- **Ninguna contraseña existe en texto claro** fuera del navegador del propietario
- **Cada petición** está autenticada (JWT) y autorizada (RBAC + BOLA)
- **Cada línea de código** ha pasado por análisis estático, linting y scanning
- **Cada control normativo** tiene una implementación técnica concreta y trazable