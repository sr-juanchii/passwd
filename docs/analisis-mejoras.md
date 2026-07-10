# Análisis integral de mejoras

Catálogo de oportunidades de mejora del **Gestor de Contraseñas de Servidores**, derivado de una
revisión completa del **código** (backend, frontend, infraestructura, CI) y de **toda la
documentación** (`docs/`, README, contratos de API). Complementa a
[`hoja-de-ruta.md`](hoja-de-ruta.md): la hoja de ruta recoge lo ya entregado (Fases 0–4) y las
decisiones tomadas; este documento propone el **siguiente escalón** de robustez, seguridad,
escalabilidad y calidad.

> **Punto de partida.** El sistema ya es **conforme en su alcance técnico** (CIS v8.1 / ISO 27001:2022
> / OWASP, verificado en [`verificacion-cumplimiento.md`](verificacion-cumplimiento.md), con suite de
> pruebas y SAST en verde). Lo que sigue **no son fallos de un producto inmaduro**, sino mejoras
> incrementales y decisiones de arquitectura para reforzar la estructura de cara a más escala,
> más superficie de ataque y operación desatendida.

> **Fuera de alcance por decisión.** La integración con directorio corporativo (**LDAP/AD/OIDC**)
> queda **excluida** de este análisis por indicación expresa; ya estaba diferida en la hoja de ruta.

---

## Cómo leer este documento

Cada mejora lleva un **identificador** por área (`SEC-`, `ESC-`, `CAL-`, `OPS-`, `DOC-`), una
**evidencia** (`archivo:línea`), el **problema**, la **mejora propuesta** y, cuando aplica, el
**control de cumplimiento** que refuerza.

**Leyenda de prioridad** (combina impacto y urgencia):

| Marca | Significado |
|---|---|
| 🔴 **Alta** | Refuerza seguridad de forma material, corrige un comportamiento incorrecto o desbloquea escala real. |
| 🟠 **Media** | Mejora robustez/operación/calidad; recomendable, sin urgencia crítica. |
| 🟡 **Baja** | Pulido, ergonomía o defensa en profundidad de valor acotado. |

**Esfuerzo:** S (pequeño, horas) · M (medio, días) · L (grande, semanas o varias entregas).

---

## Resumen ejecutivo

> **Estado (10/07/2026):** las **Olas 1–4** están **implementadas** salvo cinco ítems diferidos por
> requerir infraestructura o decisión externa. Olas 1–2 en [`hoja-de-ruta.md`](hoja-de-ruta.md) Fase 5;
> Olas 3–4 en la **Fase 7** (ESC-3/4/5/7/9/10, OPS-2/3/5/6/7/9, SEC-9/10, CAL-3/4/5). **Diferidos:**
> SEC-11 (WebAuthn), SEC-12 (HIBP), ESC-8 (HA multi-nodo), OPS-2 (firma cosign/SLSA) y CAL-1 (capa de
> servicios `routes/`↔`api_web/`), cada uno con su motivo. Los ítems se conservan aquí como registro.

Mejoras de mayor retorno, agrupadas por área:

| ID | Mejora | Área | Prioridad | Esfuerzo |
|---|---|---|:-:|:-:|
| SEC-1 | Sacar la clave de cifrado del directorio de datos (entorno/KMS obligatorio en prod) | Seguridad | 🔴 | M |
| SEC-2 | Rotación de la clave de cifrado con `MultiFernet` + recifrado por CLI | Seguridad | 🔴 | M |
| SEC-3 | Reconocer el proxy inverso para IP real (rate-limit y auditoría verídicos) | Seguridad | 🔴 | S |
| SEC-4 | Backend de rate-limit compartido (`bd`) por defecto en producción | Seguridad | 🔴 | S |
| SEC-5 | Compartir el presupuesto anti-exfiltración en historial y notas (`db=`) | Seguridad | 🔴 | S |
| ESC-1 | Adoptar **Alembic** para migraciones no aditivas | Escalabilidad | 🔴 | M |
| ESC-2 | Corregir el truncado-antes-de-filtrar de la búsqueda | Escalabilidad | 🔴 | S |
| CAL-1 | Eliminar la duplicación `routes/` vs `api_web/` con una capa de servicios | Calidad | 🔴 | L |
| CAL-4 | Introducir pruebas de frontend (unitarias + E2E del flujo crítico) | Calidad | 🔴 | M |
| OPS-1 | Incluir el frontend en CI (lint, type-check, build, audit) | DevSecOps | 🔴 | S |
| OPS-3 | Externalizar secretos (Docker secrets / Vault / SOPS) | DevSecOps | 🔴 | M |
| OPS-4 | Emitir CSP y `Permissions-Policy` en las páginas del frontend | DevSecOps | 🔴 | S |

**Secuencia sugerida (por olas):**

