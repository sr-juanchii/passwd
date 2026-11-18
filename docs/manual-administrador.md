# Manual del administrador

**Sistema:** Gestor de Contraseñas de Servidores
**Audiencia:** personas con rol **admin** (y, donde se indica, **auditor**).
**Alcance:** las tareas de administración del día a día desde la interfaz. Para la **instalación**
y el **despliegue** consulte [`guia-implementacion.md`](guia-implementacion.md); para el uso general
del inventario y las credenciales, el [`manual-usuario.md`](manual-usuario.md).

> El administrador es el único rol que gestiona usuarios, concede/revoca accesos por activo y
> administra los tokens de API. El auditor puede ver la bitácora y las métricas, pero no revela
> contraseñas ni gestiona el inventario.

---

## 1. Gestión de usuarios

Menú **Usuarios** (requiere `usuarios.gestionar`, solo admin).

### 1.1 Crear un usuario

1. **Usuarios → + Usuario**.
2. Indique **usuario**, **correo**, **nombre completo** y **rol** (admin, operador, auditor o
   analista).
3. Al guardar, el sistema genera una **contraseña temporal de un solo uso** y la muestra una vez.
   Entréguesela al usuario por un canal seguro.
4. En su primer acceso, el usuario pasará por el circuito obligatorio: **cambio de contraseña +
   enrolamiento MFA + códigos de recuperación** (ver [`manual-usuario.md`](manual-usuario.md) §2).

### 1.2 Acciones sobre una cuenta

| Acción | Efecto |
|---|---|
| **Cambiar rol** | Actualiza el rol y **revoca al instante** todas las sesiones vivas del usuario. |
| **Desactivar** | El usuario no puede entrar; sus sesiones se revocan inmediatamente. La cuenta se conserva (para la auditoría). |
| **Reactivar** | Vuelve a permitir el acceso. |
| **Restablecer contraseña** | Emite una nueva **contraseña temporal** y fuerza su cambio; desbloquea la cuenta. |
| **Reiniciar MFA** | Borra el segundo factor: el usuario re-enrola MFA en su próximo acceso y se le emiten **nuevos códigos de recuperación**; revoca sesiones. |

> **Baja de personal:** desactive la cuenta (corta el acceso de inmediato) y **rote las
> credenciales de los activos** que esa persona pudo haber revelado. La bitácora permite filtrar
> los eventos `credencial_revelada` por usuario para saber cuáles.

### 1.3 Incidentes de acceso frecuentes

| Situación | Procedimiento |
|---|---|
| Cuenta bloqueada (5 intentos) | Esperar 15 min, o **Restablecer contraseña** (desbloquea y emite temporal). |
| Dispositivo MFA perdido | El usuario entra con un **código de recuperación**; si no le quedan, **Reiniciar MFA**. |
| Códigos de recuperación agotados | **Reiniciar MFA** → nuevo juego al re-enrolar. |
| Olvido de contraseña | **Restablecer contraseña** → temporal de un solo uso. |

---

## 2. Roles y control de acceso por objeto

Los cuatro roles y la matriz de permisos están en [`control-acceso.md`](control-acceso.md). Aquí lo
operativo del rol **analista** (*default-deny*: no ve nada hasta que se le concede acceso).

### 2.1 Conceder acceso a un analista

1. Cree el usuario con rol **analista** (§1.1).
2. Abra el **detalle del activo** (servidor físico, hipervisor, VM o dispositivo de red). Al
   final verá el panel **«Accesos de analistas»** (en el frontend, la pestaña/sección de accesos).
3. Elija el analista, el **nivel** y, si procede, los **días de caducidad**; pulse **Conceder**.
   - **Ver** — ve el activo y la lista de credenciales (usuario, servicio, puerto, descripción),
     **sin** las contraseñas.
   - **Ver credenciales** — además puede **revelar/copiar** las contraseñas de ese activo.
4. Para retirar el acceso, pulse **Revocar** en la fila correspondiente (efecto inmediato).

### 2.2 Reglas que conviene recordar

- **Sin herencia:** conceder un servidor físico no da acceso a sus hipervisores ni VMs (ni a los
  dispositivos de red); cada activo se concede por separado.
- **Default-deny:** sin concesión vigente, el analista recibe **404** (ni siquiera se filtra la
  existencia del activo).
- **Caducidad:** al vencer `expira_en`, la concesión deja de surtir efecto automáticamente.
- La traza de quién concedió/revocó qué y cuándo vive en la **bitácora** (`acceso_concedido` /
  `acceso_revocado`).

### 2.3 Ocultar activos a los operadores (restringir)

Mientras las concesiones **abren** acceso a un analista, la marca **restringido** lo **cierra**
para los operadores. Úsela con los activos más sensibles (p. ej. los servidores de dirección o
seguridad) que solo la administración debe manejar.

