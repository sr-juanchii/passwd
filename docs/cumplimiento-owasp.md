# Cumplimiento OWASP — Top 10 (2021) y API Security Top 10 (2023)

Mapeo de los riesgos OWASP a las medidas implementadas en este sistema, con su evidencia
en código y la prueba automatizada que lo verifica. Complementa las matrices CIS v8.1 e
ISO/IEC 27000 del directorio `docs/`.

## OWASP Top 10 — 2021

| Riesgo | Medidas implementadas | Evidencia / pruebas |
|---|---|---|
| **A01 — Broken Access Control** | RBAC aplicado en cada ruta por dependencia central (`requiere_permiso`); los rechazos quedan auditados y persisten pese al rollback; CSRF en todo POST; las contraseñas nunca aparecen en listados (solo vía endpoints auditados); cookies `SameSite=Strict`. El acceso a credenciales es por equipo —cualquier admin/operador accede a todo el inventario—, decisión documentada en la matriz de roles. | `app/deps.py`, `app/rbac.py` · `test_auditor_no_puede_revelar_ni_gestionar`, `test_operador_no_gestiona_usuarios_ni_ve_auditoria`, `test_auditor_no_puede_copiar`, `test_editar_sin_csrf_rechazado` |
| **A02 — Cryptographic Failures** | Contraseñas de usuarios: **Argon2id**; secretos de activos y semillas TOTP: **Fernet** (AES-CBC + HMAC-SHA256, IV aleatorio); tokens de sesión: solo **SHA-256** en BD; respaldos: clave derivada por **scrypt**; claves fuera del repositorio (entorno o archivo 0600); HSTS y cookie `Secure` por defecto; respuestas con secretos llevan `Cache-Control: no-store`. | `app/security/passwords.py`, `app/security/crypto.py`, `app/security/sessions.py`, `app/backup.py` · `test_credenciales_en_los_tres_niveles_y_cifrado`, `test_cookie_de_sesion_endurecida` |
| **A03 — Injection** | Todo acceso a datos vía SQLAlchemy ORM con parámetros enlazados (cero SQL crudo); plantillas Jinja2 con autoescape; validación de tipos por FastAPI. | `app/models.py`, `app/routes/` · suite completa ejercita todas las rutas |
| **A04 — Insecure Design** | MFA obligatorio sin excepciones; credencial de arranque de un solo uso; revocación de sesiones al cambiar privilegios; defensa en profundidad (bloqueo de cuenta + límite por IP + límite anti-exfiltración); validaciones de negocio en BD (CHECK) y aplicación. | `test_flujo_completo_password_cambio_y_mfa`, `test_cambio_de_rol_revoca_sesiones`, `test_restriccion_un_solo_activo_por_credencial` |
| **A05 — Security Misconfiguration** | CSP estricta sin código embebido; `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: no-referrer`, `Permissions-Policy`, **COOP/CORP `same-origin`**, `X-Permitted-Cross-Domain-Policies: none`; documentación interactiva de la API deshabilitada; contenedor sin privilegios; puerto solo en loopback. | `app/main.py`, `Dockerfile`, `docker-compose.yml` · `test_cabeceras_de_seguridad`, `test_cabeceras_de_aislamiento_de_origen`, `test_documentacion_api_deshabilitada` |
| **A06 — Vulnerable & Outdated Components** | **pip-audit** en el pipeline de CI contra la base de avisos de PyPA en cada push; dependencias mínimas y acotadas por rango. | `.github/workflows/ci.yml`, `requirements.txt` |
| **A07 — Identification & Authentication Failures** | MFA TOTP obligatorio con anti-replay; códigos de recuperación de un solo uso (solo hash); bloqueo tras 5 fallos; límite de tasa por IP; mensajes genéricos anti-enumeración con verificación de tiempo constante; política de contraseñas; rotación del token de sesión; doble expiración de sesión. | `app/routes/auth.py` · `test_mfa_codigo_reutilizado_rechazado`, `test_bloqueo_de_cuenta_tras_intentos_fallidos`, `test_limite_de_tasa_por_ip`, `test_login_credenciales_invalidas_mensaje_generico`, `test_sesion_expira_por_inactividad` |
| **A08 — Software & Data Integrity Failures** | CI verifica cada cambio (lint + SAST + 51 pruebas); sin dependencias servidas por CDN (todo `'self'`); respaldos autenticados (HMAC de Fernet detecta manipulación). | `.github/workflows/ci.yml` · `test_respaldo_con_frase_incorrecta_rechazado` |
| **A09 — Security Logging & Monitoring Failures** | Bitácora de autenticación (éxito/fallo), bloqueos, gestión de cuentas, CRUD, accesos denegados y **cada acceso a una contraseña** (revelar y copiar por separado), con usuario, IP, agente y resultado; retención mínima 90 días; vista con filtros para roles de supervisión. | `app/audit.py` · `test_revelar_devuelve_la_clave_y_queda_auditado`, `test_copiar_entrega_la_clave_sin_mostrarla_y_queda_auditado`, `test_retencion_de_auditoria` |
| **A10 — SSRF** | No aplica por diseño: el sistema no realiza peticiones salientes a URLs (el QR de MFA se genera localmente). | revisión de código: sin clientes HTTP salientes en `app/` |