1. **Ola 1 — Seguridad y correctitud rápidas:** SEC-3, SEC-4, SEC-5, SEC-6, ESC-2, OPS-1, OPS-4
   (mayoría de esfuerzo S; corrigen comportamientos y cierran huecos sin refactor).
2. **Ola 2 — Criptografía y datos:** SEC-1, SEC-2, SEC-7, SEC-8, ESC-1 (clave y migraciones, base
   para escalar con seguridad).
3. **Ola 3 — Escala y operación:** ESC-3…ESC-9, OPS-3, OPS-5…OPS-8 (pool, paginación, HA, secretos,
   observabilidad, respaldos programados).
4. **Ola 4 — Calidad y deuda:** CAL-1 (capa de servicios), CAL-2…CAL-6, SEC-9…SEC-12, OPS-2, OPS-9
   (refactor, pruebas ampliadas, endurecimiento de la cadena de suministro).

---

## Área A — Seguridad y criptografía

### SEC-1 · Clave de cifrado almacenada junto a los datos — ✅ implementada (Fase 5)
- **Evidencia:** `app/config.py:111,116-118`. Si no se define `PASSWD_ENCRYPTION_KEY`, la clave se
  autogenera en `data_dir/.encryption_key`, **el mismo directorio** donde vive `passwd.db`
  (línea 111).
- **Problema:** un atacante (o un respaldo del volumen) con lectura del directorio de datos obtiene
  **la base de datos y la clave** a la vez; el "cifrado en reposo" deja de proteger frente a un
  compromiso del disco o del backup del volumen.
- **Mejora:** hacer que en producción `PASSWD_ENCRYPTION_KEY` provenga **siempre** de un gestor de
  secretos externo (variable de entorno inyectada por Docker secrets/Vault/KMS); reservar el modo
  "archivo autogenerado" **solo para desarrollo** y documentarlo así. Opcional: cifrado
  sobre-envolvente (envelope) con una clave maestra en KMS/HSM que envuelva la clave de datos.
- **Cumplimiento:** CIS 3.11 · ISO A.8.24.

### SEC-2 · Sin rotación de la clave de cifrado de datos — ✅ implementada (Fase 5)
- **Evidencia:** `app/security/crypto.py` (un único `Fernet`, sin `MultiFernet`).
- **Problema:** cambiar `PASSWD_ENCRYPTION_KEY` deja **todo el material cifrado existente
  indescifrable** (contraseñas de activos, semillas TOTP, notas). Hoy la rotación exige el ciclo
  manual respaldo → cambiar clave → reiniciar → restaurar, descrito en la referencia CLI.
- **Mejora:** adoptar `MultiFernet` (clave nueva la primera para cifrar; claves antiguas disponibles
  para descifrar) y añadir un **comando CLI de recifrado masivo** que reescriba en línea todo el
  material con la clave vigente. Permite rotación sin ventana de indisponibilidad ni restauración.
- **Cumplimiento:** ISO A.8.24.

### SEC-3 · El proxy inverso no se reconoce: IP real perdida — ✅ implementada (Fase 5)
- **Evidencia:** `app/audit.py:83`, `app/routes/auth.py:120` (la IP se toma de
  `request.client.host`). En despliegue con nginx, la plantilla reenvía la IP real en
  `X-Forwarded-For`/`X-Real-IP` (`infrastructure/nginx/templates-frontend/default.conf.template:63-64`),
  pero la app **no las lee**.
- **Problema:** tras el proxy, **todas** las peticiones llegan con la IP de nginx: el rate-limit "por
  IP" se vuelve global (un solo cliente abusivo bloquea a todos, o al revés) y la auditoría registra
  una IP falsa. Ya anotado como hallazgo **H-2** en la verificación de cumplimiento.
- **Mejora:** ejecutar uvicorn con `--proxy-headers --forwarded-allow-ips=<red del proxy>` o parsear
  `X-Forwarded-For` confiando **solo** en una lista de proxies conocidos. *(Precisión posterior:
  los overlays de compose con nginx ya pasaban esas banderas a uvicorn; el hueco real era el
  despliegue sin overlay. La implementación añade `PASSWD_TRUSTED_PROXIES` en la propia app,
  que cubre ambos casos y es idempotente en combinación con las banderas.)*
- **Cumplimiento:** CIS 8.x (calidad del registro) · OWASP (efectividad del anti-brute-force).

### SEC-4 · Rate-limit en memoria por defecto — ✅ implementada (Fase 5)
- **Evidencia:** `app/config.py:97` (`rate_limit_backend` por defecto `"memoria"`).
- **Problema:** el backend en memoria es **por proceso**. Con varios workers de uvicorn o varias
  instancias (escenario multi-instancia que la propia documentación contempla), el límite de login y
  el **límite anti-exfiltración** se multiplican por el número de procesos, debilitando ambas
  protecciones.
