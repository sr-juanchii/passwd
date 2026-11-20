# Notas de la versión 1.3.0

| | |
|---|---|
| **Versión** | 1.3.0 |
| **Etiqueta** | `v1.3.0` |
| **Fecha** | 2026-11-20 |
| **Versión anterior** | 1.2.1 (2026-11-17) |
| **Tipo (SemVer)** | MENOR — funcionalidad nueva retrocompatible, más endurecimiento de la auditoría |
| **Fase de la hoja de ruta** | Fase 9 (parcial: puntos 1 y 3) |
| **Migración de datos** | `0010` (aditiva) |
| **Compatibilidad** | API `/api/v1` sin cambios; variables de entorno anteriores aceptadas |
| **Pre-release** | `v1.3.0-rc.1`, publicado para pruebas funcionales |

El registro completo, entrada por entrada, está en [`CHANGELOG.md`](../CHANGELOG.md). Este
documento cataloga los cambios, explica qué hacer al actualizar y deja constancia de cómo se
verificó la versión.

> **Lo que cambia de verdad en esta versión:** cambiar la contraseña de una credencial del
> inventario deja de ser una edición y pasa a ser un acto gobernado por dos personas, con motivo,
> autorización y rastro permanente. Si solo lee un apartado, lea el 2.

## 1. Catálogo de cambios

Cada cambio lleva un identificador para poder citarlo en revisiones y auditorías.

### Gobernanza de rotación

| ID | Cambio | Dónde |
|---|---|---|
| ROT-01 | Ciclo de tres estados `SOLICITADA → AUTORIZADA → CERRADA` con **motivo obligatorio** para cambiar la contraseña de una credencial del inventario. | `app/servicios/rotacion.py` |
| ROT-02 | **Regla de dos pares**: nadie autoriza la rotación que pidió. | ídem |
| ROT-03 | El autorizador se **reautentica con aplicación autenticadora**. El código por correo no sirve: un buzón puede estar compartido o abierto en la misma sesión, así que no acredita a una segunda persona. | `app/servicios/rotacion.py`, `app/api_web/rotacion.py` |
| ROT-04 | **Libro mayor** `rotaciones_credencial`: asiento permanente con la antigüedad de la contraseña al solicitar, al autorizar y al rotar, y la desviación respecto a la fecha que marcaba la política. | `app/models.py`, migración `0010` |
| ROT-05 | **Vía de emergencia acotada**: con un solo administrador disponible, el solicitante puede autorizar su propia solicitud dentro de una ventana corta. Queda marcada de forma imborrable, alerta a todos los administradores y exige revisión posterior de otro administrador. | `app/servicios/rotacion.py` |
| ROT-06 | **Panel de rotación** (`/rotacion`): pendientes de autorizar, autorización en lote, pendientes de aplicar y emergencias por revisar. Línea de tiempo de gobernanza en la ficha de cada credencial. | `frontend/src/app/(app)/rotacion`, `frontend/src/components/rotacion` |
| ROT-07 | **Reglas de patrón** sobre el libro mayor (tempranas repetidas, fuera de horario, concentración, abuso de la vía de emergencia), en **modo observación** por omisión. | `app/servicios/patrones.py` |
| ROT-08 | Campo **«usada por»** en la credencial: servicios y automatismos que consumen la cuenta, visible al solicitar y al autorizar. | `app/models.py`, `frontend/src/components/rotacion` |
| ROT-09 | Permisos `rotacion.ver`, `rotacion.solicitar`, `rotacion.autorizar` y `rotacion.revisar`. | `app/rbac.py` |
| ROT-10 | Ajustes nuevos: `PASSWD_ROTACION_TEMPRANA_PCT`, `PASSWD_ROTACION_EMERGENCIA_VENTANA_MIN`, `PASSWD_ROTACION_EMERGENCIA_MAX_POR_MES` y `PASSWD_ROTACION_PATRONES_MODO_OBSERVACION`. | `app/config.py`, `app/ajustes.py` |

### Seguridad

