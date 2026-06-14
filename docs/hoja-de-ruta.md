# Hoja de ruta de mejoras

Evaluación de viabilidad y plan de evolución del sistema, derivado del análisis de mejoras.
Marca el estado de cada propuesta y el orden de desarrollo por fases.

**Leyenda:** ✅ implementado · 🔜 planificado · 🟡 viable con matiz · ⚠️ reconsiderar (ROI bajo).

## Fase 0 — Cimiento (habilitador) ✅ (entregada)

- ✅ **Reconciliación de esquema sin dependencias** (`app/schema_sync.py`): al arrancar, tras
  `create_all`, añade las **columnas nuevas** que falten (`ALTER TABLE ADD COLUMN`, SQLite/MySQL)
  para que las bases existentes adopten versiones nuevas sin recrearse. Cubre todos los cambios
  **aditivos** de la Fase 2 (tablas y columnas). Para cambios **no aditivos** (eliminar/renombrar
  columnas, cambiar tipos o CHECK) se recomienda adoptar **Alembic** en su momento.

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

## Fase 3 — Seguridad proactiva y operación desatendida 🔜

- 🔜 **Notificaciones por email** (opt-in; nunca incluyen secretos; sujeto a política de red).
- 🟡 **Respaldos automáticos**: el cron + `PASSWD_BACKUP_PASSPHRASE` ya está documentado
  (guía §4.7); falta retención, aviso de fallo y envío offsite (S3/FTP).
- 🟡 **Rate limit compartido** (Redis o backend en BD): solo necesario al escalar a varias
  instancias. Hoy corre un proceso y el bloqueo de cuenta ya es persistente en BD.

## Fase 4 — Integración empresarial (con su propio modelo de amenazas) 🟡

- 🟡 **API REST con tokens**: empezar por exportación de auditoría de **solo lectura** para SIEM.
  Tensión con la postura actual (API/docs deshabilitadas): superficie nueva a diseñar con cuidado.
- 🟡 **LDAP / Active Directory / OIDC**: cambio arquitectónico; redefine dónde se aplica el MFA.

## Extras de bajo coste

- 🔜 **Modo oscuro** (clase en `<html>` + `localStorage`, compatible con la CSP).

## Reconsiderar (ROI bajo para este sistema)

- ⚠️ **Auditoría en tiempo real (WebSocket)**: añade asincronía para poco valor; alternativa
  barata: auto-refresco de `/auditoria`.
- ⚠️ **GeoIP**: mantener la base MaxMind para una herramienta interna de IPs corporativas aporta
  poco frente al coste de actualización/licencia.