- **Mejora:** que producción use `PASSWD_RATE_LIMIT_BACKEND=bd` por defecto (o al menos un aviso
  prominente y un chequeo de arranque que advierta si hay >1 worker con backend en memoria).
- **Cumplimiento:** CIS 16.10 · OWASP API4.

### SEC-5 · Presupuesto anti-exfiltración no compartido en historial y notas — ✅ implementada (Fase 5)
- **Evidencia:** `app/routes/credentials.py:332` (`historial_revelar`),
  `app/api_web/credentials.py:311` y `app/routes/notes.py:113` (`notas_revelar`): llaman
  `ratelimit.permitir_intento(...)` **sin** pasar `db=`.
- **Problema:** aun con `RATE_LIMIT_BACKEND=bd`, estas rutas fuerzan el backend en memoria, de modo
  que el revelado de **contraseñas anteriores** y de **notas** no comparte el presupuesto entre
  instancias (a diferencia del revelado/copiado de la contraseña vigente, que sí lo comparte). Un
  atacante podría exfiltrar historial/notas repartiendo peticiones entre réplicas.
- **Mejora:** pasar `db=db` en esas llamadas para unificar el conteo con el resto del sistema.
- **Cumplimiento:** consistencia del control anti-exfiltración (OWASP API4).

### SEC-6 · Revocación de sesión perdida por rollback en la vía JSON — ✅ implementada (Fase 5)
- **Evidencia:** `app/api_web/deps.py:36` asigna `sesion.revocada_en` y a continuación lanza
  `HTTPException`; `app/database.py:78-79` hace `rollback` ante cualquier excepción que **no** sea
  `RedirigirLogin`, así que ese cambio no se persiste. La vía web sí lo persiste (usa
  `RedirigirLogin`, `app/database.py:74-77`).
- **Problema:** cuando se detecta un usuario desactivado a mitad de sesión, la vía JSON **no llega a
  grabar** la revocación; solo devuelve 401. El comportamiento diverge entre las dos superficies.
- **Mejora:** unificar la persistencia de la revocación (p. ej. `db.commit()` explícito antes de
  lanzar, o un tipo de excepción tratado como `RedirigirLogin` en `get_db`).

### SEC-7 · Lista de contraseñas prohibidas mínima — ✅ implementada (Fase 5)
- **Evidencia:** `app/security/passwords.py:19-22` (blocklist de ~8 entradas); política en
  `validar_politica` (`app/security/passwords.py:40-54`).
- **Problema:** la política (mín. 12, ≥4 distintos, sin username, sin espacios extremos) es correcta,
  pero la lista de comunes prohibidas es demasiado corta para frenar contraseñas débiles reales.
- **Mejora:** empaquetar una lista amplia (p. ej. las 10 000 más comunes) o verificar por
  **k-anonymity contra HIBP** (sin enviar la contraseña, solo un prefijo del hash).
- **Cumplimiento:** CIS 5.2 · ISO A.8.5.

### SEC-8 · Parámetros del respaldo cifrado por debajo de lo recomendado — ✅ implementada (Fase 5)
- **Evidencia:** `app/backup.py:47` (scrypt `n=2**14`), `app/backup.py:39` (frase mínima 12);
  el respaldo se arma como JSON con **todos los secretos en claro** en memoria antes de cifrar.
- **Problema:** el factor de coste de scrypt está por debajo de las recomendaciones actuales
  (≈`2**17` para uso interactivo), lo que abarata un ataque de fuerza bruta sobre la frase si el
  archivo se filtra; además, en bases grandes, construir todo en memoria escala mal.
- **Mejora:** subir el coste de scrypt, exigir una frase más robusta y considerar cifrado en
  *streaming* para respaldos grandes.
- **Cumplimiento:** CIS 11 · ISO A.8.13 · A.8.24.

### SEC-9 · La bitácora "inmutable" no es técnicamente inmutable — 🟠 Media · L
- **Evidencia:** `app/models.py` (tabla `RegistroAuditoria`, ~líneas 508-523): tabla SQL normal en
  **la misma base de datos** que los datos operativos. La integración SIEM es **pull** (el SIEM
  sondea `/api/v1/auditoria`), no push.
- **Problema:** un compromiso de la BD compromete también la auditoría; el texto de la UI la describe
  como "registro inmutable de solo anexado" (ver **DOC-3**) sin un mecanismo que lo garantice.
- **Mejora:** dar **evidencia de manipulación** real — encadenamiento por hash (cada registro
  incluye el hash del anterior) o firma — y/o **reenvío push** a un destino WORM externo
  (syslog/SIEM append-only) para que exista una copia que el atacante de la BD no pueda alterar.
