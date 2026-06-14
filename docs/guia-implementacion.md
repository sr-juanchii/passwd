# Guía de implementación

**Sistema:** Gestor de Contraseñas de Servidores
**Audiencia:** personal de TI responsable de la instalación, la prueba de aceptación y la operación.
**Alcance:** despliegue en **entorno de pruebas**, plan de pruebas de aceptación y, si la prueba
es aprobada, **paso a producción** con endurecimiento, respaldos y operación continua.

---

## 1. Arquitectura y componentes

```
Usuarios ──HTTPS──> Proxy TLS (nginx/Caddy/Traefik)   ← obligatorio en producción
                        │ HTTP solo en loopback/red interna
                        ▼
                Aplicación (uvicorn :8000)
                  ├── SQLite (por defecto)  o  MySQL 8 (opcional)
                  ├── Directorio de datos: BD + claves (.secret_key / .encryption_key)
                  └── Bitácora de auditoría (en la propia BD)
```

| Componente | Función |
|---|---|
| Aplicación (FastAPI/uvicorn) | Interfaz web, autenticación con MFA, RBAC, inventario, auditoría |
| Directorio de datos (`PASSWD_DATA_DIR`) | Base de datos SQLite y claves generadas (permisos 0600) |
| Proxy TLS | Terminación HTTPS; **sin él, las cookies `Secure` no funcionan** |
| CLI (`python -m app.cli`) | Alta de administrador, respaldo y restauración cifrados |

## 2. Requisitos previos

| Recurso | Mínimo recomendado |
|---|---|
| CPU / RAM | 1 vCPU / 1 GB (la aplicación es ligera; Argon2 usa ~64 MB por verificación) |
| Disco | 2 GB (BD + respaldos locales) |
| SO anfitrión | Linux con Docker Engine 24+ y Docker Compose v2, **o** Python 3.11+ |
| Red | Puerto 443 expuesto solo por el proxy TLS; el 8000 nunca debe publicarse hacia fuera |
| Otros | Aplicación autenticadora TOTP en los móviles del personal (Aegis, FreeOTP, Google/Microsoft Authenticator) y reloj del servidor sincronizado por **NTP** (el TOTP depende de la hora) |

---

## 3. FASE 1 — Entorno de pruebas

> Objetivo: validar funcionalidad y controles de seguridad con datos de prueba,
> **sin credenciales reales**, antes de autorizar producción.

### 3.1 Instalación

**Opción A — Docker (recomendada):**

```bash
git clone <repositorio> passwd && cd passwd
cp .env.example .env
# Editar .env: PASSWD_ADMIN_USERNAME, PASSWD_ADMIN_EMAIL, PASSWD_ADMIN_PASSWORD
# Solo para PRUEBAS sin HTTPS, añadir: PASSWD_COOKIE_SECURE=false
docker compose up -d --build
curl -s http://127.0.0.1:8000/healthz    # → {"estado":"ok",...}
```

**Opción B — Python local:**

```bash
pip install -r requirements.txt
export PASSWD_ADMIN_USERNAME=admin PASSWD_ADMIN_EMAIL=admin@org.tld
export PASSWD_ADMIN_PASSWORD='ClaveInicialRobusta!2026'
export PASSWD_COOKIE_SECURE=false      # solo pruebas sin HTTPS
uvicorn app.main:app --port 8000
```

### 3.2 Verificación técnica previa a la prueba de usuario

Ejecutar la suite del proyecto en la misma máquina (o en CI) y conservar la salida como evidencia:

```bash
pip install -r requirements-dev.txt
pytest                                   # esperado: 43 passed
ruff check app tests                     # esperado: All checks passed!
bandit -r app --severity-level medium    # esperado: sin hallazgos
```

### 3.3 Datos de prueba sugeridos

Cargar este conjunto mínimo, que ejercita toda la jerarquía:

1. Servidor físico **función única**: `srv-bd-nomina` (descripción: "BD del sistema de nómina") + 1 credencial SSH.
2. Servidor físico **host de virtualización**: `srv-virtual-01` + 1 credencial iLO/IPMI.
3. Hipervisor `pve-nodo-01` (Proxmox VE) dentro de `srv-virtual-01` + 1 credencial de consola.
4. Dos VMs dentro del hipervisor: `vm-correo` y `vm-intranet`, cada una con descripción de su sistema y 1 credencial.
5. Usuarios: 1 operador y 1 auditor (creados desde **Usuarios**), además del administrador.

### 3.4 Plan de pruebas de aceptación (UAT)

Registrar por cada caso: ejecutor, fecha, resultado (✔/✘) y observaciones.