## OWASP API Security Top 10 — 2023

| Riesgo | Medidas implementadas | Evidencia / pruebas |
|---|---|---|
| **API1 — Broken Object Level Authorization** | Autorización por permiso en cada endpoint; el alcance por objeto es deliberadamente de equipo (bóveda compartida) y está documentado; 404 sin filtración de existencia para IDs ajenos al inventario. | `app/deps.py` · pruebas RBAC |
| **API2 — Broken Authentication** | Igual que A07: MFA obligatorio, sesiones de servidor revocables, sin tokens autocontenidos. | `tests/test_auth_mfa.py` (18 pruebas) |
| **API3 — Broken Object Property Level Authorization** | Las respuestas de listado/detalle jamás incluyen la contraseña ni su versión cifrada; la entrega es solo por endpoints dedicados, auditados y limitados. | `test_copiar_entrega_la_clave_sin_mostrarla_y_queda_auditado` (verifica ausencia en HTML) |
| **API4 — Unrestricted Resource Consumption** | Límite de tamaño de cuerpo de petición (64 KB por defecto, configurable); límite de tasa en login por IP; **límite de revelados/copiados por usuario**; paginación en auditoría. | `app/main.py` (`LimiteTamanoPeticionMiddleware`) · `test_peticion_demasiado_grande_rechazada`, `test_limite_anti_exfiltracion_de_contrasenas` |
| **API5 — Broken Function Level Authorization** | Funciones administrativas bajo permiso `usuarios.gestionar`; verificación en servidor, nunca solo en la interfaz. | `test_operador_no_gestiona_usuarios_ni_ve_auditoria` |
| **API6 — Unrestricted Access to Sensitive Business Flows** | El flujo sensible (obtener contraseñas) tiene presupuesto por usuario (20 accesos/5 min por defecto): frena la exfiltración masiva incluso con una sesión legítima comprometida, y el exceso queda auditado como evidencia. | `test_limite_anti_exfiltracion_de_contrasenas` |
| **API7 — SSRF** | No aplica (sin peticiones salientes). | — |
| **API8 — Security Misconfiguration** | Ver A05; además sin CORS permisivo (no se habilita CORS: solo mismo origen). | `test_cabeceras_de_seguridad` |
| **API9 — Improper Inventory Management** | Una única aplicación con rutas explícitas; sin versiones antiguas expuestas; `/docs`, `/redoc` y `/openapi.json` deshabilitados. | `test_documentacion_api_deshabilitada` |
| **API10 — Unsafe Consumption of APIs** | No aplica: no se consumen APIs de terceros. | — |

## Manejo de contraseñas sin texto plano en pantalla

Flujo de mínima exposición implementado:

1. **En reposo**: cifradas con Fernet; ni la BD ni los respaldos contienen texto plano.
2. **En listados**: nunca presentes (ni enmascaradas) en el HTML.
3. **Uso normal — «📋 Copiar»**: entrega la contraseña directamente al portapapeles
   **sin mostrarla en pantalla** (anti *shoulder-surfing*); el portapapeles se sobrescribe
   a los 30 segundos (mejor esfuerzo del navegador) y la acción se audita como
   `credencial_copiada`.
4. **Uso excepcional — «Revelar»**: visible 30 segundos con re-ocultado automático,
   auditado como `credencial_revelada`.
5. **Ambas vías comparten el límite anti-exfiltración** por usuario y exigen CSRF + rol
   con permiso `credenciales.revelar` (el auditor no lo tiene).

> Nota: la API moderna de portapapeles requiere contexto seguro (HTTPS); en entornos de
> prueba sin TLS se usa un mecanismo de reserva. Una razón más para el proxy TLS
> obligatorio en producción (guía de implementación §4.3).