- **Cumplimiento:** CIS 8.x · ISO A.8.15.

### SEC-10 · Tokens de API sin caducidad ni alcance — 🟠 Media · M
- **Evidencia:** `app/routes/api.py` y la gestión en `/tokens`. Todo token Bearer lee **auditoría e
  inventario**; solo se revoca manualmente.
- **Problema:** un token filtrado permanece válido indefinidamente y con más acceso del necesario;
  no hay principio de mínimo privilegio por token.
- **Mejora:** **TTL configurable** por token (caducidad automática) y **scoping** (p. ej. un token
  solo-auditoría para el SIEM, otro solo-inventario), con auditoría del uso.
- **Cumplimiento:** OWASP API2/API5 · ISO A.5.18.

### SEC-11 · Segundo factor limitado a TOTP — 🟠 Media · L
- **Evidencia:** `app/security/mfa.py`, `app/security/recovery.py` (8 códigos de recuperación,
  ~49 bits de entropía por código).
- **Problema:** para cuentas privilegiadas (admin) un TOTP por software es más débil que una llave
  hardware; los códigos de recuperación están al límite inferior de entropía razonable.
- **Mejora:** ofrecer **WebAuthn/FIDO2** (llaves de hardware/passkeys) como segundo factor opcional,
  al menos para admin; subir los códigos de recuperación a 3 grupos.
- **Cumplimiento:** CIS 6.3-6.5 · ISO A.8.5.

### SEC-12 · Defensa en profundidad adicional — 🟡 Baja · S–M (varios)
- Sin **detección de contraseñas comprometidas** (HIBP) para las contraseñas de usuario.
- Sin **límite de sesiones concurrentes** por usuario (el modelo `SesionWeb` permite varias).
- Sin **autoservicio ni verificación de correo**: el reseteo de contraseña y el reinicio de MFA
  dependen 100 % del admin (`docs/manual-administrador.md`).
- Sin **procedimiento de acceso de emergencia (break-glass)** documentado fuera del contexto LDAP.
- **`assert` como control de flujo** en invariantes tras autenticación (`app/deps.py:65`,
  `app/routes/auth.py:219`): se eliminan con `python -O`; sustituir por comprobaciones explícitas.

---

## Área B — Escalabilidad y alta disponibilidad

### ESC-1 · Migraciones limitadas a cambios aditivos (adoptar Alembic) — ✅ implementada (Fase 5)
- **Evidencia:** `app/schema_sync.py:77-100` (solo `ALTER TABLE ADD COLUMN`, e `inspect`+`ALTER` en
  **cada arranque**). Pendiente reconocido en `hoja-de-ruta.md` (Fase 0), `arquitectura.md §6`,
  `guia-desarrollo.md §7` y `control-acceso.md:70`.
- **Problema:** cualquier cambio **no aditivo** (eliminar/renombrar columna, cambiar tipo o CHECK)
  obliga a **recrear la base** — ya ocurrió al añadir el rol `analista`. Sin historial de versiones,
  sin *downgrade*, sin control determinista.
- **Mejora:** adoptar **Alembic** (revisiones versionadas, up/down, integración en el arranque o en
  un paso de despliegue). Mantener `schema_sync` solo como red de seguridad o retirarlo.
- **Impacto:** desbloquea la evolución del esquema en producción sin pérdida de datos.

### ESC-2 · La búsqueda trunca antes de filtrar por acceso — ✅ implementada (Fase 5)
- **Evidencia:** `app/routes/search.py:64,72,80,86` aplican `.limit(LIMITE_POR_TIPO)` en SQL, y solo
  **después** se filtra por acceso con `visibles()` (`app/routes/search.py:90-96`).
- **Problema (correctitud):** para un **analista**, el `LIMIT` recorta antes de aplicar sus
  concesiones; puede obtener resultados vacíos o incompletos aunque existan coincidencias en activos
  que sí tiene concedidos más allá de las primeras N filas.
- **Mejora:** filtrar por concesiones **dentro de la consulta SQL** (join con la tabla de concesiones)
  o paginar tras aplicar el filtro de acceso.
- **Cumplimiento:** mantiene OWASP A01/API1 sin degradar la utilidad para el analista.

### ESC-3 · Pool de conexiones sin afinar — 🟠 Media · S
- **Evidencia:** `app/database.py` (motor sin `pool_size`/`max_overflow`/`pool_recycle`; solo
  `pool_pre_ping=True`).
- **Problema:** con MySQL y su `wait_timeout`, conviene `pool_recycle` (pre_ping lo mitiga solo en
  parte); el tamaño del pool debería dimensionarse según los workers.
- **Mejora:** configurar el pool de forma explícita y parametrizable por entorno.

