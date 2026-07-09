# Hoja de ruta de mejoras

Evaluación de viabilidad y plan de evolución del sistema, derivado del análisis de mejoras.
Marca el estado de cada propuesta y el orden de desarrollo por fases.

**Leyenda:** ✅ implementado · 🔜 planificado · 🟡 viable con matiz · ⚠️ reconsiderar (ROI bajo).

## Fase 0 — Cimiento (habilitador) ✅ (entregada)

- ✅ **Reconciliación de esquema sin dependencias** (`app/schema_sync.py`): al arrancar, tras
  `create_all`, añade las **columnas nuevas** que falten (`ALTER TABLE ADD COLUMN`, SQLite/MySQL)
  para que las bases existentes adopten versiones nuevas sin recrearse. Cubre todos los cambios
  **aditivos** de la Fase 2 (tablas y columnas). Para cambios **no aditivos** (eliminar/renombrar
  columnas, cambiar tipos o CHECK) el proyecto ya incorpora **Alembic** (Fase 5).

## Fase 1 — Cumplimiento y visibilidad ✅ (entregada)

- ✅ **Exportación de auditoría a CSV** (`app/routes/audit_view.py`): conjunto filtrado completo,
  solo admin/auditor, la exportación se audita y las celdas se sanean contra inyección de
  fórmulas (Excel/Sheets).
- ✅ **Dashboard de métricas de seguridad** (`app/routes/metrics.py`): rotación pendiente, logins
  fallidos 24 h/7 d, usuarios bloqueados, cuentas sin MFA, top de accesos a credenciales (30 d) y
  concesiones por caducar. Roles admin/auditor.
- ✅ **Búsqueda global** (`app/routes/search.py`): servidores, hipervisores, VMs y credenciales
  (por usuario/servicio, nunca por contraseña), **filtrada por el control de acceso por objeto**
  para no exponer el inventario a un analista.

## Fase 2 — Inventario más rico ✅ (entregada)

- ✅ **Campos de hardware/estado** (RAM, CPU, almacenamiento, serie, garantía, proveedor, estado).
- ✅ **Etiquetas/tags** en activos, incluidas en la búsqueda global.
- ✅ **Notas seguras** cifradas por activo (Fernet, revelado auditado y por acceso por objeto).
- ✅ **Historial de contraseñas** anteriores (tope `N` configurable, revelado auditado solo a gestores).
- ✅ **Importación masiva CSV** (en memoria, sin persistir el archivo, cifrando al guardar; errores
  por fila sin abortar; auditada).

## Fase 3 — Seguridad proactiva y operación desatendida ✅ (entregada)

- ✅ **Notificaciones por email** (opt-in, `app/notifications.py`): alertas de cuenta bloqueada,
  posible exfiltración (límite de revelados superado), alta de usuario y fallo de respaldo. De
  mejor esfuerzo (un fallo de SMTP no rompe el flujo) y **nunca incluyen secretos**.
- ✅ **Respaldos automáticos**: cron + `PASSWD_BACKUP_PASSPHRASE` (guía §4.7) más `--retener N`
  (poda los respaldos antiguos) y aviso por correo ante un fallo. El envío offsite (S3/FTP) se
  documenta como paso posterior (rsync/cliente del entorno) para no añadir dependencias pesadas.
- ✅ **Rate limit compartido** (`PASSWD_RATE_LIMIT_BACKEND=bd`): backend opcional en base de datos
  (tabla `eventos_tasa`) para despliegues con varias instancias, sin necesidad de Redis. Por
  defecto sigue en memoria (un proceso).

## Fase 4 — Integración empresarial (con su propio modelo de amenazas)

- ✅ **API REST de solo lectura con tokens** (`app/routes/api.py`, `/api/v1/...`): autenticación
  Bearer (sin cookies ni CSRF), solo lectura, **nunca expone secretos**; endpoints de auditoría
  (ingestión incremental para SIEM) e inventario. Tokens gestionados por admin (`/tokens`), solo
  hash en BD, revocables y limitados por tasa.
- ⏸️ **LDAP / Active Directory / OIDC**: **sin prioridad por ahora; no se incorpora a `main`.**
  Toca el flujo de autenticación y requiere el IdP de la organización y decisiones de política
  (aprovisionamiento, roles, break-glass, MFA del IdP) más una revisión de seguridad dedicada.
  Queda como candidata futura; cuando se priorice se retomará el diseño y se implementará con esos
  datos.

## Fase 5 — Endurecimiento (Olas 1+2 del [análisis de mejoras](analisis-mejoras.md)) ✅ (entregada)

- ✅ **IP real tras el proxy** (`PASSWD_TRUSTED_PROXIES`): auditoría y límites de tasa con la IP
  del cliente, no la de nginx (cierra el hallazgo H-2 de la verificación). [SEC-3]
- ✅ **Presupuesto anti-exfiltración compartido**: los revelados de notas e historial (web y JSON)
  usan también el backend en BD; prod/preprod pasan a `PASSWD_RATE_LIMIT_BACKEND=bd` y la app
  avisa al arrancar en modo memoria. [SEC-4/SEC-5]
- ✅ **Revocación persistente en la vía JSON** para usuarios desactivados. [SEC-6]
- ✅ **Búsqueda corregida para el analista**: el filtro por concesiones se aplica en SQL **antes**
  del límite (web y JSON). [ESC-2]
- ✅ **CI de frontend** (eslint, `tsc`, `next build`, `pnpm audit`) y **CSP + Permissions-Policy**
  en las páginas de Next (nginx queda como único emisor de HSTS, sin cabeceras duplicadas).
  [OPS-1/OPS-4]
- ✅ **Modo estricto de claves** (`PASSWD_REQUIRE_ENV_KEYS`): en producción las claves llegan por
  entorno o la app no arranca. [SEC-1]
- ✅ **Rotación de la clave de cifrado**: `PASSWD_ENCRYPTION_KEY` multi-clave (MultiFernet) +
  comando `recifrar` — rotación sin restaurar respaldos. [SEC-2]
- ✅ **Blocklist amplia** de 10 000 contraseñas comunes empaquetada. [SEC-7]
- ✅ **Respaldo v2**: scrypt `n=2^17` con parámetros declarados en el archivo (v1 restaurable),
  frase mínima 16. [SEC-8]
- ✅ **Alembic**: migraciones versionadas con línea base del esquema completo. [ESC-1]

Las mejoras restantes del análisis (olas 3 y 4: paginación, N+1, pool, TTL/alcance de tokens,
capa de servicios, observabilidad, secretos en Docker, etc.) quedan como candidatas siguientes;
ver [`analisis-mejoras.md`](analisis-mejoras.md).

## Extras de bajo coste

- ✅ **Modo oscuro** (atributo `data-tema` en `<html>` + `localStorage`, sin código embebido,
  compatible con la CSP estricta).

## Reconsiderar (ROI bajo para este sistema)

- ⚠️ **Auditoría en tiempo real (WebSocket)**: añade asincronía para poco valor; alternativa
  barata: auto-refresco de `/auditoria`.
- ⚠️ **GeoIP**: mantener la base MaxMind para una herramienta interna de IPs corporativas aporta
  poco frente al coste de actualización/licencia.
