# 🔐 Gestor de Contraseñas de Servidores

Sistema interno para custodiar las credenciales de la infraestructura de servidores con un
**inventario relacional completo**, **inicio de sesión seguro con MFA obligatorio** y
controles alineados con **CIS Controls v8.1** e **ISO/IEC 27003**.

## Inventario segmentado y relacional

El inventario refleja la realidad física y lógica de la infraestructura:

```
🖥️ Servidor físico (función única)            p. ej. el servidor de la base de datos de nómina
🖥️ Servidor físico (host de virtualización)   sin función única establecida
   └── ⚙️ Hipervisor (Proxmox VE, ESXi, Hyper-V…)
         └── 🗔 Máquina virtual                 cada una con su sistema y función descritos
```

Cada nivel —servidor físico, hipervisor o máquina virtual— almacena sus **credenciales de
acceso**: usuario, contraseña (cifrada en reposo), servicio/protocolo (SSH, RDP, iLO/IPMI,
panel web…), puerto y una **descripción de a qué sistema da acceso**. Las relaciones se
garantizan con claves foráneas y restricciones CHECK; el detalle está en
[`docs/modelo-datos.md`](docs/modelo-datos.md).

## Seguridad implementada

| Ámbito | Control |
|---|---|
| Autenticación | Contraseña (hash **Argon2id**) + **MFA TOTP obligatorio** (RFC 6238) con QR de enrolamiento generado localmente; anti-replay del último código usado; **códigos de recuperación de un solo uso** (8 por usuario, solo hashes en BD) por si se pierde el dispositivo |
| Sesiones | Gestionadas en servidor (revocables), token rotado al elevar privilegios, cookie `HttpOnly` + `Secure` + `SameSite=Strict`, expiración por inactividad (15 min) y absoluta (8 h) |
| Cuentas | Bloqueo tras 5 intentos fallidos, límite de tasa por IP, contraseñas temporales de un solo uso con cambio forzado, política de contraseñas (mín. 12, lista de comunes prohibidas), desactivación con revocación inmediata |
| Autorización | RBAC con cuatro roles (**admin**, **operador**, **auditor**, **analista**) más **control de acceso por objeto**: el analista solo ve y usa los activos que un administrador le concede (con nivel y caducidad) — matriz en [`app/rbac.py`](app/rbac.py), concesiones en [`app/access.py`](app/access.py) |
| Datos | Contraseñas de activos y semillas TOTP **cifradas con Fernet (AES)** antes de tocar la base de datos; claves criptográficas fuera del repositorio; **generador de contraseñas robustas** (CSPRNG, 20 caracteres) en el formulario |
| Exposición mínima | Botón **«Copiar» sin visualización**: la contraseña va directo al portapapeles sin mostrarse en pantalla y se limpia a los 30 s; «Revelar» se re-oculta solo; **límite anti-exfiltración** por usuario (20 accesos/5 min configurables) compartido entre ambas vías |
| Rotación | **Alerta visual** en el panel y en cada activo cuando una credencial supera los 90 días (configurable) sin rotarse; el contador se reinicia al cambiar la contraseña |
| Respaldo | **Respaldo cifrado portátil** por CLI (`respaldo`/`restaurar`): todo el sistema en un archivo cifrado con frase (scrypt + Fernet), restaurable incluso en otra instancia con claves distintas |
| Auditoría | Bitácora completa: logins (éxito/fallo), MFA, bloqueos, gestión de usuarios, CRUD del inventario, accesos denegados y **cada acceso a una contraseña** (revelado y copiado por separado, incluso los intentos bloqueados por exceso), con usuario, IP y agente; retención configurable (mínimo 90 días); **exportación a CSV** (filtrada, auditada, con mitigación de inyección de fórmulas) |
| Visibilidad | **Dashboard de métricas** de seguridad (rotación pendiente, logins fallidos 24 h/7 d, cuentas sin MFA, top de accesos a credenciales, concesiones por caducar) y **búsqueda global** del inventario filtrada por el control de acceso por objeto |
| Inventario ampliado | Campos de **hardware** (RAM/CPU/almacenamiento/serie/garantía/proveedor) y **estado** (activo/mantenimiento/retirado); **etiquetas** con búsqueda; **notas seguras cifradas** por activo (revelado auditado); **historial de contraseñas** anteriores; **importación masiva CSV** (en memoria, cifrando al guardar) |
| Operación proactiva | **Alertas por correo** opt-in (cuenta bloqueada, posible exfiltración, alta de usuario, fallo de respaldo; sin secretos); **respaldos programados** con retención y aviso de fallo; **limitador de tasa** opcional en BD para despliegues multi-instancia |
| Integración | **API REST de solo lectura** con tokens Bearer para SIEM/automatización (`/api/v1/auditoria`, `/api/v1/inventario`; nunca expone secretos); tokens gestionados y revocables |
| Interfaz | Modo claro/oscuro persistente, compatible con la CSP estricta (sin código embebido) |
| Aplicación | CSP estricta sin código embebido, anti-CSRF en todos los formularios, cabeceras endurecidas (HSTS, X-Frame-Options, nosniff, COOP/CORP), límite de tamaño de petición (OWASP API4), mensajes genéricos anti enumeración, API docs deshabilitadas, **pip-audit** en CI contra dependencias vulnerables |

