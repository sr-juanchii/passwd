# Matriz de cumplimiento — CIS Controls v8.1

Ámbito evaluado: la aplicación **Gestor de Contraseñas de Servidores** (este repositorio).
Se listan las salvaguardas (safeguards) de CIS Controls v8.1 aplicables a una aplicación
interna de gestión de credenciales y su estado.

**Leyenda de estado**
- ✅ **Implementado**: control técnico aplicado por el sistema, con evidencia en el código.
- 🔶 **Despliegue**: el sistema lo soporta; requiere configuración del entorno al desplegar.
- 📋 **Organizativo**: proceso de la institución; el sistema aporta soporte o evidencia.

## Control 1 — Inventario y control de activos empresariales

| Salvaguarda | Descripción | Estado | Implementación / evidencia |
|---|---|---|---|
| 1.1 | Establecer y mantener un inventario detallado de activos | ✅ | El sistema es el inventario: servidores físicos (función única u host de virtualización), hipervisores y máquinas virtuales, con descripción del sistema, SO, IP y ubicación, en modelo relacional con integridad referencial. `app/models.py` |

## Control 3 — Protección de datos

| Salvaguarda | Descripción | Estado | Implementación / evidencia |
|---|---|---|---|
| 3.3 | Configurar listas de control de acceso a los datos | ✅ | RBAC con matriz de permisos explícita (admin / operador / auditor / analista) **más control de acceso por objeto**: el analista solo accede a los activos y credenciales que se le conceden (least privilege, default-deny). `app/rbac.py`, `app/access.py`, `app/deps.py` |
| 3.10 | Cifrar datos sensibles en tránsito | 🔶 | Despliegue obligatorio detrás de proxy TLS; cookies `Secure` y HSTS activados por defecto. `docker-compose.yml`, `app/main.py` |
| 3.11 | Cifrar datos sensibles en reposo | ✅ | Contraseñas de activos y semillas TOTP cifradas con Fernet (AES + HMAC) antes de persistirse; contraseñas de usuarios con hash Argon2id; claves fuera del repositorio (entorno o archivo 0600). `app/security/crypto.py`, `app/security/passwords.py`, `app/config.py` |
| 3.14 | Registrar el acceso a datos sensibles | ✅ | Cada revelado de una contraseña genera un evento de auditoría con usuario, IP, agente y activo afectado. `app/routes/credentials.py` (`credencial_revelada`) |

## Control 4 — Configuración segura de activos y software

| Salvaguarda | Descripción | Estado | Implementación / evidencia |
|---|---|---|---|
| 4.3 | Bloqueo automático de sesión por inactividad | ✅ | Expiración por inactividad (15 min, configurable) y vida máxima absoluta (8 h) gestionadas en servidor. `app/security/sessions.py` |
| 4.7 | Gestionar cuentas por defecto | ✅ | El administrador de arranque nace con cambio de contraseña forzado y enrolamiento MFA obligatorio: la credencial inicial es de un solo uso. `app/main.py` (`_bootstrap_admin`) |

## Control 5 — Gestión de cuentas

| Salvaguarda | Descripción | Estado | Implementación / evidencia |
|---|---|---|---|
| 5.2 | Usar contraseñas únicas y robustas | ✅ | Política: mínimo 12 caracteres (CIS exige 8 con MFA), lista de contraseñas comunes prohibidas, sin nombre de usuario embebido; generador CSPRNG de 20 caracteres para credenciales de activos y alerta visual cuando una credencial supera el umbral configurable sin rotarse. `app/security/passwords.py`, `app/static/app.js`, `app/models.py` (`dias_sin_rotar`) |
| 5.3 | Deshabilitar cuentas inactivas | ✅/📋 | Desactivación inmediata con revocación de sesiones desde la consola admin; la revisión periódica de cuentas sin uso (campo «último acceso» visible) es proceso organizativo. `app/routes/users.py` |
| 5.4 | Restringir privilegios de administrador a cuentas dedicadas | ✅ | Rol `admin` separado; operación diaria posible con roles `operador`/`auditor` de menor privilegio. `app/rbac.py` |
| 5.6 | Centralizar la gestión de cuentas | ✅ | Toda alta, baja, rol y restablecimiento se gestiona en un único módulo auditado. `app/routes/users.py` |

## Control 6 — Gestión del control de accesos

