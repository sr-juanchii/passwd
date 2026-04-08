# Matriz de Cumplimiento Normativo — Fase 0

## NIST CSF 2.0

| ID | Control | Implementación | Archivo(s) |
|---|---|---|---|
| PR.DS-1 | Datos en reposo protegidos | MySQL con esquema preparado para `VARBINARY` y transporte cifrado | `infrastructure/mysql/init.sql`, `infrastructure/docker-compose.yml` |
| PR.DS-2 | Datos en tránsito protegidos | `require-secure-transport=ON`, `REQUIRE SSL` para usuarios de BD | `infrastructure/docker-compose.yml`, `infrastructure/mysql/bootstrap.sh` |
| DE.CM-1 | Monitoreo continuo | Logging estructurado y healthcheck de backend | `backend/app/shared/logging_config.py`, `backend/app/main.py` |

## CIS Controls v8

| ID | Control | Implementación | Archivo(s) |
|---|---|---|---|
| 3.12 | Segmentar procesamiento de datos sensibles | Red interna `backend-net` separada de `frontend-net` | `infrastructure/docker-compose.yml` |
| 6.1 | Gestionar accesos con privilegio mínimo | Usuarios MySQL dedicados por función y permisos acotados | `infrastructure/mysql/bootstrap.sh` |
| 16.7 | Pipeline de desarrollo seguro | Mypy, Ruff, Bandit, Safety, Trivy y ZAP | `.github/workflows/security-pipeline.yml` |

## ISO 27001

| Control | Implementación | Archivo(s) |
|---|---|---|
| A.8.9 | Gestión de configuración | `Settings` estricto y secretos por archivo | `backend/app/config/settings.py` |
| A.8.24 | Uso de criptografía | Base TLS para MySQL y scaffold preparado para cifrado extremo a extremo | `infrastructure/docker-compose.yml` |

## PCI DSS

| Requisito | Implementación | Archivo(s) |
|---|---|---|
| 6.3 | Entorno de desarrollo seguro | Imágenes slim, contenedores no root y escaneo de imagen | `backend/Dockerfile`, `frontend/Dockerfile`, `.github/workflows/security-pipeline.yml` |

## OWASP Top 10

| Riesgo | Mitigación | Archivo(s) |
|---|---|---|
| API1 | Broken Object Level Authorization preparado por diseño | `infrastructure/mysql/init.sql` |
| API8 | Security Misconfiguration | Security headers, CORS restrictivo, puertos en localhost | `backend/app/main.py`, `infrastructure/docker-compose.yml` |