1. Al crear o editar un servidor físico, hipervisor o dispositivo de red, marque la casilla
   **«Restringir a administradores»** (solo visible para administradores).
2. Efecto inmediato:
   - El **operador** deja de ver el activo por completo: no aparece en el inventario, la
     búsqueda ni la exportación, y su detalle responde **404**. Tampoco puede gestionar ni
     revelar sus credenciales o notas.
   - El **auditor sí lo ve** (para su labor de supervisión) pero, como siempre, **no revela
     contraseñas**.
   - Un **analista** solo lo ve si usted le concede acceso explícito (la concesión prevalece
     sobre la restricción).
   - Si restringe un **hipervisor**, sus **máquinas virtuales** quedan igualmente ocultas.
3. Para volver a hacerlo visible, desmarque la casilla. Cada cambio queda auditado
   (`activo_restriccion_cambiada`).

---

## 3. Auditoría (bitácora)

Menú **Auditoría** (requiere `auditoria.ver`: admin y auditor).

- **Filtros** por usuario y por acción; **paginación** de 50 registros.
- Cada registro incluye: fecha (UTC), usuario, acción, tipo y ID de objeto, detalle, IP, agente y
  resultado (éxito/fallo).
- **Exportar CSV:** botón de exportación; descarga el conjunto **filtrado**. La exportación se
  audita y las celdas se sanean contra **inyección de fórmulas** (Excel/Sheets).

Acciones típicas a vigilar (revisión semanal recomendada, ver
[`guia-implementacion.md`](guia-implementacion.md) §5.1): `login_fallido`, `cuenta_bloqueada`,
`acceso_denegado`, `credencial_revelada`/`credencial_copiada` inusuales y `revelado_tasa_excedida`.

> La retención por defecto es de 365 días y **nunca baja de 90** aunque se configure menos
> (CIS 8.10). Se purga automáticamente al arrancar la aplicación.

**Cadena firmada (desde la 1.3.0).** Cada registro encadena con el anterior y se firma con
HMAC-SHA256 usando `PASSWD_AUDIT_KEY`, que vive fuera de la base de datos. Antes el encadenamiento
era un SHA-256 sin clave: quien pudiera escribir en la base podía recalcular la cadena entera y
reescribir quién hizo qué. Los registros anteriores se conservan como **tramo heredado** y se
siguen verificando con su algoritmo; `python -m app.cli verificar-auditoria` informa de los dos
tramos y del punto de corte, y detecta tanto una fila alterada como el intento de degradar la firma
reescribiendo registros con el algoritmo público.

---

## 4. Métricas de seguridad

Menú **Métricas** (requiere `metricas.ver`: admin y auditor). Panel de apoyo a la revisión que
resume:

- **Rotación vencida:** credenciales que superan el umbral (90 días por defecto) sin rotarse.
- **Logins fallidos** en las últimas 24 h y 7 días.
- **Usuarios bloqueados** en este momento.
- **Cuentas sin MFA** (deberían ser cero salvo durante un re-enrolamiento).
- **Top de accesos a credenciales** (últimos 30 días).
- **Concesiones por caducar.**
- **Gobernanza de rotación:** cuántas solicitudes esperan autorización, cuántas están autorizadas
  sin aplicar y cuántas emergencias quedan por revisar, más las señales de patrón (§4 bis).

---

## 4 bis. Rotación de contraseñas bajo gobernanza

Menú **Rotación** (requiere `rotacion.ver`: admin, operador y auditor).

Desde la 1.3.0, la contraseña de una credencial del inventario **no se cambia editando la ficha**.
Es un expediente con cinco pasos y dos personas:

```
SOLICITADA ──► AUTORIZADA ──► CERRADA
     │              │
     └─ rechazada ──┴─ cancelada
```

### Por qué no basta con «cambiar la contraseña»

Un cambio de contraseña sin más deja tres preguntas sin responder: quién decidió cambiarla, por qué
en ese momento, y cuánto duró realmente la anterior. Son justo las tres que hacen falta cuando hay
que explicar una rotación a los dos días de la anterior. El ciclo las responde y lo deja escrito
para siempre.

### Los pasos

| Paso | Quién | Qué exige |
|---|---|---|
| **Solicitar** | admin u operador que ya puede gestionar esa credencial | **Motivo obligatorio** (mínimo 10 caracteres; 30 si la rotación es temprana o de emergencia) y tipo: programada, manual, emergencia o masiva |
| **Autorizar** | **otro administrador**, nunca el solicitante | **Reautenticación**: su contraseña y un código de su **aplicación autenticadora**. El código por correo no sirve |
| **Registrar** | quien pueda solicitar | Cambia la contraseña en el servidor y la registra en la aplicación. La anterior pasa al historial cifrado |