| Salvaguarda | Descripción | Estado | Implementación / evidencia |
|---|---|---|---|
| 6.1 | Proceso de concesión de accesos | ✅ | Alta por administrador con rol explícito, contraseña temporal de un solo uso y evento de auditoría. `app/routes/users.py` |
| 6.2 | Proceso de revocación de accesos | ✅ | Desactivar, cambiar rol o restablecer credenciales revoca todas las sesiones vivas del usuario al instante. `app/security/sessions.py` (`revocar_sesiones_de_usuario`) |
| 6.3 | MFA en aplicaciones expuestas | ✅ | TOTP (RFC 6238) **obligatorio para todas las cuentas**; ninguna sesión alcanza la etapa activa sin segundo factor. `app/routes/auth.py` |
| 6.4 | MFA para acceso remoto | ✅ | Ídem 6.3: el acceso es vía web y siempre exige MFA. |
| 6.5 | MFA para cuentas administrativas | ✅ | Ídem 6.3, incluye el rol admin sin excepción. |
| 6.7 | Centralizar el control de acceso | ✅ | Sesiones gestionadas en servidor (revocables), no tokens autocontenidos. `app/security/sessions.py` |
| 6.8 | Definir y mantener control de acceso basado en roles | ✅ | Matriz de permisos por rol documentada y aplicada en un único punto, complementada con concesiones por activo para el rol analista (acceso mínimo necesario, con nivel y caducidad). `app/rbac.py`, `app/access.py`, `docs/control-acceso.md` |

## Control 8 — Gestión de registros de auditoría

| Salvaguarda | Descripción | Estado | Implementación / evidencia |
|---|---|---|---|
| 8.1 | Establecer proceso de gestión de registros | ✅ | Bitácora estructurada con acciones normalizadas y retención configurada. `app/audit.py` |
| 8.2 | Recolectar registros de auditoría | ✅ | Autenticación (éxitos y fallos), MFA, bloqueos, gestión de cuentas, CRUD de inventario, accesos denegados y revelados de contraseñas. `app/audit.py` |
| 8.5 | Recolectar registros detallados | ✅ | Cada evento incluye fecha UTC, usuario, acción, objeto, detalle, IP, agente de usuario y resultado. `app/models.py` (`RegistroAuditoria`) |
| 8.10 | Retener registros ≥ 90 días | ✅ | Retención por defecto 365 días; el purgado nunca baja del mínimo de 90 días aunque se configure menos. `app/audit.py` (`purgar_antiguos`) |
| 8.11 | Revisar los registros de auditoría | ✅/📋 | Vista dedicada con filtros por usuario y acción para roles admin/auditor; la cadencia de revisión es proceso organizativo. `app/routes/audit_view.py` |

## Control 11 — Recuperación de datos

| Salvaguarda | Descripción | Estado | Implementación / evidencia |
|---|---|---|---|
| 11.1 | Establecer proceso de recuperación de datos | ✅/📋 | Comandos `respaldo`/`restaurar` documentados en README; la programación periódica (cron) y la prueba de restauración son proceso organizativo. `app/cli.py` |
| 11.2 | Realizar respaldos automatizables | ✅ | Exportación completa (usuarios, inventario, credenciales, bitácora) en un archivo único apto para automatizar por cron. `app/backup.py` |
| 11.3 | Proteger los datos de recuperación | ✅ | Respaldo cifrado con clave derivada por scrypt de una frase (mín. 12 caracteres) + Fernet; sin la frase el archivo es irrecuperable; escritura con permisos 0600. `app/backup.py` |
| 11.4 | Mantener instancias aisladas de respaldo | 📋 | El archivo es portable (independiente de las claves de la instancia); su custodia fuera de línea corresponde a la institución. |

## Control 12 — Gestión de la infraestructura de red

| Salvaguarda | Descripción | Estado | Implementación / evidencia |
|---|---|---|---|
| 12.2 | Arquitectura de red segura | 🔶 | El compose publica el servicio solo en loopback; la exposición externa exige proxy TLS. `docker-compose.yml` |

## Control 16 — Seguridad del software de aplicación

| Salvaguarda | Descripción | Estado | Implementación / evidencia |
|---|---|---|---|
| 16.1 | Proceso de desarrollo seguro | ✅ | CI con lint (ruff), análisis estático de seguridad (bandit) y suite de pruebas que cubre autenticación, MFA, RBAC, CSRF y cifrado. `.github/workflows/ci.yml`, `tests/` |
| 16.10 | Aplicar plantillas de diseño seguro | ✅ | CSP estricta sin código embebido, cookies HttpOnly/Secure/SameSite=Strict, anti-CSRF en todos los formularios, mensajes de error genéricos (anti enumeración), rotación de token de sesión, límite de tasa y bloqueo de cuenta. `app/main.py`, `app/deps.py`, `app/routes/auth.py` |
| 16.12 | Verificaciones de seguridad a nivel de código | ✅ | Bandit en el pipeline con umbral de severidad media. `.github/workflows/ci.yml` |

## Controles fuera del alcance técnico de esta aplicación

Los controles CIS 2 (inventario de software), 7 (gestión de vulnerabilidades de plataforma),
9 (correo/navegador), 10 (antimalware), 13 (monitoreo de red), 14 (concienciación),
15 (proveedores), 17 (respuesta a incidentes) y 18 (pentesting) corresponden al entorno y a
los procesos de la institución. La bitácora de auditoría y el inventario de este sistema
sirven como insumo y evidencia para varios de ellos.
