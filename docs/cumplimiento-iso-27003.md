# Alineación con ISO/IEC 27003 (guía de implementación del SGSI)

ISO/IEC 27003 es la **guía de orientación para implementar un Sistema de Gestión de
Seguridad de la Información (SGSI)** conforme a las cláusulas 4 a 10 de ISO/IEC 27001.
Un SGSI es, por definición, un sistema de gestión de la organización: ningún software lo
"cumple" por sí solo. Este documento describe **cómo esta aplicación materializa la
orientación de ISO/IEC 27003 dentro de su alcance** (gestión de credenciales de servidores)
y qué evidencia aporta a cada cláusula, además del mapeo a los controles del Anexo A de
ISO/IEC 27001:2022 que implementa técnicamente.

## Cláusulas 4–10 (orientación ISO/IEC 27003)

| Cláusula | Orientación 27003 | Aporte de este sistema |
|---|---|---|
| 4. Contexto de la organización | Determinar alcance, partes interesadas y activos | El inventario relacional delimita con precisión los activos en alcance: servidores físicos, hipervisores y máquinas virtuales, con su función documentada (`app/models.py`). Roles definidos identifican a las partes que interactúan (admin/operador/auditor). |
| 5. Liderazgo y política | Política de seguridad y asignación de roles y responsabilidades | La matriz RBAC (`app/rbac.py`, `docs/` y README) documenta responsabilidades por rol y se aplica en código; la política de contraseñas y MFA queda establecida y forzada técnicamente, no solo declarada. |
| 6. Planificación | Apreciación y tratamiento de riesgos, objetivos medibles | Riesgos típicos del proceso (robo de credenciales, acceso no autorizado, repudio, fuga de la BD) tratados con controles verificables: MFA obligatorio, cifrado en reposo, bloqueo de cuenta, auditoría íntegra. La suite de pruebas (`tests/`) verifica cada control como objetivo medible y repetible. |
| 7. Soporte | Recursos, competencia, concienciación e información documentada | Documentación operativa completa (README, `.env.example`, `docs/`); la interfaz refuerza la concienciación (avisos de auditoría, política visible en formularios); la información documentada del sistema se versiona en este repositorio. |
| 8. Operación | Planificación y control operacional | Controles operados automáticamente: expiración de sesiones, bloqueo por intentos fallidos, retención de bitácora, revocación inmediata de accesos; el arranque aplica mantenimiento (purga de sesiones vencidas y retención de auditoría) sin intervención manual (`app/main.py`). |
| 9. Evaluación del desempeño | Seguimiento, medición, análisis, auditoría interna | Bitácora consultable y filtrable por usuario/acción con paginación (`/auditoria`), apta como evidencia de auditoría interna; el pipeline de CI ejecuta verificación continua (lint, SAST, pruebas) en cada cambio. |
| 10. Mejora | No conformidades y mejora continua | Los eventos `acceso_denegado`, `login_fallido` y `cuenta_bloqueada` permiten detectar desviaciones y ajustar permisos; las pruebas de regresión protegen las correcciones; el historial Git documenta el ciclo de mejora. |

## Controles del Anexo A de ISO/IEC 27001:2022 implementados

| Control | Nombre | Implementación |
|---|---|---|
| A.5.9 | Inventario de información y otros activos | Inventario relacional completo con descripción de función por activo. |
| A.5.15 | Control de acceso | RBAC por rol aplicado en cada ruta, más control de acceso por objeto (concesiones por activo al rol analista), evaluado en cada petición. |
| A.5.16 | Gestión de identidades | Cuentas individuales únicas; sin cuentas compartidas; identidad trazable en cada evento. |
| A.5.17 | Información de autenticación | Contraseñas con Argon2id; temporales de un solo uso con cambio forzado; política contra contraseñas comunes; secretos TOTP cifrados; códigos de recuperación MFA de un solo uso almacenados solo como hash; generador de contraseñas robustas y alertas de rotación para credenciales de activos. |
| A.5.18 | Derechos de acceso | Concesión por rol en el alta y concesión por activo (nivel + caducidad) a analistas; revocación inmediata (desactivación/cambio de rol revoca sesiones; revocar una concesión surte efecto en la siguiente petición). |
| A.8.2 | Derechos de acceso privilegiados | Rol admin separado; MFA obligatorio también para administradores. |
| A.8.3 | Restricción de acceso a la información | El auditor consulta sin revelar contraseñas; el analista solo ve los activos concedidos y solo usa credenciales si su concesión es de nivel «ver_credenciales». |
| A.8.5 | Autenticación segura | Flujo de dos factores (contraseña + TOTP), mensajes genéricos anti enumeración, límite de tasa, bloqueo de cuenta, rotación de token de sesión. |
| A.8.13 | Copia de seguridad de la información | Respaldo cifrado completo por CLI (scrypt + Fernet), portable entre instancias, con restauración verificada por pruebas automatizadas. |
| A.8.15 | Registro de eventos (logging) | Bitácora estructurada e íntegra de autenticación, gestión y acceso a secretos, con IP y agente. |
| A.8.24 | Uso de criptografía | Fernet (AES-CBC + HMAC-SHA256) para secretos en reposo; Argon2id para contraseñas; SHA-256 para tokens de sesión; gestión de claves fuera del repositorio. |
| A.8.26 | Requisitos de seguridad de las aplicaciones | Cabeceras endurecidas (CSP, X-Frame-Options, HSTS), anti-CSRF, cookies seguras, sin documentación de API expuesta. |

## Responsabilidades que permanecen en la organización

Para completar el SGSI conforme a 27003, la institución debe mantener: la política general
aprobada por la dirección, la apreciación formal de riesgos, el plan de tratamiento, la
programación periódica del respaldo cifrado (`python -m app.cli respaldo`) con prueba de
restauración y custodia de la frase fuera de línea, la revisión periódica de la bitácora y
de las cuentas, y la gestión segura de las claves (`PASSWD_SECRET_KEY`,
`PASSWD_ENCRYPTION_KEY`) en un custodio adecuado.