Cumplimiento documentado con evidencia por control:
- [`docs/cumplimiento-cis-v8.1.md`](docs/cumplimiento-cis-v8.1.md) — matriz CIS Controls v8.1
- [`docs/cumplimiento-iso-27003.md`](docs/cumplimiento-iso-27003.md) — alineación ISO/IEC 27003 y Anexo A
- [`docs/cumplimiento-owasp.md`](docs/cumplimiento-owasp.md) — **OWASP Top 10 (2021) y API Security Top 10 (2023)**
- [`docs/verificacion-cumplimiento.md`](docs/verificacion-cumplimiento.md) — **informe de verificación** (pruebas, SAST y evidencia dinámica)
- [`docs/control-acceso.md`](docs/control-acceso.md) — control de acceso por objeto (roles y concesiones)

Para implantar el sistema (entorno de pruebas, plan de aceptación UAT y paso a producción):
- [`docs/guia-implementacion.md`](docs/guia-implementacion.md) — **guía de implementación completa**
- [`docs/guia-nginx-tls.md`](docs/guia-nginx-tls.md) — **HTTPS con nginx y rotación de certificados**
- [`docs/hoja-de-ruta.md`](docs/hoja-de-ruta.md) — **hoja de ruta de mejoras** (viabilidad y fases)

## Interfaz alternativa: Next.js + shadcn/ui

Además de la interfaz Jinja (servida por la propia aplicación), el repositorio
incluye un **frontend moderno en [`frontend/`](frontend/)** construido con
**Next.js (App Router, React 19)** y **shadcn/ui**, con **paridad funcional
completa**: autenticación por etapas con MFA, inventario relacional, gestión de
credenciales (generador, copiar/revelar con auto-ocultado, historial), notas
seguras, control de acceso por objeto, usuarios, tokens, auditoría con export
CSV, métricas, importación CSV, búsqueda global y tema claro/oscuro.

Consume una **API JSON** (`/api/web`, en [`app/api_web/`](app/api_web/)) que
reutiliza el mismo modelo de seguridad del backend: sesión por cookie HttpOnly,
anti-CSRF (cabecera `X-CSRF-Token`), RBAC y control de acceso por objeto. Ambas
interfaces conviven. Detalles en [`frontend/README.md`](frontend/README.md).

### Ejecutar el frontend con Docker (recomendado)

Levanta backend + frontend Next.js + nginx (HTTPS) enrutando `/api/*` al backend
y el resto al frontend:

```bash
cp .env.example .env        # editar PASSWD_ADMIN_* y PASSWD_DOMAIN
# Certificado en infrastructure/nginx/certs/{fullchain,privkey}.pem
# (pruebas: sh infrastructure/nginx/generar-cert-autofirmado.sh localhost)
docker compose -f docker-compose.yml -f docker-compose.frontend.yml up -d --build
# Disponible en https://<PASSWD_DOMAIN>
```

#### En Windows (PowerShell)

