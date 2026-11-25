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
- 🔜 **WebAuthn / FIDO2 como segundo factor** (llave física o *passkey*), al menos para las cuentas
  de administrador. Es la **mejora de seguridad de mayor impacto** pendiente para este sistema. El
  TOTP actual resiste todos los vectores auditados en
  [`resistencia-bypass-mfa.md`](resistencia-bypass-mfa.md) —replay, re-enrolamiento, fuerza bruta,
  fijación de sesión—, pero es **intrínsecamente vulnerable al phishing en tiempo real**
  (*adversary-in-the-middle*: Evilginx, Modlishka), donde un sitio falso proxifica el real y usa la
  contraseña y el código al instante. Ningún control de servidor puede distinguir ese uso, porque el
  código es legítimo y se usa una sola vez. WebAuthn lo cierra por diseño: la firma va **ligada al
  dominio**, de modo que un sitio falso no puede reutilizarla. Dado que este sistema custodia las
  contraseñas de todos los servidores, el TOTP es el eslabón más débil que queda en el acceso.

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

## Fase 6 — Versatilidad y migración (feedback de preproducción) ✅ (entregada)

- ✅ **Vault personal por usuario** (`EntradaVault`): cada usuario guarda contraseñas de
  servicios, aplicaciones o cuentas propias, **privadas** (solo el dueño las ve/revela; ni el
  admin accede). Permiso `vault.usar` (todos los roles), contraseña cifrada (Fernet), revelado y
  copiado auditados y limitados. Web (`/vault`) y JSON (`/api/web/vault`); se incluye en el
  respaldo cifrado, nunca en el export en claro.
- ✅ **Especificaciones de la VM**: RAM, CPU (vCPU/núcleos) y almacenamiento asignados, coherentes
  con el hardware de servidor/hipervisor, en formularios, ficha, API, respaldo y CSV.
- ✅ **Export en claro para migración** (`inventario.exportar`, admin/operador): CSV con las
  contraseñas en claro en el **mismo formato del importador** (round-trip), para editar y migrar
  entre versiones. Web (`POST /exportar`), JSON (`/api/web/exportar`) y CLI (`exportar-csv`);
  auditado y con `Cache-Control: no-store`. Excluye los vaults personales.
- ✅ **Plantilla CSV descargable** (`/plantilla.csv`) e importador alineado con toda la estructura
  (incluidas las specs de VM).

## Fase 7 — Escala, operación y calidad (Olas 3+4 del [análisis](analisis-mejoras.md)) ✅ (entregada)

Escala y operación:
- ✅ **Pool de conexiones afinado** (`PASSWD_DB_POOL_SIZE/MAX_OVERFLOW/POOL_RECYCLE`) [ESC-3];
  **eager-load** de concesiones del analista (sin N+1) [ESC-4]; **paginación** (`limit`/`offset`) y
  specs de VM en `/api/v1/inventario` [ESC-5]; **amortiguación de escrituras** de actividad de sesión
  y token [ESC-7]; **índice compuesto** `(accion, fecha)` en auditoría [ESC-10].
- ✅ **Respaldos programados** (overlay `docker-compose.backup.yml`, retención + aviso de fallo) [ESC-9].
- ✅ **nginx endurecido**: `limit_req`/`limit_conn`, `gzip`, caché de `/_next/static` y recarga
  automática cada 6 h para adoptar el certificado renovado [OPS-5/OPS-6].
- ✅ **Compose endurecido**: `depends_on: service_healthy`, healthcheck de nginx, límites de recursos
  y rotación de logs [OPS-7].
- ✅ **Secretos externalizables**: variantes `PASSWD_*_FILE` (Docker secrets) y overlay
  `docker-compose.secrets.yml` [OPS-3]; **Dockerfile multi-stage** del backend [OPS-9].
- ✅ **Observabilidad**: aviso de arranque y (Fase 5) IP real; readiness de la app cubierto por el
  healthcheck de contenedor.

Seguridad y calidad:
- ✅ **Tokens de API con alcance y caducidad** (`todo`/`auditoria`/`inventario`, `expira_en`) [SEC-10].
- ✅ **Auditoría encadenada por hash** con evidencia de manipulación + CLI `verificar-auditoria` [SEC-9].
- ✅ **CI ampliado**: cobertura (umbral 70 %), **smoke sobre MySQL**, job de frontend con **Vitest**,
  y escaneo de **secretos (gitleaks)** e **imagen/config (Trivy)** [CAL-3/CAL-4/OPS-2].
- ✅ **Guard de rutas en el borde** (`proxy.ts`) y `global-error.tsx` en el frontend [CAL-5].

Deferidas por requerir infraestructura o decisión externa (documentadas en `analisis-mejoras.md`):
**WebAuthn/FIDO2** (SEC-11: requiere librería + hardware), **HIBP** (SEC-12: llamada externa +
política de privacidad), **HA multi-nodo con MySQL replicado** (ESC-8: orquestador/BD gestionada),
**firma de imágenes cosign/SLSA** (OPS-2: registry + claves), y la **capa de servicios** que unifique
`routes/`↔`api_web/` (CAL-1: refactor transversal, mejor en su propia entrega).

