# Notas de la versión 1.2.0

| | |
|---|---|
| **Versión** | 1.2.0 |
| **Etiqueta** | `v1.2.0` |
| **Fecha** | 2026-11-14 |
| **Versión anterior** | 1.1.0 (2026-07-29) |
| **Tipo (SemVer)** | MENOR — funcionalidad nueva retrocompatible, más una corrección de seguridad |
| **Fase de la hoja de ruta** | Fase 8 |
| **Migración de datos** | `0009` (aditiva) |
| **Compatibilidad** | API `/api/v1` sin cambios; variables de entorno anteriores aceptadas |

El registro completo, entrada por entrada, está en [`CHANGELOG.md`](../CHANGELOG.md). Este
documento cataloga los cambios, explica qué hacer al actualizar y deja constancia de cómo se
verificó la versión.

## 1. Catálogo de cambios

Cada cambio lleva un identificador para poder citarlo en revisiones y auditorías.

### Seguridad

| ID | Cambio | Dónde |
|---|---|---|
| SEG-01 | **Fuga corregida**: `POST /api/web/exportar` entregaba a un operador las contraseñas en claro de los activos restringidos a administradores. La decisión vive en un único punto y la exportación es segura por defecto. | `app/exporter.py`, `app/api_web/exporter.py` |
| SEG-02 | La exportación tiene límite de tasa (5 por hora y usuario), alerta al superarlo y aviso de actividad sensible al titular. | `app/exporter.py` |
| SEG-03 | La importación CSV no permite, a quien no puede restringir, crear máquinas virtuales ni credenciales bajo activos restringidos. | `app/importacion.py` |
| SEG-04 | TOTP: se rechaza cualquier código de un paso temporal igual o anterior al último aceptado. | `app/security/mfa.py`, `app/security/segundo_factor.py` |
| SEG-05 | Los fallos durante el alta del segundo factor cuentan para el bloqueo de la cuenta; la verificación tiene límite de tasa propio. | `app/api_web/auth.py` |
| SEG-06 | `recifrar` incluye los secretos guardados en la configuración (contraseña SMTP). | `app/cli.py` |
| SEG-07 | El inicio de sesión muestra mensajes fijos por motivo; deja de mostrar texto libre tomado de la URL. | `frontend/src/app/(auth)/login` |
| SEG-08 | Los errores SMTP se explican sin exponer detalles internos del servidor. | `app/notifications.py` |

### Sesión

| ID | Cambio | Dónde |
|---|---|---|
| SES-01 | Aviso de expiración con cuenta atrás: «Extender sesión» o «Cerrar sesión ahora». | `frontend/src/components/session-guard.tsx` |
| SES-02 | Al vencer, la interfaz se cierra, redirige al inicio de sesión con un mensaje claro y, tras entrar, vuelve a la página de origen. | `frontend/src/lib/session.tsx`, `expiracion.ts` |
| SES-03 | Tratamiento único del 401 en el cliente de la API; las pestañas se sincronizan. | `frontend/src/lib/api.ts` |
| SES-04 | `GET /api/web/session` informa de los plazos y deja de contar como actividad; nuevo `POST /api/web/session/extender`. | `app/api_web/auth.py`, `app/security/sessions.py` |
| SES-05 | El 401 de una sesión vencida lleva `code: "sesion_expirada"` y borra la cookie. | `app/api_web/deps.py` |

### Verificación en dos pasos

| ID | Cambio | Dónde |
|---|---|---|
| MFA-01 | Método elegible por usuario: aplicación autenticadora o código por correo. | `app/security/segundo_factor.py`, `frontend/src/app/(auth)/mfa` |
| MFA-02 | Política del administrador: correo como principal, correo como respaldo y TOTP obligatorio para administradores. | `app/config.py`, `app/ajustes.py` |
| MFA-03 | Una cuenta de correo que deja de poder usarlo debe configurar TOTP, solo tras acreditar sus dos factores. | `app/api_web/auth.py` |
| MFA-04 | Vista «Mi seguridad»: cambio de método y regeneración de códigos de recuperación, con reautenticación. | `app/api_web/cuenta.py`, `frontend/src/app/(app)/cuenta` |
| MFA-05 | Columnas `usuarios.mfa_metodo` y `usuarios.ultimo_totp_paso`. | migración `0009` |

### Configuración y correo

| ID | Cambio | Dónde |
|---|---|---|
| CFG-01 | Consola reorganizada en siete grupos por función, con descripción de cada uno. | `app/ajustes.py`, `frontend/src/app/(app)/configuracion` |
| CFG-02 | Cada ajuste declara de qué depende; la pantalla lo deshabilita y lo explica. | ídem |
| CFG-03 | Validación de formato (host, direcciones, emisor) y de coherencia entre ajustes. | `app/ajustes.py` |
| CFG-04 | Interruptor propio del servicio de correo (`PASSWD_SMTP_ENABLED`). | `app/config.py`, `app/notifications.py` |
| CFG-05 | Modo de cifrado `PASSWD_SMTP_SECURITY`: `starttls`, `ssl` (puerto 465) o `ninguna`. | ídem |
| CFG-06 | «Probar conexión» con los valores del formulario sin guardar; panel «Estado del correo». | `app/api_web/configuracion.py` |
| CFG-07 | Editables en pantalla: respaldo y validez del código por correo, avisos a usuarios y preaviso de rotación. | `app/ajustes.py` |
| CFG-08 | Mantenimiento periódico cada 6 h: la retención de auditoría surte efecto sin reiniciar. | `app/main.py` |
| CFG-09 | La CLI (`respaldo`, `avisar-rotacion`) aplica los ajustes guardados; el respaldo los incluye junto con el método de segundo factor. | `app/cli.py`, `app/backup.py` |