### ESC-4 · Consultas N+1 en el panel del analista y en accesos — 🟠 Media · S
- **Evidencia:** `app/routes/inventory.py:101-102` (orden por `nombre_activo`/`tipo_activo`) con
  `app/access.py:108-113` (`concesiones_vigentes_de_usuario` sin eager-load); paneles de accesos que
  leen `.usuario.username`/`.nombre_activo` por fila.
- **Problema:** cada concesión dispara cargas perezosas adicionales; el coste crece linealmente con
  el número de concesiones.
- **Mejora:** *eager-load* (`selectinload`/`joinedload`) de las relaciones necesarias. El dashboard
  general ya lo hace bien (`app/routes/inventory.py:108-120`), replicar el patrón.

### ESC-5 · Falta paginación en varios listados — 🟠 Media · M
- **Evidencia:** dashboard (todos los activos), usuarios (`app/routes/users.py:52`), tokens y
  `GET /api/v1/inventario` (`app/routes/api.py:90-119`, **sin límite**). La auditoría y la búsqueda
  sí paginan/limitan.
- **Problema:** a mayor inventario, respuestas más pesadas y lentas; `/api/v1/inventario` sin tope
  puede devolver todo el inventario en una sola respuesta.
- **Mejora:** paginación consistente (con `selectinload`) en dashboard, usuarios, tokens y la API v1.

### ESC-6 · Bootstrap y mantenimiento por worker en el arranque — 🟠 Media · M
- **Evidencia:** `app/main.py:193-194` ejecuta `_bootstrap_admin` y `_mantenimiento_arranque` en
  `create_app()`, es decir en **cada** proceso/worker.
- **Problema:** purga y escrituras redundantes por worker y una posible carrera de bootstrap
  (mitigada por conteo + `unique`, pero frágil).
- **Mejora:** mover estas tareas a un **entrypoint único** (comando CLI o paso de migración), o
  ejecutarlas solo en un proceso líder.

### ESC-7 · Amplificación de escritura por actividad de sesión y token — 🟠 Media · S
- **Evidencia:** `app/security/sessions.py:65` (`ultima_actividad` en **cada** acceso autenticado) y
  `app/routes/api.py:53` (`ultimo_uso` del token en **cada** llamada).
- **Problema:** una escritura en BD por petición amplifica la carga de escritura y compite por bloqueos
  (especialmente en SQLite).
- **Mejora:** *throttling* — actualizar la marca como mucho cada N segundos.

### ESC-8 · Sin historia de alta disponibilidad — 🟠 Media · L
- **Evidencia:** despliegue mono-nodo (`docker-compose.*.yml`): `restart: unless-stopped` da
  resiliencia básica, pero SQLite es *single-writer* y MySQL es un contenedor único sin réplica; sin
  límites de recursos ni orquestador.
- **Problema:** no hay tolerancia a fallo del nodo ni escalado horizontal real.
- **Mejora (para HA real):** MySQL gestionado/replicado + varias réplicas de app tras nginx +
  `PASSWD_RATE_LIMIT_BACKEND=bd` (ver SEC-4) + estado (claves/cripto) no dependiente del volumen
  local (ver SEC-1). Documentar la topología HA como escenario de despliegue.
- **Cumplimiento:** CIS 12.

### ESC-9 · Respaldo offsite y programado no nativos — 🟠 Media · M
- **Evidencia:** no hay servicio/cron de respaldo en ningún `docker-compose.*.yml`; el envío offsite
  se documenta como paso manual (rsync/cliente del entorno) en la hoja de ruta y la guía.
- **Problema:** la copia periódica, la retención y la prueba de restauración quedan como tarea
  organizativa manual, propensa a olvido.
- **Mejora:** servicio de respaldo cifrado **programado** dentro del despliegue (con retención y
  aviso de fallo, que ya existen por CLI), envío offsite integrado (S3/FTP) y verificación de
  restauración automatizable. Añadir *dump* programado también para MySQL.
- **Cumplimiento:** CIS 11 · ISO A.8.13.

### ESC-10 · Ajustes finos de datos — 🟡 Baja · S
- Índice compuesto `(accion, fecha)` para acelerar las consultas de métricas
  (`app/routes/metrics.py:50-81`).
- `backup.exportar` carga toda la BD en memoria → *streaming* (relacionado con SEC-8).

---

## Área C — Calidad y deuda técnica

### CAL-1 · Duplicación casi total entre `routes/` y `api_web/` — 🔴 Alta · L
- **Evidencia:** `app/api_web/auth.py` reimplementa casi línea por línea `app/routes/auth.py`
  (rate-limit, hash ficticio de tiempo constante, bloqueo, rehash, etapas, rotación de token, CSRF);
  `_entregar_password`/`_registrar_fallo`/`_podar_historial` están duplicados entre
  `app/routes/credentials.py` y `app/api_web/credentials.py`.
