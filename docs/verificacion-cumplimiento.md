# Informe de verificación de cumplimiento — CIS Controls v8.1 y familia ISO/IEC 27000

| Campo | Valor |
|---|---|
| Fecha de verificación | 11/06/2026 |
| Sistema verificado | Gestor de Contraseñas de Servidores v1.0.0 — rama `claude/elegant-shannon-ip3003` |
| Método | Revisión de código + **45 pruebas automatizadas** + verificación dinámica sobre instancia en ejecución + análisis estático de seguridad |
| Resultado global | **CONFORME** en el alcance técnico de la aplicación; quedan ítems organizativos y de despliegue listados en §6 |

## 1. Alcance y método

Se verificó cada salvaguarda declarada en `docs/cumplimiento-cis-v8.1.md` y cada control del
Anexo A declarado en `docs/cumplimiento-iso-27003.md`, con cuatro técnicas:

1. **Pruebas automatizadas** (`pytest`): cada control técnico tiene al menos una prueba que lo ejercita de extremo a extremo.
2. **Verificación dinámica**: instancia real levantada con `uvicorn`; peticiones `curl` y revisión de respuestas.
3. **Análisis estático**: `ruff` (calidad, reglas de seguridad `S`) y `bandit` (SAST).
4. **Revisión de código**: confirmación de la evidencia citada (archivo y mecanismo).

Sobre la nomenclatura «ISO 27000»: ISO/IEC 27000 es la norma de **vocabulario** de la familia y no
contiene requisitos auditables. La verificación se realizó contra los miembros aplicables de la
familia: **ISO/IEC 27001:2022** (requisitos del SGSI: cláusulas 4–10 y Anexo A) con la guía de
implementación **ISO/IEC 27003** y la guía de controles **ISO/IEC 27002**.

## 2. Resultados de las herramientas (evidencia de ejecución)

| Verificación | Comando | Resultado obtenido |
|---|---|---|
| Suite de pruebas | `pytest` | **45 passed**, 0 failed |
| Lint + reglas de seguridad | `ruff check app tests` | **All checks passed** |
| SAST | `bandit -r app --severity-level medium` | **Sin hallazgos** ≥ severidad media (14 avisos *Low* revisados uno a uno: falsos positivos —constantes con nombre de etapa, `assert` de invariantes, valores por defecto `""` de formularios—) |

### Verificación dinámica (instancia real, salidas literales)

```
GET /healthz                  → {"estado":"ok","version":"1.0.0"}
GET /  (sin sesión)           → 303 Location: /login
GET /docs                     → 404      GET /openapi.json → 404
POST /login (sin token CSRF)  → 403

Cabeceras observadas en /login:
  content-security-policy: default-src 'self'; img-src 'self' data:; style-src 'self';
                           script-src 'self'; form-action 'self'; frame-ancestors 'none';
                           base-uri 'self'; object-src 'none'
  x-content-type-options: nosniff
  x-frame-options: DENY
  referrer-policy: no-referrer
  permissions-policy: camera=(), microphone=(), geolocation=()
  strict-transport-security: max-age=31536000; includeSubDomains
  cache-control: no-store

Cookie de sesión emitida tras el primer factor:
  set-cookie: passwd_session=…; HttpOnly; Max-Age=28800; Path=/; SameSite=strict; Secure
```

## 3. Verificación CIS Controls v8.1 (control por control)

Estados: ✅ verificado · 🔶 conforme condicionado al despliegue · 📋 organizativo (fuera del software).