```powershell
Copy-Item .env.example .env     # editar PASSWD_ADMIN_* y PASSWD_DOMAIN
# Certificado autofirmado de pruebas (usa OpenSSL local o, si no está, Docker):
powershell -ExecutionPolicy Bypass -File .\infrastructure\nginx\generar-cert-autofirmado.ps1 localhost
docker compose -f docker-compose.yml -f docker-compose.frontend.yml up -d --build
# Disponible en https://localhost (acepte la advertencia del certificado autofirmado)
```

Si prefiere no usar el script, el certificado de pruebas se genera con un único
contenedor (no requiere instalar OpenSSL):

```powershell
docker run --rm -v "${PWD}\infrastructure\nginx\certs:/certs" alpine/openssl `
  req -x509 -nodes -newkey rsa:2048 -days 365 `
  -keyout /certs/privkey.pem -out /certs/fullchain.pem `
  -subj "/CN=localhost" -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
```

> En producción **no** use certificados autofirmados: coloque los de su CA o
> Let's Encrypt en `infrastructure/nginx/certs/`. Guía completa y rotación en
> [`docs/guia-nginx-tls.md`](docs/guia-nginx-tls.md).

### Ejecutar el frontend en local (desarrollo)

Sin Docker ni TLS (más simple para desarrollar); el navegador habla con Next y
este proxya `/api` al backend, así que **no hace falta certificado**:

```bash
# Linux/macOS
PASSWD_COOKIE_SECURE=false uvicorn app.main:app --port 8000
cd frontend && pnpm install && pnpm dev     # http://localhost:3000
```

```powershell
# Windows (PowerShell)
$env:PASSWD_COOKIE_SECURE = "false"; uvicorn app.main:app --port 8000
# en otra terminal:
cd frontend; pnpm install; pnpm dev          # http://localhost:3000
```

### Verificación funcional

`python scripts/verificar_api_web.py` ejercita end-to-end **todas** las
funciones de la API JSON (auth+MFA, inventario, credenciales, rotación e
historial, notas, control de acceso por objeto, usuarios, tokens, auditoría
con export CSV, métricas, búsqueda, importación CSV y cascadas).

## Roles

| Permiso | admin | operador | auditor | analista |
|---|:-:|:-:|:-:|:-:|
| Ver inventario y credenciales (sin contraseña) | ✔ | ✔ | ✔ | solo concedidos |
| Gestionar inventario y credenciales | ✔ | ✔ | ✘ | ✘ |
| Revelar/copiar contraseñas (auditado) | ✔ | ✔ | ✘ | solo concedidas |
| Gestionar usuarios | ✔ | ✘ | ✘ | ✘ |
| Conceder/revocar accesos por activo | ✔ | ✘ | ✘ | ✘ |
| Ver bitácora de auditoría | ✔ | ✘ | ✔ | ✘ |

El rol **analista** es *default-deny*: no ve nada hasta que un administrador le concede acceso a
activos concretos. Ver [`docs/control-acceso.md`](docs/control-acceso.md).

## Puesta en marcha

### Opción A: Docker con HTTPS/nginx (recomendada para producción)

```bash
cp .env.example .env        # editar: PASSWD_ADMIN_USERNAME / EMAIL / PASSWORD y PASSWD_DOMAIN
# Certificado: colocar infrastructure/nginx/certs/{fullchain,privkey}.pem
# (pruebas: sh infrastructure/nginx/generar-cert-autofirmado.sh localhost)
docker compose -f docker-compose.yml -f docker-compose.nginx.yml up -d --build
# Disponible en https://<PASSWD_DOMAIN> (nginx termina TLS; la app no se expone)
```

Detalles, Let's Encrypt y **rotación de certificados**: [`docs/guia-nginx-tls.md`](docs/guia-nginx-tls.md).

### Opción A′: Docker sin proxy (solo para pruebas internas)

```bash
cp .env.example .env
docker compose up -d --build
# La app queda en http://127.0.0.1:8000 — publicar SIEMPRE detrás de un proxy TLS
```

### Opción B: local (Python 3.11+)

```bash
pip install -r requirements.txt
export PASSWD_ADMIN_USERNAME=admin
export PASSWD_ADMIN_EMAIL=admin@su-organizacion.tld
export PASSWD_ADMIN_PASSWORD='UnaClaveInicialRobusta!'
export PASSWD_COOKIE_SECURE=false   # solo para probar sin HTTPS; nunca en producción
uvicorn app.main:app
```

### Primer acceso

1. Entre con el administrador inicial definido en las variables `PASSWD_ADMIN_*`.
2. El sistema **fuerza el cambio de contraseña** (la inicial es de un solo uso).
3. El sistema **exige enrolar MFA**: escanee el QR con su aplicación autenticadora
   (Aegis, FreeOTP, Google/Microsoft Authenticator…) y confirme el código.
4. Cree el resto de usuarios desde **Usuarios**: recibirán una contraseña temporal y
   pasarán por el mismo circuito (cambio forzado + MFA) en su primer ingreso.

También puede crearse un administrador por CLI: `python -m app.cli crear-admin --username admin --email admin@dominio`.

### Respaldo y restauración

```bash
python -m app.cli respaldo --salida copia.passwd          # pide una frase de cifrado (mín. 12)
python -m app.cli restaurar --entrada copia.passwd --sobrescribir
```

El archivo incluye usuarios, inventario completo, credenciales y bitácora, cifrado con una
clave derivada de la frase (scrypt); es portable entre instancias aunque tengan claves de
cifrado distintas. Sin la frase, el respaldo es irrecuperable: custódiela aparte del archivo.

### Base de datos

Por defecto **SQLite** en el directorio de datos (cero configuración). Para **MySQL 8**,
defina `MYSQL_PASSWORD` en `.env` (línea sin comentar) y arranque con el archivo adicional:
`docker compose -f docker-compose.yml -f docker-compose.mysql.yml up -d --build`.
Sin Docker: `PASSWD_DATABASE_URL=mysql+pymysql://usuario:clave@host:3306/passwd`.