| ID | Cambio | Dónde |
|---|---|---|
| SEG-01 | **Bitácora firmada con HMAC-SHA256** y clave `PASSWD_AUDIT_KEY` fuera de la base de datos. El encadenamiento anterior era un SHA-256 sin clave: quien pudiera escribir en la base podía recalcular la cadena entera y reescribir quién hizo qué. El material previo se conserva como **tramo heredado** y `verificar-auditoria` valida ambos tramos e informa del punto de corte. | `app/audit.py`, `app/cli.py` |
| SEG-02 | Un registro **sin firmar después del punto de corte** se trata como cadena rota: la firma no se puede degradar reescribiendo filas con el algoritmo público. | `app/audit.py` |
| SEG-03 | **Punto único de escritura** de `Credencial.password_cifrada`. Había tres caminos que la escribían con lógica duplicada (formulario clásico, API JSON e importación CSV); un circuito de autorización en uno solo no habría sido un control. Una prueba de arquitectura falla si alguno vuelve a hacerlo por su cuenta. | `app/servicios/rotacion.py`, `tests/` |
| SEG-04 | La **verificación del segundo factor** tiene ya límite de tasa por usuario también en la interfaz clásica; antes solo lo aplicaba la API JSON. | `app/servicios/autenticacion.py` |
| SEG-05 | Un **código de enrolamiento incorrecto cuenta para el bloqueo** de la cuenta en la interfaz clásica; antes solo se auditaba. | ídem |
| SEG-06 | Una cuenta con **segundo factor por correo ya puede iniciar la auto-recuperación**. Antes se le exigía un secreto TOTP que esas cuentas no tienen y quedaba atrapada en un desafío imposible, aun teniendo códigos de recuperación válidos. | ídem |
| SEG-07 | **Aviso de arranque con menos de dos administradores activos**: la regla de dos pares no se puede aplicar y toda rotación caería por la vía de emergencia. Los manuales lo afirmaban sin que existiera. | `app/main.py` |

### Estructura y calidad

| ID | Cambio | Dónde |
|---|---|---|
| EST-01 | Capa **`app/servicios/`** con los casos de uso de rotación, reautenticación, patrones, **credenciales** y **autenticación completa** (login por etapas, cambio de contraseña, segundo factor por ambos métodos, auto-recuperación y cierre de sesión). Los controladores pasan a traducir HTTP ↔ servicio. | `app/servicios/` |
| EST-02 | **El login deja de estar escrito dos veces.** CSRF de doble cookie, límite por IP, comparación en tiempo constante y *rehash* oportunista vivían duplicados en los dos controladores. | `app/servicios/autenticacion.py` |
| EST-03 | **La entrega de una contraseña en claro deja de estar escrita dos veces.** Control de acceso por objeto, límite anti-exfiltración y auditoría estaban duplicados línea por línea; mantenerlos sincronizados a mano es lo que falló en la 1.2.0. | `app/servicios/credenciales.py` |
| EST-04 | **Matriz de permisos generada del registro de rutas.** Cada dependencia de autorización declara el permiso que exige; añadir un endpoint sin declarar su política —un permiso RBAC o una exención con su motivo escrito— hace fallar la suite. | `app/deps.py`, `app/api_web/deps.py`, `tests/rutas.py` |
| EST-05 | **Pruebas de navegador en CI** (Playwright) contra backend, frontend compilado para producción y un receptor SMTP local: acceso, expiración de sesión, segundo factor por **ambos** métodos, configuración, exportación y el **ciclo completo de rotación**. Sin endpoints de prueba en la aplicación. | `frontend/e2e/`, `scripts/buzon_pruebas.py` |
| EST-06 | La política de versionado admite **pre-releases** (`X.Y.Z-rc.N`), y `GET /healthz` los expone: quien prueba sabe siempre qué está corriendo. | `docs/versionado.md`, `.github/workflows/prelanzamiento.yml` |

### Avisos de retirada (la 2.0 no romperá nada sin avisar antes)

| ID | Cambio | Dónde |
|---|---|---|
| RET-01 | **La interfaz clásica (HTML) se retira en la 2.0.** Sus respuestas llevan `Deprecation: true` y un `Link` a la documentación, y sus páginas muestran un aviso. `/api/web`, `/api/v1` y los estáticos **no** se marcan: siguen vivos. | `app/main.py`, `app/templates/base.html` |
| RET-04 | **`PASSWD_SMTP_TLS`, y `PASSWD_NOTIFY_ENABLED` como origen de `PASSWD_SMTP_ENABLED`**, dejan de heredarse en la 2.0. El arranque avisa solo cuando esa herencia decide de verdad, y pide definir la variable nueva en vez de sustituir la antigua: `NOTIFY_ENABLED` conserva su significado propio. | `app/config.py`, `app/main.py` |
| RET-07 | **`/api/v1/inventario` paginará siempre y excluirá por omisión los activos restringidos** en la 2.0. El aviso va por registro y documentación, **no por el cuerpo de la respuesta**: añadir una clave rompería a un cliente con validación estricta de esquema. | `app/routes/api.py`, `docs/referencia-api-rest.md` |

## 2. Cambios de comportamiento que conviene conocer

1. **El formulario de edición de una credencial ya no cambia la contraseña.** En su lugar se
   solicita una rotación con motivo, otro administrador la autoriza y se registra después la
   contraseña que quedó aplicada en el activo. El resto de campos se siguen editando igual.
2. **Hacen falta dos administradores activos.** Con uno solo, la regla de dos pares no se puede
   aplicar: toda rotación cae por la vía de emergencia, queda marcada, alerta a los
   administradores y espera revisión. El arranque lo avisa.
3. **El código por correo no sirve para autorizar una rotación**, aunque sea el segundo factor
   habitual de esa cuenta. Hace falta aplicación autenticadora.