- **Problema:** **la mayor deuda técnica y un riesgo de seguridad**: un parche de seguridad puede
  quedar aplicado en una sola superficie (de hecho SEC-5 se manifiesta en ambas por copia). Doble
  mantenimiento y deriva garantizada con el tiempo.
- **Mejora:** extraer una **capa de servicios** (`app/services/`) con la lógica de negocio y de
  seguridad; dejar `routes/` (HTML) y `api_web/` (JSON) como adaptadores finos de presentación.
- **Impacto:** un solo lugar donde arreglar y probar cada control.

### CAL-2 · Endpoints síncronos con operaciones bloqueantes — 🟠 Media · M
- **Evidencia:** endpoints `def` (no `async`); `enviar_alerta` hace SMTP **dentro de la petición**
  (`app/routes/auth.py:88`, `app/routes/credentials.py:288`); Argon2 consume ~64 MiB por hash.
- **Problema:** SMTP (timeout 10 s) y Argon2 bloquean hilos del *threadpool*; una ráfaga de logins o
  un SMTP lento degradan la latencia general.
- **Mejora:** mover el envío de correo a `BackgroundTasks`; evaluar rutas `async` donde aporte;
  vigilar la presión de memoria de Argon2 bajo carga.

### CAL-3 · Cobertura de pruebas del backend con huecos — 🟠 Media · M
- **Evidencia:** la suite (amplia y sólida) usa **solo SQLite**; no ejercita la vía
  MySQL/`READ COMMITTED`; faltan pruebas del rollback de revocación JSON (SEC-6), de
  `X-Forwarded-For` (SEC-3), del `db=` faltante (SEC-5) y de concurrencia del limitador; no hay
  `pytest-cov`.
- **Mejora:** matriz de CI que ejecute la suite también contra **MySQL**, pruebas que cubran ambas
  superficies compartiendo casos, casos de regresión para los hallazgos anteriores y **cobertura con
  umbral** (`pytest-cov`).

### CAL-4 · Sin pruebas de frontend — 🔴 Alta · M
- **Evidencia:** no existe ninguna prueba (`*.test/*.spec`), ni Vitest/Jest/Playwright, ni script
  `test` en `frontend/package.json`.
- **Problema:** es el mayor punto ciego del frontend; un cambio puede romper el flujo de
  autenticación sin que nada lo detecte.
- **Mejora:** **Vitest + Testing Library** para unidades y **Playwright** para el flujo crítico
  (login → cambio de contraseña → enrolar/verificar MFA → revelar/copiar credencial).

### CAL-5 · Robustez del frontend (datos, validación, guardas) — 🟠 Media · M
- **Evidencia:** sin capa de *data-fetching* con caché/revalidación; validación de formularios manual
  y mínima; guarda de rutas 100 % *client-side* en `frontend/src/app/(app)/layout.tsx` (sin
  `middleware.ts`), lo que provoca un *flash* de layout antes de redirigir; falta `global-error.tsx`;
  las respuestas de la API no se validan en tiempo de ejecución (`return res as unknown as T`).
- **Mejora:** **TanStack Query** (caché, reintentos, estados de carga/error uniformes);
  **react-hook-form + Zod** (validación declarativa + validación de payloads en runtime);
  `middleware.ts` para redirigir en el borde; `global-error.tsx`; anunciar errores con
  `aria-live`/`aria-invalid`/`aria-describedby` (accesibilidad). Decidir explícitamente la política
  de i18n (hoy todo el texto está en español embebido; aceptable si es intencional).

### CAL-6 · Frontend sobre un Next.js "no estándar" — 🟡 Baja · —
- **Evidencia:** `frontend/AGENTS.md` advierte que **no** es el Next.js habitual, con *breaking
  changes*, e indica leer documentación local antes de codificar (Next 16.2.9).
- **Problema:** complica el mantenimiento y las actualizaciones de seguridad del framework.
- **Mejora:** documentar el porqué de esa versión y su plan de actualización; vigilar avisos de
  seguridad (relación con OWASP A06).

---

## Área D — DevSecOps y operación

### OPS-1 · El frontend no pasa por CI — ✅ implementada (Fase 5)
- **Evidencia:** `.github/workflows/ci.yml` tiene un único job **solo de Python** (ruff, bandit,
  pip-audit, pytest). No hay `eslint`, `tsc --noEmit`, `next build`, pruebas ni `pnpm audit`;
  `frontend/package.json` no define script `typecheck`.
- **Mejora:** añadir un job Node con `pnpm install --frozen-lockfile`, `pnpm lint`, `tsc --noEmit`,
  `pnpm build` y (cuando existan, CAL-4) las pruebas; añadir el script `typecheck`.