### Variables de entorno

Todas opcionales salvo el administrador inicial; ver [`.env.example`](.env.example) para la
lista completa con sus valores por defecto (sesiones, bloqueo, retención de auditoría, claves).

## Pruebas y calidad

```bash
pip install -r requirements-dev.txt
pytest          # 103 pruebas: MFA, recuperación, RBAC, acceso por objeto, CSRF, cifrado, respaldo, export CSV, métricas, búsqueda, hardware/tags, notas, historial, importación CSV, migraciones, email, rate limit BD, API de tokens, modo oscuro, anti-exfiltración, cascadas, auditoría
ruff check app tests
bandit -r app --severity-level medium
pip-audit -r requirements.txt
```

El pipeline de CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) ejecuta lo mismo
en cada push y pull request.

## Estructura del proyecto

```
app/
├── main.py            # aplicación, cabeceras de seguridad, arranque
├── config.py          # configuración por entorno (prefijo PASSWD_)
├── models.py          # modelo relacional (usuarios, inventario, credenciales, auditoría)
├── database.py        # motor SQLAlchemy (SQLite/MySQL)
├── rbac.py            # matriz de roles y permisos (por tipo de operación)
├── access.py          # control de acceso por objeto (concesiones a analistas)
├── audit.py           # bitácora de auditoría y retención
├── deps.py            # dependencias: sesión activa, permisos, CSRF, render
├── security/          # Argon2id, Fernet, TOTP+QR, sesiones, límite de tasa
├── routes/            # auth, inventario, búsqueda, credenciales, accesos, usuarios, auditoría (+CSV), métricas
├── templates/         # interfaz en español (Jinja2)
└── static/            # CSS y JS compatibles con la CSP estricta
tests/                 # suite completa de pruebas de seguridad y funcionalidad
docs/                  # guía de implementación, cumplimiento CIS v8.1 / ISO 27000,
                       # informe de verificación y modelo de datos
```

## Adiciones aprobadas e incorporadas

Tras consulta, se aprobaron e implementaron: **generador de contraseñas**, **alertas de
rotación**, **respaldo cifrado** y **códigos de recuperación MFA**.

## Posibles adiciones futuras (pendientes de aprobación)

Por decisión del proyecto, **ninguna funcionalidad extra se incorpora sin consultarla
antes**. Candidatas restantes: integración con un directorio corporativo (LDAP/OIDC) y
campos adicionales de hardware (RAM/CPU/almacenamiento).