4. **La bitácora pasa a firmarse con HMAC.** Defina `PASSWD_AUDIT_KEY` por entorno: si no, se
   autogenera y se avisa, y una clave que cambie invalida la verificación del tramo firmado.
5. **Los registros anteriores no se refirman.** Quedan como tramo heredado, verificable con el
   algoritmo antiguo; `verificar-auditoria` informa del punto de corte.
6. La importación CSV y la interfaz clásica **ya no escriben contraseñas del inventario por su
   cuenta**: delegan en el servicio de rotación. Un intento sin autorización vigente se rechaza
   con 409 y queda auditado.
7. **Avisos de retirada**: si usa la interfaz clásica o las variables obsoletas, empezará a verlo
   en las cabeceras, en las páginas y en el arranque. Nada deja de funcionar en la serie 1.x.

## 3. Actualización desde la 1.2.0

1. Haga un respaldo cifrado (`python -m app.cli respaldo …`).
2. **Defina `PASSWD_AUDIT_KEY`** por entorno antes de arrancar, y custódiela como el resto de
   claves. Si no la define, se autogenera y el arranque lo avisa.
3. Despliegue la versión `v1.3.0` (backend y frontend a la vez: comparten contrato).
4. Aplique el esquema: `alembic upgrade head` (revisión `0010`, aditiva). En el despliegue por
   contenedor las columnas se añaden solas al arrancar.
5. **Compruebe que hay al menos dos administradores activos.** Si no, créelos antes de que nadie
   necesite rotar (ver [`manual-administrador.md`](manual-administrador.md) §4 bis).
6. Avise a quien gestione credenciales de que la contraseña ya no se cambia editando la ficha.
7. Verifique la bitácora: `python -m app.cli verificar-auditoria`. Debe reconocer el tramo
   heredado y el firmado, e informar del punto de corte sin reportar rotura.
8. Compruebe `GET /healthz` → `"version": "1.3.0"`.

**Vuelta atrás:** la migración `0010` es reversible (`alembic downgrade 0009`), pero se perdería
el libro mayor de rotaciones, que es evidencia de auditoría. Respáldelo antes. Los registros
firmados con HMAC dejarían de verificarse con la 1.2.0, que solo conoce el algoritmo antiguo.

## 4. Verificación de la versión

| Comprobación | Resultado |
|---|---|
| Pruebas del backend (`pytest`) | 393 superadas |
| Análisis estático (`ruff`) | sin hallazgos |
| Frontend: tipos, compilación y pruebas unitarias | correctos (21 pruebas) |
| Frontend: linter | sin errores; 18 avisos de un tipo que ya existía |
| Recorrido en navegador (backend + frontend + SMTP simulado) | 29 de 29 |
| Versión en caliente (`GET /healthz`) | `1.3.0` |
| Cadena de auditoría (`verificar-auditoria`) | tramo heredado y tramo firmado reconocidos, sin rotura |

El recorrido en navegador cubrió: primer acceso forzado, contraseña temporal de un solo uso,
indistinguibilidad entre usuario inexistente y contraseña incorrecta, guarda del segundo factor,
rechazo de código TOTP reutilizado, código de recuperación de un solo uso, alta y verificación del
segundo factor **por correo**, RBAC de un operador, restablecimiento del MFA por un administrador,
aviso y extensión de sesión, cierre por inactividad con regreso a la página de origen,
configuración que manda en otra pantalla sin reiniciar, exportación en claro con confirmación y
registro en auditoría, y el **ciclo completo de rotación**: solicitud con motivo, rechazo del
intento de autorizar la propia solicitud, autorización del segundo administrador con
reautenticación TOTP y cierre sin marca de emergencia.

Antes de publicar se liberó el pre-release **`v1.3.0-rc.1`** para pruebas funcionales.

## 5. Limitaciones conocidas

- La **rotación es manual**: el sistema gobierna la decisión y deja el rastro, pero no cambia la
  contraseña en el activo. Los agentes que la apliquen son trabajo posterior
  ([`plan-rotacion-agentes.md`](plan-rotacion-agentes.md)).
- Las **reglas de patrón** están en modo observación: registran, no bloquean.
- La **interfaz clásica (Jinja)** sigue existiendo, ya con aviso de retirada. La 2.0 la elimina.
- La exportación **no pide reautenticación** (solo límite de tasa y aviso).
- Las **notas del vault personal** siguen sin cifrar, y el vault **no entra** en el ciclo de
  gobernanza: es un almacén privado, no inventario.
- El CSV del inventario no neutraliza fórmulas: hacerlo rompería la reimportación de contraseñas
  que empiezan por `=`.
- El **manual operativo** y sus capturas describen la 1.1.0.
- El shell del frontend tiene dos defectos de accesibilidad conocidos: dos elementos `<main>`
  anidados y una barra lateral de navegación sin landmark `nav`.
- Quedan avisos de seguridad en **herramientas de desarrollo** del frontend, que no forman parte
  de lo desplegado.

Todas están recogidas en la [hoja de ruta](hoja-de-ruta.md).