| # | Caso | Pasos | Resultado esperado |
|---|---|---|---|
| 1 | Primer acceso del admin | Entrar con la clave de `.env` | Obliga a cambiar la contraseña |
| 2 | Política de contraseñas | Intentar clave de 8 caracteres y luego una con el nombre de usuario | Ambas rechazadas con motivo claro |
| 3 | Enrolamiento MFA | Escanear QR e ingresar código | MFA activado; muestra **8 códigos de recuperación** una sola vez |
| 4 | MFA en cada acceso | Cerrar sesión y volver a entrar | Pide código TOTP; sin él no se accede a ninguna página |
| 5 | Código MFA erróneo/reusado | Ingresar 000000; luego un código ya usado | Rechazados (401); el intento queda en auditoría |
| 6 | Código de recuperación | Entrar usando uno de los 8 códigos | Acceso concedido; aviso de cuántos quedan; el mismo código ya no sirve |
| 7 | Bloqueo de cuenta | 5 contraseñas erróneas seguidas | Cuenta bloqueada 15 min, incluso con la clave correcta; evento `cuenta_bloqueada` |
| 8 | Jerarquía del inventario | Crear los datos de 3.3 | El panel muestra el árbol físico → hipervisor → VM |
| 9 | Regla de función única | Intentar crear un hipervisor bajo `srv-bd-nomina` | Rechazado (400): solo hosts de virtualización |
| 10 | Credenciales por nivel | Crear credenciales en físico, hipervisor y VM | Aceptadas; contraseña nunca visible en listados |
| 11 | Generador | Botón 🎲 Generar en el formulario | Contraseña aleatoria de 20 caracteres visible para copiar |
| 12 | Revelar auditado | Pulsar «Revelar» en una credencial | Muestra la clave 30 s; queda evento `credencial_revelada` con usuario e IP en /auditoria |
| 13 | Rol auditor | Entrar como auditor | Ve inventario y auditoría; sin botones de gestión; «Revelar» no disponible; POST manual → 403 |
| 14 | Rol operador | Entrar como operador | Gestiona inventario/credenciales; /usuarios y /auditoria → 403 |
| 15 | Desactivar usuario | Admin desactiva al operador con sesión abierta | La sesión del operador muere al instante; no puede volver a entrar |
| 16 | Expiración por inactividad | Dejar sesión 15+ min sin uso | Redirige a /login al siguiente clic |
| 17 | Alerta de rotación | (Técnico) retroceder `password_rotada_en` 120 días en BD de prueba | Insignia «días sin rotar» y contador en el panel; desaparece al rotar la clave |
| 18 | Respaldo y restauración | `python -m app.cli respaldo` → borrar BD de prueba → `restaurar` | Todo recuperado; frase incorrecta → error sin revelar datos |
| 19 | Eliminación en cascada | Eliminar `srv-virtual-01` | Pide confirmación; desaparecen su hipervisor, VMs y credenciales |
| 20 | Auditoría | Revisar /auditoria con filtros | Todos los eventos anteriores presentes con usuario, IP y resultado |

### 3.5 Criterios de aprobación de la fase de pruebas

- [ ] 20/20 casos UAT con resultado esperado.
- [ ] `pytest` 43/43, `ruff` y `bandit` sin hallazgos (≥ media).
- [ ] Al menos un respaldo restaurado con éxito (caso 18).
- [ ] Personal clave enrolado en MFA sin incidencias y códigos de recuperación custodiados.
- [ ] Visto bueno del responsable de seguridad sobre el informe `docs/verificacion-cumplimiento.md`.

**Si algún criterio falla:** registrar el hallazgo, corregir y repetir la prueba afectada antes de autorizar producción.

---

## 4. FASE 2 — Producción (tras aprobar la prueba)

### 4.1 Lista de verificación previa

