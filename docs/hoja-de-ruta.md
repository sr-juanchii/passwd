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

## Extras de bajo coste

- ✅ **Modo oscuro** (atributo `data-tema` en `<html>` + `localStorage`, sin código embebido,
  compatible con la CSP estricta).

## Visión a largo plazo (sin priorizar)

- 🔭 **Rotación remota de contraseñas (evolución a PAM)**: que el sistema cambie la contraseña
  directamente en el servidor (ciclo cerrado). Cambio de paradigma de bóveda pasiva a plataforma
  de acceso privilegiado, con su propio modelo de amenazas. Visión, riesgos y hoja de fases en
  [`vision-rotacion-remota.md`](vision-rotacion-remota.md).
- ⏸️ **LDAP / Active Directory / OIDC** (SSO): candidata futura, sin prioridad (ver Fase 4).

## Reconsiderar (ROI bajo para este sistema)

- ⚠️ **Auditoría en tiempo real (WebSocket)**: añade asincronía para poco valor; alternativa
  barata: auto-refresco de `/auditoria`.
- ⚠️ **GeoIP**: mantener la base MaxMind para una herramienta interna de IPs corporativas aporta
  poco frente al coste de actualización/licencia.