### OPS-2 · Cadena de suministro sin escaneo completo — 🔴 Alta · M
- **Evidencia:** `pip-audit` solo cubre `requirements.txt`; no hay auditoría de dependencias JS,
  ni escaneo de imágenes (Trivy/Grype), ni SBOM, ni firma (cosign/SLSA); las actions se referencian
  por etiqueta móvil (`actions/checkout@v4`, `actions/setup-python@v5`).
- **Mejora:** `pnpm audit`/Dependabot/Renovate; escaneo de imágenes en CI; generación de SBOM; firma
  de imágenes; **pin de las actions por SHA**; auditar también `requirements-dev.txt`.
- **Cumplimiento:** OWASP A06/A08.

### OPS-3 · Secretos en texto plano vía `.env` — 🔴 Alta · M
- **Evidencia:** `docker-compose.yml` monta `.env` con `env_file`; `PASSWD_ENCRYPTION_KEY`,
  `MYSQL_PASSWORD`, `PASSWD_SMTP_PASSWORD` y `PASSWD_BACKUP_PASSPHRASE` acaban como variables de
  entorno del contenedor.
- **Problema:** los secretos quedan visibles en `docker inspect`, en el entorno del proceso y en
  copias del `.env`. Especialmente crítico para `PASSWD_ENCRYPTION_KEY` (ver SEC-1).
- **Mejora:** **Docker secrets** (`secrets:` + variantes `*_FILE`) o un gestor externo (Vault/SOPS).
  Custodiar la clave de cifrado fuera del volumen de datos.
- **Cumplimiento:** ISO A.8.24 · OWASP A02.

### OPS-4 · Sin CSP ni Permissions-Policy en las páginas del frontend — ✅ implementada (Fase 5)
- **Evidencia:** la CSP estricta del backend (`app/main.py:47-51`) solo cubre respuestas de `/api`.
  Las páginas HTML las sirve Next.js; `next.config.ts` **no** define `headers()`, y la plantilla
  nginx del frontend (`infrastructure/nginx/templates-frontend/default.conf.template:43-50`) añade
  `nosniff`, `X-Frame-Options` y `Referrer-Policy` **pero no** `Content-Security-Policy` ni
  `Permissions-Policy`.
- **Problema:** el documento HTML de la aplicación moderna se sirve **sin CSP**, perdiendo una capa
  clave anti-XSS que la interfaz Jinja sí tiene.
- **Mejora:** emitir `Content-Security-Policy` y `Permissions-Policy` para el frontend (en el bloque
  443 de la plantilla nginx o vía `headers()` en `next.config.ts`), con una política específica de
  Next (probablemente `style-src` con nonce o `'unsafe-inline'` acotado). De paso, evitar la
  **duplicación** de cabeceras en `/api` con `proxy_hide_header`.
- **Cumplimiento:** OWASP A05 · CIS 16.10.

### OPS-5 · nginx sin rate-limit de borde, compresión ni caché de estáticos — 🟠 Media · S
- **Evidencia:** las plantillas nginx no usan `limit_req`/`limit_conn`, ni `gzip`/brotli, ni caché
  para `/_next/static/*` (activos inmutables con hash).
- **Mejora:** `limit_req_zone`/`limit_conn_zone` para frenar fuerza bruta y DoS antes de la app;
  `gzip` (y preferiblemente brotli) para estáticos/JSON; `location /_next/static/` con caché larga.
- **Cumplimiento:** OWASP API4 (defensa en profundidad).

### OPS-6 · nginx no se recarga tras renovar el certificado — 🟠 Media · S
- **Evidencia:** el `--deploy-hook` de certbot solo **copia** los certificados
  (`docker-compose.certbot.yml:26`), y el comentario delega la recarga a "un cron externo"
  (`docker-compose.certbot.yml:8-10`).
- **Problema:** tras renovar, nginx sigue sirviendo el **certificado viejo** hasta que alguien lo
  reinicia/recarga; riesgo de servir un certificado caducado.
- **Mejora:** que el hook ejecute `nginx -s reload` (o `docker kill -s HUP`) sobre el contenedor de
  nginx tras copiar los certificados.

### OPS-7 · Endurecimiento operativo del Compose — 🟠 Media · S
- **Evidencia:** en `docker-compose.frontend.yml`/`docker-compose.nginx.yml`, `depends_on` usa la
  forma corta (solo orden, no *readiness*) para nginx/frontend; no hay healthcheck de nginx; ningún
  servicio define límites de recursos (`deploy.resources`/`mem_limit`); no hay `logging` con rotación
  (`max-size`/`max-file`).
- **Problema:** posibles `502` transitorios al arrancar; un servicio puede agotar el host; los logs
  crecen sin límite.
- **Mejora:** `depends_on: condition: service_healthy` (el backend necesita un healthcheck), límites
  de recursos y rotación de logs en todos los servicios.