- [ ] Servidor dedicado/VM con SO actualizado, firewall activo y acceso administrativo restringido.
- [ ] **NTP activo** y zona horaria correcta.
- [ ] Certificado TLS disponible (interno o Let's Encrypt).
- [ ] `.env` de producción preparado **sin** `PASSWD_COOKIE_SECURE=false`.
- [ ] Claves `PASSWD_SECRET_KEY` y `PASSWD_ENCRYPTION_KEY` generadas y custodiadas (ver 4.4).
- [ ] Frase de respaldo definida y custodiada **fuera del servidor** (sobre sellado / gestor corporativo).
- [ ] Destino de respaldos externo al servidor (NAS, almacenamiento remoto).

### 4.2 Endurecimiento del anfitrión (resumen)

- Firewall: permitir solo 443/tcp (y 80/tcp para la redirección y el desafío ACME, más el puerto de administración del propio anfitrión); **nunca exponer el 8000**.
- Docker: con el override de nginx la app **deja de publicar** el 8000 (`ports: !reset []`) y solo se llega por nginx.
- Restringir el acceso al directorio de datos al usuario del servicio; los archivos de claves ya nacen 0600.
- Mantener el anfitrión bajo el régimen de parches de la institución (CIS 7 — organizativo).

### 4.3 Proxy TLS con nginx (obligatorio)

El proyecto incluye una solución de nginx lista para usar (TLS endurecido, IP real del
cliente sin posibilidad de spoofing, HSTS y rotación de certificados sencilla):

```bash
# 1. Definir el dominio en .env
echo 'PASSWD_DOMAIN=passwd.su-organizacion.tld' >> .env
# 2. Colocar el certificado de la CA en infrastructure/nginx/certs/{fullchain,privkey}.pem
#    (o, para pruebas: sh infrastructure/nginx/generar-cert-autofirmado.sh localhost)
# 3. Levantar app + nginx (la app deja de publicarse en el host; solo entra por 443)
docker compose -f docker-compose.yml -f docker-compose.nginx.yml up -d --build
```

El procedimiento completo —certificado de CA interna/comercial, Let's Encrypt con
renovación automática, **rotación de certificados sin caída** y verificación TLS— está en
**[`docs/guia-nginx-tls.md`](guia-nginx-tls.md)**.

> La IP real del cliente en la auditoría queda resuelta por esta solución: nginx sobrescribe
> `X-Forwarded-For` con la dirección observada y la app arranca con `--proxy-headers`. No es
> necesario ajustar rangos manualmente.

### 4.4 Claves criptográficas

```bash
# Generar y colocar en .env (recomendado en producción, en lugar de los archivos automáticos):
python3 - <<'EOF'
import secrets
from cryptography.fernet import Fernet
print("PASSWD_SECRET_KEY=" + secrets.token_urlsafe(48))
print("PASSWD_ENCRYPTION_KEY=" + Fernet.generate_key().decode())
EOF
```

- Custodiar copia de ambas claves y de la frase de respaldo en el gestor corporativo o sobre sellado.
- **Perder `PASSWD_ENCRYPTION_KEY` = perder todas las contraseñas guardadas** (el respaldo cifrado
  con frase es el único camino de recuperación).
- **Rotación de la clave de cifrado** (si se sospecha compromiso):
  1. `python -m app.cli respaldo --salida rotacion.passwd` (con frase fuerte)
  2. Cambiar `PASSWD_ENCRYPTION_KEY` en `.env` y reiniciar
  3. `python -m app.cli restaurar --entrada rotacion.passwd --sobrescribir`
  4. Destruir `rotacion.passwd` de forma segura y registrar la operación.

### 4.5 Despliegue paso a paso

```bash
cd /srv && git clone <repositorio> passwd && cd passwd   # o copiar el release aprobado
cp .env.example .env && chmod 600 .env
# Editar .env: admin inicial, claves de 4.4, (opcional) PASSWD_DATABASE_URL
docker compose up -d --build
docker compose ps                       # app "healthy"
curl -s http://127.0.0.1:8000/healthz   # {"estado":"ok"}
```

Primer acceso vía `https://passwd.su-organizacion.tld`: cambio de contraseña forzado + enrolamiento
MFA + guardar códigos de recuperación. Crear el resto de usuarios con el menor rol necesario.
**Después del arranque inicial, retire `PASSWD_ADMIN_PASSWORD` del `.env`** (solo se usa si la BD está vacía).

### 4.6 Base de datos: SQLite o MySQL

| Criterio | SQLite (por defecto) | MySQL 8 (perfil opcional) |
|---|---|---|
| Equipos de hasta ~25 usuarios | ✅ idóneo | innecesario |
| Alta concurrencia / BD corporativa existente | limitado | ✅ |
| Operación | cero administración; respaldo = CLI | requiere DBA; arranque: `docker compose -f docker-compose.yml -f docker-compose.mysql.yml up -d` con `MYSQL_PASSWORD` en `.env` |

### 4.7 Respaldos programados

```bash
# /etc/cron.d/passwd-respaldo  (la frase viene del .env: PASSWD_BACKUP_PASSPHRASE)
30 2 * * * root cd /srv/passwd && docker compose exec -T app \
  python -m app.cli respaldo --salida /srv/passwd/data/respaldo-$(date +\%F).passwd --retener 30
```

- `--retener 30` conserva los 30 respaldos `*.passwd` más recientes del directorio (poda el resto).
- Si las notificaciones están configuradas (`PASSWD_NOTIFY_ENABLED`), un fallo del respaldo envía una alerta por correo.
- Copiar el archivo a un destino **externo** (NAS/remoto) tras generarse, p. ej. añadiendo al cron
  `&& rsync -a /srv/passwd/data/respaldo-*.passwd usuario@nas:/respaldos/` (o el cliente S3 de su entorno).
- **Prueba de restauración trimestral** en una máquina aparte (criterio CIS 11.x): restaurar el último
  respaldo y verificar el acceso a una credencial conocida.

### 4.8 Verificación posterior al despliegue (smoke test)

```bash
curl -s https://passwd.su-organizacion.tld/healthz                      # {"estado":"ok"}
curl -sI https://passwd.su-organizacion.tld/login | grep -iE \
  "strict-transport|content-security|x-frame"                           # cabeceras presentes
curl -s -o /dev/null -w "%{http_code}\n" https://passwd.../docs         # 404
```

Más: login completo con MFA de un usuario real, un «Revelar» de prueba y confirmación del evento en /auditoria.

---

## 5. Operación y mantenimiento

### 5.1 Tareas periódicas

| Frecuencia | Tarea | Responsable |
|---|---|---|
| Diaria (automática) | Respaldo cifrado por cron + copia externa | Sistema / TI |
| Semanal | Revisar /auditoria: `login_fallido`, `cuenta_bloqueada`, `acceso_denegado`, `credencial_revelada` inusuales | Auditor / Seguridad |
| Mensual | Revisar usuarios: «último acceso» antiguo → desactivar (CIS 5.3); credenciales con alerta de rotación → rotar | Administrador |
| Trimestral | Prueba de restauración del respaldo; re-ejecución de `pytest` tras actualizaciones; revisión de esta guía | TI / Seguridad |
| Anual | Rotación preventiva de la frase de respaldo; revisión de la matriz de cumplimiento | Seguridad |

### 5.2 Incidentes comunes

| Situación | Procedimiento |
|---|---|
| Usuario bloqueado (5 intentos) | Esperar 15 min, o admin: **Restablecer clave** (emite temporal y desbloquea) |
| Dispositivo MFA perdido | El usuario entra con un **código de recuperación**; si no tiene, admin: **Reiniciar MFA** (re-enrolamiento forzado y sesiones revocadas) |
| Códigos de recuperación agotados | Admin: **Reiniciar MFA** → nuevo juego de códigos al re-enrolar |
| Olvido de contraseña | Admin: **Restablecer clave** → temporal de un solo uso |
| Baja de personal | **Desactivar** la cuenta (revoca sesiones al instante) y **rotar las credenciales de activos** que esa persona haya podido revelar (la bitácora filtra `credencial_revelada` por usuario) |
| Sospecha de fuga de la BD | Las contraseñas están cifradas y las sesiones hasheadas; aun así: rotar claves (4.4), rotar credenciales de activos, revisar auditoría |
| Pérdida de la frase de respaldo | Los respaldos existentes quedan irrecuperables: generar de inmediato un respaldo nuevo con frase nueva |

### 5.3 Actualizaciones del sistema

```bash
cd /srv/passwd
python -m app.cli respaldo --salida data/pre-actualizacion.passwd   # respaldo previo SIEMPRE
git pull                       # o desplegar el release aprobado
docker compose up -d --build
curl -s http://127.0.0.1:8000/healthz
```

Reversión: volver al commit/release anterior, reconstruir y, solo si hubo corrupción de datos,
restaurar `pre-actualizacion.passwd`.

### 5.4 Matriz de responsabilidades

| Actividad | Admin del sistema | Operador | Auditor | Seguridad |
|---|:-:|:-:|:-:|:-:|
| Altas/bajas de usuarios y roles | **R** | — | — | C |
| Gestión del inventario y credenciales | R | **R** | — | — |
| Revisión de bitácora | C | — | **R** | A |
| Respaldos y restauración | **R** | — | — | C |
| Custodia de claves y frase | C | — | — | **R** |
| Aprobación de cambios/adiciones | C | — | — | **A** |

(R = responsable, A = aprueba, C = consultado)

---

## 6. Documentos relacionados

- [`README.md`](../README.md) — características y arranque rápido
- [`docs/modelo-datos.md`](modelo-datos.md) — modelo relacional
- [`docs/cumplimiento-cis-v8.1.md`](cumplimiento-cis-v8.1.md) — matriz CIS Controls v8.1
- [`docs/cumplimiento-iso-27003.md`](cumplimiento-iso-27003.md) — alineación ISO/IEC 27003 y Anexo A
- [`docs/verificacion-cumplimiento.md`](verificacion-cumplimiento.md) — informe de verificación con evidencia