## Fase 8 — Sesión, método de segundo factor y configuración coherente ✅ (entregada en la v1.2.0)

Seguridad:
- ✅ **Fuga de activos restringidos en la exportación JSON, corregida.** `POST /api/web/exportar`
  entregaba al operador las contraseñas de los activos restringidos a administradores (la
  interfaz clásica sí los filtraba). La decisión vive en un único punto (`exportar_auditado`),
  `exportar_csv` es seguro por defecto, y la exportación tiene límite de tasa y aviso al titular.
- ✅ **Importación CSV respeta la restricción**: quien no puede restringir no cuelga máquinas
  virtuales ni credenciales de activos restringidos; el procesado de filas es común a las dos
  interfaces (`app/importacion.py`).
- ✅ **TOTP: rechazo por paso temporal** (no solo por repetición literal del último código),
  fallos de alta que cuentan para el bloqueo y límite de tasa propio en la verificación.
- ✅ **`recifrar` y el respaldo incluyen los ajustes guardados** (la contraseña SMTP ya no queda
  ilegible al rotar la clave) y el respaldo conserva el método de segundo factor.

Sesión:
- ✅ **Aviso de expiración con cuenta atrás** («Extender sesión» / «Cerrar sesión ahora») y, al
  vencer, cierre de la interfaz con redirección al inicio de sesión y regreso a la página de
  origen. Tratamiento único del 401 en el frontend; el servidor borra la cookie vencida;
  sincronización entre pestañas. Ya no queda la interfaz «abierta» sin sesión.

Verificación en dos pasos:
- ✅ **Método elegible por usuario**: aplicación autenticadora o código por correo, con política
  del administrador (correo como principal, correo como respaldo, TOTP obligatorio para
  administradores) y vista **«Mi seguridad»** (cambio de método y regeneración de códigos con
  reautenticación). Comprobación única del segundo factor para ambas interfaces
  (`app/security/segundo_factor.py`).

Configuración:
- ✅ **Consola reorganizada por función**, con dependencias visibles, validación de formato y
  entre ajustes, interruptor propio del servicio de correo (`smtp_enabled`), modos
  STARTTLS / SSL / sin cifrado, **«Probar conexión»** con los valores sin guardar y panel
  **«Estado del correo»**. Mantenimiento periódico (la retención de auditoría surte efecto sin
  reiniciar) y la CLI aplica los ajustes guardados.

> Las fases 9 a 12 se ordenan, con sus roturas, dependencias y criterios de aceptación, como
> **versión 2.0** en [`plan-v2.0.md`](plan-v2.0.md).

## Fase 9 — Unificación de interfaces 🚧 (parcial en la v1.3.0)

La lógica duplicada entre `app/routes/` (interfaz clásica) y `app/api_web/` (JSON) ya causó una
divergencia de seguridad (la exportación de la Fase 8). Al unificar la autenticación en la v1.3.0
aparecieron **tres divergencias más**, las tres con la interfaz clásica en el lado débil: sin
límite de tasa en la verificación del segundo factor, sin contar los fallos de enrolamiento para
el bloqueo, y sin auto-recuperación para las cuentas con segundo factor por correo. Plan:

1. ✅ **Entregado en la v1.3.0.** Casos de uso extraídos a `app/servicios/`: rotación,
   reautenticación, patrones, credenciales y autenticación completa (login por etapas, cambio de
   contraseña, segundo factor por ambos métodos, auto-recuperación y cierre de sesión), además de
   la exportación, la importación y el segundo factor que ya vivían ahí. Quedan inventario,
   usuarios y accesos.
2. 🔜 Dejar `api_web` como única interfaz de aplicación y **retirar la interfaz clásica**
   (`app/routes` salvo `/api/v1`, `app/templates`, `app/static`), migrando antes las pruebas
   que hoy la usan como vía de entrada. Es la rotura R1 de la 2.0 y **ya está avisada** desde la
   v1.3.0: cabecera `Deprecation`, `Link` a la documentación y aviso en las páginas.
3. ✅ **Entregado en la v1.3.0.** Matriz de permisos **generada del registro de rutas**: cada
   dependencia de autorización declara el permiso que exige, y añadir un endpoint sin declarar su
   política hace fallar la suite. La acompañan las pruebas de navegador en CI, que recorren el
   sistema entero (backend + frontend + SMTP simulado).

> La capa `app/servicios/` es además prerrequisito de la gobernanza de rotación: ver
> [`plan-rotacion-agentes.md`](plan-rotacion-agentes.md) §3.4 y §8.1.

## Serie de agentes — v1.4.0 🚧 (en curso)

Primera rotación **desde el sistema**: un agente Go por activo Linux (servidor físico, hipervisor
o VM) recoge un trabajo autorizado, cambia la contraseña de la cuenta local, la verifica y la
confirma o la **revierte**. Corre bajo la gobernanza de la v1.3.0 sin atajos: «Rotar ahora» crea
una solicitud, y nada se despacha sin `AUTORIZADA`. Especificación completa en
[`plan-rotacion-agentes.md`](plan-rotacion-agentes.md) §8.2.

