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
| Autorización | RBAC con tres roles: **admin**, **operador** y **auditor** (solo lectura, sin acceso a contraseñas) — matriz en [`app/rbac.py`](app/rbac.py) |
| Datos | Contraseñas de activos y semillas TOTP **cifradas con Fernet (AES)** antes de tocar la base de datos; claves criptográficas fuera del repositorio; **generador de contraseñas robustas** (CSPRNG, 20 caracteres) en el formulario |
| Rotación | **Alerta visual** en el panel y en cada activo cuando una credencial supera los 90 días (configurable) sin rotarse; el contador se reinicia al cambiar la contraseña |
| Respaldo | **Respaldo cifrado portátil** por CLI (`respaldo`/`restaurar`): todo el sistema en un archivo cifrado con frase (scrypt + Fernet), restaurable incluso en otra instancia con claves distintas |
| Auditoría | Bitácora completa: logins (éxito/fallo), MFA, bloqueos, gestión de usuarios, CRUD del inventario, accesos denegados y **cada revelado de contraseña**, con usuario, IP y agente; retención configurable (mínimo 90 días) |
| Aplicación | CSP estricta sin código embebido, anti-CSRF en todos los formularios, cabeceras endurecidas (HSTS, X-Frame-Options, nosniff), mensajes genéricos anti enumeración de usuarios, API docs deshabilitadas |

Cumplimiento documentado con evidencia por control:
- [`docs/cumplimiento-cis-v8.1.md`](docs/cumplimiento-cis-v8.1.md) — matriz CIS Controls v8.1
- [`docs/cumplimiento-iso-27003.md`](docs/cumplimiento-iso-27003.md) — alineación ISO/IEC 27003 y Anexo A
- [`docs/verificacion-cumplimiento.md`](docs/verificacion-cumplimiento.md) — **informe de verificación** (pruebas, SAST y evidencia dinámica)

Para implantar el sistema (entorno de pruebas, plan de aceptación UAT y paso a producción):
- [`docs/guia-implementacion.md`](docs/guia-implementacion.md) — **guía de implementación completa**

## Roles

| Permiso | admin | operador | auditor |
|---|:-:|:-:|:-:|
| Ver inventario y credenciales (sin contraseña) | ✔ | ✔ | ✔ |
| Gestionar inventario y credenciales | ✔ | ✔ | ✘ |
| Revelar contraseñas (auditado) | ✔ | ✔ | ✘ |
| Gestionar usuarios | ✔ | ✘ | ✘ |
| Ver bitácora de auditoría | ✔ | ✘ | ✔ |

## Puesta en marcha

### Opción A: Docker (recomendada)

```bash
cp .env.example .env        # editar: PASSWD_ADMIN_USERNAME / EMAIL / PASSWORD
docker compose up -d --build
# La aplicación queda en http://127.0.0.1:8000 — publicar SIEMPRE detrás de un proxy TLS
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
pytest          # 45 pruebas: flujo MFA, códigos de recuperación, RBAC, CSRF, cifrado, respaldo, expiración de sesión, cascadas, auditoría
ruff check app tests
bandit -r app --severity-level medium
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
├── rbac.py            # matriz de roles y permisos
├── audit.py           # bitácora de auditoría y retención
├── deps.py            # dependencias: sesión activa, permisos, CSRF, render
├── security/          # Argon2id, Fernet, TOTP+QR, sesiones, límite de tasa
├── routes/            # auth (login/MFA), inventario, credenciales, usuarios, auditoría
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