### OPS-8 · Observabilidad limitada — 🟠 Media · M
- **Evidencia:** `/healthz` (`app/main.py:216-218`) devuelve estado/versión pero **no comprueba la
  BD**; no hay métricas operativas (Prometheus), ni *tracing* (OpenTelemetry), ni logging
  estructurado con correlación de petición; las alertas por correo son "mejor esfuerzo" y un fallo de
  SMTP se pierde en silencio.
- **Mejora:** separar **liveness/readiness** (readiness con `SELECT 1`), exponer `/metrics` opcional,
  logging **JSON** con id de correlación, y una vía de reintento/registro para las alertas críticas
  de seguridad (que hoy pueden perderse).

### OPS-9 · Reproducibilidad de imágenes y modelo de build — 🟡 Baja · M
- **Evidencia:** el `Dockerfile` del backend no es multi-stage y su imagen base no está *pineada* por
  digest (sin `pip install --require-hashes`); el flujo documentado construye en el servidor
  (`docker compose up -d --build`). *(El `Dockerfile` del frontend ya es multi-stage y con usuario
  no-root — buena referencia.)*
- **Mejora:** multi-stage y pin por digest en el backend; hashes de dependencias; **construir en CI**,
  publicar imágenes versionadas a un *registry* y **desplegar por digest** (separación
  build/release/run del modelo 12-factor), habilitando *rollback* y firma.

---

## Higiene documental (contradicciones detectadas)

Correcciones de bajo coste que mejoran la fiabilidad de la documentación. *(No aplicadas en esta
entrega, que es solo el informe.)*

- **DOC-1 ·** El `README.md` (sección "Posibles adiciones futuras", líneas ~269-278) lista los
  **campos de hardware** (RAM/CPU/almacenamiento) como "adición futura pendiente de aprobación",
  pero `hoja-de-ruta.md` (Fase 2) los marca **entregados** y `modelo-datos.md` /
  `frontend/API_CONTRACT.md` ya los incluyen. → El texto del README está obsoleto; actualizarlo.
- **DOC-2 ·** **Número de pruebas inconsistente** entre documentos: 103
  (`README.md`/`arquitectura.md`/`guia-desarrollo.md`) vs 45 (`verificacion-cumplimiento.md §2`) vs
  43 (`guia-implementacion.md §3`) vs 51 (`cumplimiento-owasp.md`, A08), además de los apéndices
  63/75/103. → Unificar al valor real vigente y fechar la verificación.
- **DOC-3 ·** `manual-uso-ilustrado.md §8` describe la auditoría como "registro inmutable de solo
  anexado", afirmación que **hoy no tiene respaldo técnico** (ver SEC-9). → Matizar el texto ("registro
  de solo anexado a nivel de aplicación") o implementar la evidencia de manipulación de SEC-9.

---

## Fuera de alcance / decisiones registradas

- **LDAP / AD / OIDC:** **excluido** por indicación expresa del usuario para este análisis; ya
  diferido en `hoja-de-ruta.md` (Fase 4).
- **Auditoría en tiempo real (WebSocket)** y **GeoIP:** la propia `hoja-de-ruta.md` los marca ⚠️ de
  bajo ROI; se registran aquí como **no recomendados por ahora** (la alternativa barata para la
  auditoría en vivo es el auto-refresco de la vista).

---

## Matriz consolidada de priorización

| Prioridad → / Esfuerzo ↓ | S (horas) | M (días) | L (semanas) |
|---|---|---|---|
| 🔴 **Alta** | SEC-3, SEC-4, SEC-5, ESC-2, OPS-1, OPS-4 | SEC-1, SEC-2, ESC-1, CAL-4, OPS-3 | CAL-1 |
| 🟠 **Media** | SEC-6, SEC-7, SEC-8, ESC-3, ESC-4, ESC-7, OPS-5, OPS-6, OPS-7 | SEC-10, ESC-5, ESC-6, ESC-9, CAL-2, CAL-3, CAL-5, OPS-8 | SEC-9, SEC-11, ESC-8, OPS-2 |
| 🟡 **Baja** | ESC-10, SEC-12 (parcial) | OPS-9 | — |

**Recomendación:** ejecutar primero la **casilla 🔴/S** (alto impacto, bajo coste y bajo riesgo de
regresión), que cierra los huecos de seguridad y correctitud más urgentes sin refactores; después la
**🔴/M** (criptografía y migraciones); y reservar **CAL-1** (capa de servicios, 🔴/L) como refactor
transversal que debe planificarse con cuidado porque toca las dos superficies HTTP a la vez.

---

*Documento de análisis; no modifica el comportamiento del sistema. Las evidencias `archivo:línea`
corresponden al estado del repositorio en el momento del análisis y deben reconfirmarse antes de
implementar cada mejora.*