| Salvaguarda | Verificación realizada | Evidencia / prueba | Resultado |
|---|---|---|---|
| 1.1 Inventario de activos | UI y BD reflejan jerarquía físico→hipervisor→VM con descripciones | `test_jerarquia_completa_y_arbol_en_panel` | ✅ |
| 3.3 Control de acceso a datos | Auditor sin revelado ni gestión; operador sin usuarios/auditoría | `test_auditor_no_puede_revelar_ni_gestionar`, `test_operador_no_gestiona_usuarios_ni_ve_auditoria` | ✅ |
| 3.10 Cifrado en tránsito | HSTS activo verificado en vivo; TLS lo termina el proxy del despliegue | Cabecera `strict-transport-security` observada; guía §4.3 | 🔶 |
| 3.11 Cifrado en reposo | Blob en BD ≠ texto plano; descifrado correcto; semilla TOTP cifrada | `test_credenciales_en_los_tres_niveles_y_cifrado`, `test_flujo_completo_password_cambio_y_mfa` | ✅ |
| 3.14 Registro de acceso a datos | Revelado genera evento con usuario e IP | `test_revelar_devuelve_la_clave_y_queda_auditado` | ✅ |
| 4.3 Bloqueo por inactividad | Sesión inválida tras 15 min sin uso y al alcanzar la vida máxima | `test_sesion_expira_por_inactividad`, `test_sesion_expira_por_vida_maxima` | ✅ |
| 4.7 Cuentas por defecto | Credencial de arranque de un solo uso (cambio forzado + MFA) | `test_flujo_completo_password_cambio_y_mfa`, `test_alta_de_usuario_con_clave_temporal_y_primer_acceso` | ✅ |
| 5.2 Contraseñas robustas | Mínimo 12, comunes prohibidas, sin username; generador CSPRNG | `test_password_nueva_debe_cumplir_politica`, `test_generador_disponible_en_formulario` | ✅ |
| 5.3 Cuentas inactivas | Desactivación inmediata con revocación de sesiones | `test_desactivar_usuario_revoca_sus_sesiones` | ✅ (revisión periódica: 📋) |
| 5.4 Privilegios de admin restringidos | Matriz RBAC aplicada en cada ruta | pruebas RBAC de §3.3 + revisión `app/rbac.py` | ✅ |
| 5.6 Gestión centralizada de cuentas | Módulo único auditado | `tests/test_usuarios_auditoria.py` (8 pruebas) | ✅ |
| 6.1 Concesión de acceso | Alta con rol, clave temporal y evento | `test_alta_de_usuario_con_clave_temporal_y_primer_acceso` | ✅ |
| 6.2 Revocación de acceso | Desactivar/cambiar rol revoca sesiones al instante | `test_desactivar_usuario_revoca_sus_sesiones`, `test_cambio_de_rol_revoca_sesiones` | ✅ |
| 6.3/6.4/6.5 MFA (aplicación, remoto, admin) | Ninguna sesión activa sin TOTP; aplica a todos los roles | `test_sesion_pendiente_de_mfa_no_accede_al_inventario`, `test_relogin_con_mfa`, `test_mfa_codigo_incorrecto_rechazado`, `test_mfa_codigo_reutilizado_rechazado` | ✅ |
| 6.7 Control de acceso centralizado | Sesiones en servidor, revocables; logout efectivo | `test_logout_revoca_la_sesion` | ✅ |
| 6.8 RBAC definido y mantenido | Matriz documentada = matriz aplicada | revisión `app/rbac.py` + pruebas RBAC | ✅ |
| 8.1/8.2/8.5 Bitácora detallada | Eventos con fecha, usuario, acción, objeto, IP, agente, resultado | aserciones de auditoría en 6 pruebas distintas | ✅ |
| 8.10 Retención ≥ 90 días | Purga respeta piso de 90 días aunque se configure menos | `test_retencion_de_auditoria` | ✅ |
| 8.11 Revisión de bitácora | Vista con filtros para admin/auditor | `test_auditoria_visible_para_admin_y_auditor_con_filtros` | ✅ (cadencia de revisión: 📋, guía §5.1) |
| 11.1–11.3 Recuperación de datos | Respaldo íntegro, cifrado con frase (scrypt+Fernet), restauración verificada; frase errónea rechazada | `test_respaldo_y_restauracion_completa`, `test_respaldo_con_frase_incorrecta_rechazado` + ejecución CLI en vivo | ✅ |
| 11.4 Copia aislada | Archivo portable; custodia externa | guía §4.7 | 📋 |
| 12.2 Arquitectura segura | Servicio publicado solo en loopback en compose | revisión `docker-compose.yml` | 🔶 (depende del despliegue) |
| 16.1/16.12 Desarrollo seguro / SAST | CI con ruff+bandit+pytest; ejecutados en esta verificación | `.github/workflows/ci.yml` + resultados §2 | ✅ |
| 16.10 Diseño seguro | CSP, CSRF, cookies endurecidas, anti-enumeración, límite de tasa, bloqueo, docs API ocultas | `test_cabeceras_de_seguridad`, `test_login_sin_csrf_rechazado`, `test_editar_sin_csrf_rechazado`, `test_cookie_de_sesion_endurecida`, `test_limite_de_tasa_por_ip`, `test_login_credenciales_invalidas_mensaje_generico`, `test_bloqueo_de_cuenta_tras_intentos_fallidos`, `test_documentacion_api_deshabilitada` + evidencia dinámica §2 | ✅ |

**Controles CIS no aplicables al software** (2, 7, 9, 10, 13, 14, 15, 17, 18): responsabilidad del
entorno y de los procesos institucionales; el sistema aporta inventario y bitácora como insumo.

## 4. Verificación familia ISO/IEC 27000

### 4.1 ISO/IEC 27001:2022 — Anexo A (controles técnicos implementados)