### Correcciones

| ID | Cambio |
|---|---|
| COR-01 | La interfaz quedaba aparentemente abierta, mostrando «No autenticado», tras caducar la sesión. |
| COR-02 | El diálogo de restablecer contraseña mostraba una contraseña vacía cuando el correo sí se enviaba. |
| COR-03 | El texto «Mínimo 12 caracteres» ignoraba la longitud mínima configurada. |
| COR-04 | El código por correo podía enviarse dos veces al abrir la verificación. |

## 2. Cambios de comportamiento que conviene conocer

1. **`PASSWD_NOTIFY_ENABLED` ya no apaga todo el correo.** Controla solo las alertas a
   administradores. El servicio se enciende con `PASSWD_SMTP_ENABLED`, que hereda el valor de
   `NOTIFY_ENABLED` si no se define; un ajuste guardado en la consola se migra una sola vez al
   arrancar. Una instalación que ya enviaba correo lo sigue haciendo.
2. **El correo como método principal de segundo factor viene permitido** para los no
   administradores cuando el servicio de correo está activo. Es un factor más débil que la
   aplicación autenticadora. Para no ofrecerlo: `PASSWD_EMAIL_OTP_PRIMARY_ENABLED=false` o
   Configuración → Verificación en dos pasos.
3. **`PASSWD_SMTP_TLS` queda obsoleta** (se sigue aceptando) en favor de `PASSWD_SMTP_SECURITY`.
4. **`ACTIVITY_THROTTLE_SECONDS` deja de editarse en pantalla**; si había un valor guardado en
   la consola se ignora y rige el de entorno, acotado a la mitad de la ventana de inactividad.
5. **Consultar `GET /api/web/session` ya no prolonga la sesión.** Un cliente propio que la
   usara como «latido» debe llamar a `POST /api/web/session/extender`.
6. **La exportación está limitada** a 5 por hora y usuario.
7. Un usuario con método «correo» que pierda sus códigos de recuperación **no puede
   autorrecuperar la contraseña**: debe acudir al administrador.

## 3. Actualización desde la 1.1.0

1. Haga un respaldo cifrado (`python -m app.cli respaldo …`).
2. Despliegue la versión `v1.2.0` (backend y frontend a la vez: comparten contrato).
3. Aplique el esquema: `alembic upgrade head` (revisión `0009`). En el despliegue por
   contenedor la columna se añade sola al arrancar.
4. Revise en **Configuración** el grupo «Servidor de correo (SMTP)»: el panel «Estado del
   correo» debe decir *operativo* si antes enviaba correo. Use «Probar conexión».
5. Decida la política del segundo factor (punto 2 del apartado anterior).
6. Compruebe `GET /healthz` → `"version": "1.2.0"`.

**Vuelta atrás:** la migración `0009` es reversible (`alembic downgrade 0008`), pero los
usuarios que hayan elegido el correo como método quedarían sin segundo factor utilizable en la
1.1.0; reinicie su verificación en dos pasos antes de retroceder.

## 4. Verificación de la versión

| Comprobación | Resultado |
|---|---|
| Pruebas del backend (`pytest`) | 289 superadas; 60 de ellas nuevas en esta versión |
| Análisis estático (`ruff`) | sin hallazgos |
| Frontend: tipos, compilación y pruebas unitarias | correctos (21 pruebas) |
| Frontend: linter | sin errores; 18 avisos de un tipo que ya existía |
| Recorrido en navegador (backend + frontend + SMTP simulado) | 32 de 32 comprobaciones |

El recorrido en navegador cubrió: aviso de expiración y extensión, cierre y redirección al
vencer, cierre simultáneo de otra pestaña, regreso a la página de origen, alta y acceso con
código por correo, veto del correo para administradores, dependencias y pruebas de la consola
de configuración, y exportación sin activos restringidos para un operador.

## 5. Limitaciones conocidas

- La **interfaz clásica (Jinja)** sigue existiendo y solo enrola TOTP; comparte con la API la
  exportación, la importación y la comprobación del segundo factor. Su retirada está planificada.
- La exportación **no pide reautenticación** (solo límite de tasa y aviso).
- Las **notas del vault personal** siguen sin cifrar.
- El CSV del inventario no neutraliza fórmulas: hacerlo rompería la reimportación de
  contraseñas que empiezan por `=`.
- El **manual operativo** y sus capturas describen la 1.1.0; este documento cubre las novedades.

Todas están recogidas en la [hoja de ruta](hoja-de-ruta.md).