No pertenece a las Fases 9-12, que son el camino de la 2.0 ([`plan-v2.0.md`](plan-v2.0.md)): es
una versión **intercalada y aditiva**, sin roturas, que no retrasa ninguna de las ocho de la 2.0.

1. 🔜 Modelo de datos aditivo: agentes, trabajos de rotación y telemetría.
2. 🔜 Servicios: enrolamiento de un solo uso, identidad de vida corta renovada en cada latido,
   despacho cifrado al par del agente (X25519 + HKDF + Fernet) y cierre por el punto único de
   escritura de la v1.3.0.
3. 🔜 Protocolo `/api/agent/*` con anti-replay, límite de tasa y de tamaño y auditoría de cada
   llamada. `/api/v1` no cambia.
4. 🔜 Agente Go para Linux: sin privilegios, con un *helper* root de una sola acción, journal
   cifrado y unidad systemd endurecida.
5. 🔜 Panel `/agentes` e insignias de cobertura en la ficha del activo.

Todo queda tras `agentes_enabled` apagado hasta el cierre: una credencial de rotación manual se
comporta exactamente igual que en la v1.3.0.

## Fase 10 — Endurecimiento 🔜

- 🔜 **Reautenticación (contraseña + código) para exportar** y otras acciones de alto impacto,
  con el mecanismo ya usado en «Mi seguridad». La autorización de rotaciones la exige con TOTP y
  sin OTP por correo ([`plan-rotacion-agentes.md`](plan-rotacion-agentes.md) §3.5).
- 🔜 **Cifrar las notas del vault personal** (hoy en claro en `EntradaVault.notas`).
- 🔜 **Cadena de auditoría con clave (HMAC)** y escritura serializada, para que quien escriba
  en la base de datos no pueda recalcularla ni bifurcarla. **Se adelanta a la 1.3.0**: el libro
  mayor de rotaciones solo prueba quién aprobó qué si la cadena no se puede recalcular
  ([`plan-rotacion-agentes.md`](plan-rotacion-agentes.md) §3.6).
- 🔜 **CSP con nonce en el frontend** (retirar `'unsafe-inline'` de `script-src`).
- 🔜 **Valores seguros por defecto**: `RATE_LIMIT_BACKEND=bd` y `REQUIRE_ENV_KEYS=true`.
- 🔜 **Contenedores**: `read_only`, `cap_drop: ALL`, `no-new-privileges`.
- 🔜 **Cadena de suministro**: lockfile de Python con hashes, Dependabot, CodeQL, Trivy sobre la
  imagen y *actions* fijadas por SHA.
- 🔜 Manejador global de excepciones; `/api/v1/inventario` respeta la marca `restringido`.
- 🟡 **Neutralizar fórmulas en el CSV del inventario**: choca con el *round-trip* (una
  contraseña puede empezar por `=`); requiere un formato de escape que el importador deshaga.
- 🟡 **Cifrado del lado del cliente (zero-knowledge) para el vault personal**: cambia el modelo
  de recuperación; decidir antes si el aislamiento frente al administrador es un requisito.

## Fase 11 — Funciones nuevas 🔜

- 🔜 **Sesiones activas**: ver y cerrar las propias sesiones; límite de sesiones concurrentes.
- 🔜 **Contraseñas reutilizadas y filtradas** (k-anonimato, con opción sin conexión).
- 🔜 **Papelera e historial de versiones en el vault personal**.
- 🔜 **Generador configurable** (longitud, clases) y medidor de fortaleza con zxcvbn.
- 🔜 **Compartir por enlace de un solo uso** con caducidad.
- 🔜 **Bloqueo en el cliente** al ocultar la pestaña (ocultar secretos revelados).
- 🔜 **Cola de correo con reintentos** y plantillas HTML; programación de `avisar-rotacion`.
- 🔜 **WebAuthn / llaves de acceso** como tercer método elegible (ver Fase 4).

## Fase 12 — Rendimiento y mejora continua 🔜

- 🔜 Paginación del dashboard y del vault; eliminar las consultas repetidas de
  `serializers.py` (`puede_revelar_credencial` por credencial) y `access.py`.
- 🔜 Índice para la búsqueda por nombre sin distinguir mayúsculas.
- 🔜 **Pruebas de navegador** (inicio de sesión, expiración, segundo factor, configuración) y
  de componentes del frontend; cobertura ≥ 80 %.
- 🔜 Revisión trimestral de dependencias y de esta hoja de ruta.

## Extras de bajo coste

- ✅ **Modo oscuro** (atributo `data-tema` en `<html>` + `localStorage`, sin código embebido,
  compatible con la CSP estricta).

## Reconsiderar (ROI bajo para este sistema)

- ⚠️ **Auditoría en tiempo real (WebSocket)**: añade asincronía para poco valor; alternativa
  barata: auto-refresco de `/auditoria`.
- ⚠️ **GeoIP**: mantener la base MaxMind para una herramienta interna de IPs corporativas aporta
  poco frente al coste de actualización/licencia.