| Control | Verificación | Resultado |
|---|---|---|
| A.5.9 Inventario de activos | pruebas de inventario (jerarquía, unicidad, cascada) | ✅ |
| A.5.15 Control de acceso | pruebas RBAC (403 verificados y auditados) | ✅ |
| A.5.16 Gestión de identidades | cuentas únicas, identidad en cada evento de bitácora | ✅ |
| A.5.17 Información de autenticación | política verificada, temporales de un solo uso, TOTP cifrado, códigos de recuperación solo-hash y un-solo-uso (`test_codigos_de_recuperacion_un_solo_uso`) | ✅ |
| A.5.18 Derechos de acceso | concesión por rol y revocación inmediata verificadas | ✅ |
| A.8.2 Accesos privilegiados | rol admin separado; MFA también para admin | ✅ |
| A.8.3 Restricción de acceso a la información | auditor sin revelado (`test_auditor_no_puede_revelar_ni_gestionar`) | ✅ |
| A.8.5 Autenticación segura | flujo 2FA completo + bloqueo + tasa + anti-enumeración | ✅ |
| A.8.13 Copias de seguridad | respaldo/restauración cifrados verificados (pruebas + CLI en vivo) | ✅ |
| A.8.15 Registro de eventos | bitácora íntegra; persiste incluso en peticiones denegadas | ✅ |
| A.8.24 Criptografía | Argon2id, Fernet, SHA-256 de tokens, scrypt para respaldo; claves fuera del repositorio (revisión `app/security/`) | ✅ |
| A.8.26 Seguridad en aplicaciones | cabeceras y CSRF verificados dinámicamente (§2) | ✅ |

### 4.2 ISO/IEC 27001 cláusulas 4–10 (SGSI) con guía ISO/IEC 27003

El SGSI es un sistema de gestión **organizacional**: el software no lo certifica por sí solo.
Estado verificado del aporte documental: contexto y activos (✅ inventario), roles y
responsabilidades (✅ RBAC + matriz en guía §5.4), tratamiento de riesgos técnicos (✅ controles
verificados arriba), información documentada (✅ README + 5 documentos en `docs/`), operación
(✅ controles automáticos), evaluación del desempeño (✅ bitácora consultable + CI), mejora
(✅ pruebas de regresión + eventos de desviación). **Pendiente organizativo**: política aprobada
por la dirección, apreciación formal de riesgos y auditoría interna del SGSI (§6).

### 4.3 ISO/IEC 27000

Norma de vocabulario y visión general: sin requisitos verificables. La terminología de la
documentación del proyecto es consistente con ella.

## 5. Hallazgos de la verificación

| # | Hallazgo | Severidad | Tratamiento |
|---|---|---|---|
| H-1 | El cifrado en tránsito (CIS 3.10) depende del proxy TLS del despliegue; la aplicación no termina TLS por sí misma | Media (diseño esperado) | Mitigado por diseño (HSTS + cookie `Secure` por defecto) y por la guía de implementación §4.3, que lo hace **obligatorio** en producción |
| H-2 | Detrás de un proxy, la bitácora registraría la IP del proxy y no la del cliente | Baja | Resuelto documentalmente: guía §4.3 indica `--proxy-headers --forwarded-allow-ips` |
| H-3 | 14 avisos *Low* de bandit | Informativa | Revisados individualmente: falsos positivos (constantes de etapa/acción, `assert` internos, defaults de formulario); el umbral de CI queda en «media» |
| H-4 | CIS 4.3 carecía de prueba automatizada específica | Baja | **Corregido durante esta verificación**: se añadieron `test_sesion_expira_por_inactividad` y `test_sesion_expira_por_vida_maxima` (suite pasa de 43 a 45) |

## 6. Ítems que permanecen fuera del software (para el cierre del cumplimiento)

1. Publicar detrás de TLS según guía §4.3 y custodiar claves/frase según §4.4 (despliegue).
2. Programar el respaldo (cron §4.7) y ejecutar la prueba de restauración trimestral (CIS 11 / A.8.13).
3. Formalizar: política de seguridad aprobada, apreciación de riesgos, cadencia de revisión de la
   bitácora y de cuentas (guía §5.1), y auditoría interna del SGSI (ISO 27001 cl. 9.2).
4. Mantener el anfitrión bajo gestión de parches y monitoreo institucional (CIS 7/13).

## 7. Conclusión

Todos los controles **técnicos** declarados en las matrices de cumplimiento fueron verificados con
resultado satisfactorio (45/45 pruebas, SAST limpio, evidencia dinámica conforme). El sistema está
**apto para la fase de pruebas** descrita en `docs/guia-implementacion.md` §3 y, condicionado a los
ítems de despliegue y organizativos del §6, **apto para producción** según §4 de la misma guía.

**Re-verificación**: repetir §2 de este informe (tres comandos + smoke test dinámico) tras cada
actualización y al menos trimestralmente; el pipeline de CI lo automatiza en cada cambio.

## Apéndice — Adición posterior: control de acceso por objeto (14/06/2026)

Se incorporó el rol **analista** y las **concesiones de acceso por activo** (ver
`docs/control-acceso.md`), reforzando CIS 3.3/6.8 y OWASP A01/API1 (BOLA) con autorización a
nivel de objeto (default-deny, 404 sin filtrar existencia, sin herencia, caducidad opcional,
revocación inmediata). Verificado con **10 pruebas nuevas** de aislamiento (`tests/test_accesos.py`):
analista sin concesión, niveles ver / ver+credenciales, activo ajeno → 404, revocación,
caducidad, ausencia de herencia, upsert y exclusividad de gestión por el admin; más regresión de
acceso total de operador. **Suite total: 63/63 en verde**, ruff y bandit (≥media) sin hallazgos,
`pip-audit` sin vulnerabilidades.