Una credencial solo puede tener **una solicitud abierta** a la vez.

### Rotación temprana

Si la contraseña lleva menos del 25 % de su vigencia (22 días con los 90 por defecto), la rotación
se marca **temprana** y el motivo debe ser más explícito. No se prohíbe —a veces hay que rotar al
día siguiente— pero queda señalada, y varias seguidas disparan una regla de patrón.

### Vía de emergencia (break-glass)

Ante un incidente puede no haber un segundo administrador disponible. En ese caso, una solicitud de
tipo **emergencia** la puede autorizar **su propio solicitante**, dentro de una ventana corta (60
minutos por defecto) y con su reautenticación completa. Esa rotación:

- queda marcada con `emergencia_sin_segundo_par` de forma **imborrable**;
- alerta por correo a **todos** los administradores;
- queda **pendiente de revisión**, y la revisión la cierra **otro** administrador;
- cuenta para la regla de patrón de abuso de emergencia.

Fuera de la ventana vuelve a exigirse la regla de dos personas.

> **Mínimo operativo: dos administradores.** Con uno solo, todas las rotaciones caen por la vía de
> emergencia marcada: visible y revisable, pero sin el control que dan dos personas. La aplicación
> lo advierte en el arranque.

### El libro mayor

Cada rotación deja un asiento permanente que **nunca se purga** y que entra entero en el respaldo
cifrado. Registra la antigüedad de la contraseña al solicitar, al autorizar y al rotar, y la
**desviación** respecto a la fecha que marcaba la política (negativa si se adelantó). Si la
credencial se elimina, el asiento sigue siendo legible: conserva el nombre del activo y el usuario
de acceso.

El asiento también registra el **alcance de la verificación**. En esta versión siempre es «sin
comprobación automática»: el cambio lo hace una persona y nadie comprueba por ella que la credencial
siga sirviendo. Los agentes (1.4.0) comprobarán localmente, y la comprobación contra el servicio
declarado llega en la 2.2.0.

### Señales de patrón

En **Rotación** y en **Métricas** aparecen reglas simples sobre los últimos 30 días: rotaciones
tempranas repetidas, fuera de horario, ráfagas del mismo solicitante o sobre la misma credencial, y
abuso de la vía de emergencia.

Vienen en **modo observación**: se evalúan y se ven, pero no envían avisos. Déjelas así hasta
calibrar los umbrales con los datos reales de su instalación; una regla que avisa de más acaba
filtrada, y entonces se pierde la señal justo cuando hace falta. El interruptor está en
**Configuración → Gobernanza de rotación**.

---

## 5. Tokens de API (integración con SIEM/automatización)

Menú **Tokens** (requiere `tokens.gestionar`, solo admin). Los tokens dan acceso a la **API REST de
solo lectura** (`/api/v1`), que **nunca** expone secretos. Detalle técnico en
[`referencia-api-rest.md`](referencia-api-rest.md).

1. **Crear token:** indique un **nombre** descriptivo; el sistema muestra el valor del token
   **una sola vez**. Cópielo y guárdelo de forma segura (en BD solo queda su hash).
2. **Revocar:** desactiva el token; las peticiones con él dejan de funcionar de inmediato.
3. La lista muestra el **último uso** de cada token para detectar tokens olvidados.

> Use los tokens siempre **sobre TLS**. Un token comprometido solo permite **leer** inventario y
> auditoría (sin contraseñas), pero conviene revocarlo igualmente.

---

## 6. Importación masiva por CSV

Menú **Importar** (requiere `inventario.gestionar`: admin y operador).

- Suba un **CSV** con activos y/o credenciales. El archivo se procesa **en memoria** (no se
  persiste) y las contraseñas se **cifran al guardar**.
- Los **errores por fila no abortan** la importación: al final se muestra un resumen con lo creado
  (servidores, hipervisores, dispositivos de red, VMs, credenciales) y la lista de errores.
- La operación queda auditada.

El CSV usa una columna `tipo` (`servidor`/`hipervisor`/`dispositivo`/`vm`/`credencial`) y, para las
VMs y credenciales, una referencia al activo padre (en credenciales, `activo_tipo` acepta también
`dispositivo`). Los dispositivos de red usan además `tipo_dispositivo`, `version` (firmware) y
`puertos`. Tras importar, revise el inventario y rote o complete las credenciales que lo necesiten.

---

## 6 bis. Configuración del sistema (en caliente)

Menú **Configuración** (solo administradores; requiere `configuracion.gestionar`). Permite ajustar
parámetros operativos **sin reiniciar ni tocar el `.env`**. Los cambios se aplican al instante,
anulan la variable de entorno correspondiente, se propagan a las demás instancias en pocos segundos
y **quedan auditados**.

Grupos de ajustes editables:

- **Sesión y comportamiento:** inactividad máxima, vida máxima de sesión, amortiguación de actividad.
- **Política de cuentas:** longitud mínima de contraseña (mín. 8), intentos antes de bloquear,
  duración del bloqueo.
- **Límites de tasa (anti-abuso):** límites y ventanas de inicio de sesión y de revelado/copiado.
- **Inventario y auditoría:** días de rotación antes de alertar, historial de contraseñas, retención
  de auditoría (mín. 90 días).
- **Notificaciones por correo:** activación, servidor/puerto/usuario SMTP, contraseña SMTP (se guarda
  **cifrada** y nunca se muestra; deje el campo vacío para conservarla), STARTTLS, remitente,
  destinatarios y nombre/emisor.

Utilidades de la pantalla:

- **Origen de cada ajuste:** una insignia indica si el valor viene «por defecto», «por entorno» o si
  está «configurado aquí». **Restablecer** un ajuste borra el override y vuelve al valor base.
- **Enviar correo de prueba:** valida la configuración SMTP enviando un mensaje (sin secretos) a un
  destinatario o a la lista configurada; informa si el envío falla.
- **Información del sistema (solo lectura):** parámetros que **no** se editan aquí porque son
  secretos de despliegue o exigen reinicio (claves criptográficas, base de datos, `COOKIE_SECURE`,
  tamaño máximo de petición, proxies de confianza, backend del limitador). Estos siguen fijándose por
  variable de entorno — ver [`referencia-configuracion.md`](referencia-configuracion.md).

> La configuración inicial (y la de despliegue) sigue haciéndose por variables de entorno; esta
> pantalla es para los ajustes operativos del día a día. Un cambio hecho aquí **prevalece** sobre la
> variable de entorno hasta que se restablezca.

---

## 7. Respaldo y restauración

Operación de **CLI** (no desde la web). Referencia completa en
[`referencia-cli.md`](referencia-cli.md); operación recomendada en
[`guia-implementacion.md`](guia-implementacion.md) §4.7.

```bash
# Crear un respaldo cifrado (pide una frase de mín. 16 caracteres)
python -m app.cli respaldo --salida copia.passwd

# Restaurar (sobre una instancia, posiblemente con claves distintas)
python -m app.cli restaurar --entrada copia.passwd --sobrescribir
```

- El archivo incluye usuarios, inventario, credenciales, códigos de recuperación y bitácora,
  cifrado con una clave derivada de la frase (**scrypt + Fernet**). Es **portable** entre
  instancias.
- **Sin la frase, el respaldo es irrecuperable**: custódiela aparte del archivo (gestor de secretos
  / sobre sellado).
- Para respaldos desatendidos (cron), defina `PASSWD_BACKUP_PASSPHRASE` y use `--retener N`.

---

## 8. Buenas prácticas operativas

- **Menor privilegio:** asigne el rol más bajo que permita la tarea (operador para gestión diaria,
  auditor para revisión, analista con concesiones puntuales).
- **Retire `PASSWD_ADMIN_PASSWORD`** del `.env` tras el primer arranque (solo se usa si la BD está
  vacía).
- **Custodie las claves** `PASSWD_SECRET_KEY`, `PASSWD_ENCRYPTION_KEY` y `PASSWD_AUDIT_KEY`, y la
  frase de respaldo, fuera del servidor. Perder `PASSWD_AUDIT_KEY` no pierde datos, pero deja de
  poder verificarse la cadena de auditoría firmada con ella. Perder la clave de cifrado = perder todas las contraseñas guardadas (salvo el
  respaldo cifrado).
- **Prueba de restauración trimestral** en una máquina aparte.
- **Revise la bitácora** con la cadencia de [`guia-implementacion.md`](guia-implementacion.md) §5.1.
- **Mantenga dos administradores activos**: sin el segundo, la regla de dos personas de la rotación
  no se puede aplicar y todo pasa por la vía de emergencia (§4 bis).
- **Atienda las emergencias pendientes de revisión** en el panel de Rotación; son el precio de
  tener una salida instrumentada en vez de rotaciones fuera del sistema.

---

## 9. Documentos relacionados

- [`manual-usuario.md`](manual-usuario.md) — uso general (todos los roles).
- [`control-acceso.md`](control-acceso.md) — roles y concesiones por activo.
- [`referencia-cli.md`](referencia-cli.md) — comandos de línea de comandos.
- [`referencia-api-rest.md`](referencia-api-rest.md) — API REST de solo lectura.
- [`guia-implementacion.md`](guia-implementacion.md) — instalación, producción y operación.
- [`plan-rotacion-agentes.md`](plan-rotacion-agentes.md) — por qué el ciclo es como es, y qué llega
  en las versiones siguientes (agentes, telemetría, conectores).
</content>
