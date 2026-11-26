# Manual del administrador

**Sistema:** Gestor de Contraseñas de Servidores
**Audiencia:** personas con rol **admin** (y, donde se indica, **auditor**).
**Alcance:** las tareas de administración del día a día desde la interfaz. Para la **instalación**
y el **despliegue** consulte [`guia-implementacion.md`](guia-implementacion.md); para el uso general
del inventario y las credenciales, el [`manual-usuario.md`](manual-usuario.md).

> El administrador es el único rol que gestiona usuarios, concede/revoca accesos por activo,
> administra los tokens de API y da de alta o revoca los agentes de rotación. El auditor puede ver la bitácora y las métricas, pero no revela
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
Con agentes de rotación (1.4.0), además: `agente_anomalia_ip`, `agente_acceso_rechazado`,
`agente_enrolamiento_rechazado`, `trabajo_rotacion_resultado_rechazado` y
`trabajo_rotacion_sin_confirmar` (lista completa en [`manual-operativo.md`](manual-operativo.md)
§15). Lo que hace un agente figura con el usuario `agente:<nombre>`, nunca con una persona.

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
- **Agentes de rotación** (desde la 1.4.0, solo con los agentes activos): cuántos están conectados,
  sin contacto, con la identidad caducada o pendientes de instalar, las rotaciones sin confirmar y
  la lista de agentes que piden atención (§4 ter.8).

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

El asiento también registra el **alcance de la verificación**. En la vía manual es «sin
comprobación automática»: el cambio lo hace una persona y nadie comprueba por ella que la credencial
siga sirviendo. Desde la 1.4.0, una rotación ejecutada por un agente queda «comprobada en el
sistema operativo» (§4 ter.3); la comprobación contra el servicio declarado llega en la 2.2.0.

### Señales de patrón

En **Rotación** y en **Métricas** aparecen reglas simples sobre los últimos 30 días: rotaciones
tempranas repetidas, fuera de horario, ráfagas del mismo solicitante o sobre la misma credencial, y
abuso de la vía de emergencia.

Vienen en **modo observación**: se evalúan y se ven, pero no envían avisos. Déjelas así hasta
calibrar los umbrales con los datos reales de su instalación; una regla que avisa de más acaba
filtrada, y entonces se pierde la señal justo cuando hace falta. El interruptor está en
**Configuración → Gobernanza de rotación**.

---

## 4 ter. Agentes de rotación (desde la 1.4.0)

Menú **Agentes** (requiere `agentes.ver`: admin, operador y auditor). Dar de alta, reinstalar y
revocar requieren `agentes.gestionar` (solo admin). Permisos y reautenticación en
[`control-acceso.md`](control-acceso.md).

Un **agente** es un programa instalado en un servidor Linux (servidor físico, hipervisor o máquina
virtual) que aplica en él las rotaciones **que ya autorizaron dos personas**, comprueba que la
contraseña nueva funciona y, si no, deja la anterior. No decide nada: la gobernanza del §4 bis no
cambia, solo deja de hacer falta que alguien cambie la contraseña a mano. Cómo está construido, en
[`arquitectura-agentes.md`](arquitectura-agentes.md); qué tiene prohibido, en
[`contrato-agente.md`](contrato-agente.md).

> **Antes de empezar:** los agentes vienen **apagados**. Actívelos en **Configuración → Agentes de
> rotación → «Agentes de rotación activos»** (o `PASSWD_AGENTES_ENABLED=true`). Mientras estén
> apagados, la página **Agentes** lo advierte («Agentes desactivados») y toda rotación sigue el
> flujo manual. Los dispositivos de red no admiten agente.

### 4 ter.1 Dar de alta un agente

1. Abra la **ficha del activo** (servidor, hipervisor o VM). El panel **«Agente de rotación»**
   muestra la insignia **«Sin agente»**.
2. Revise el **Nombre del agente** (se propone `agente-<nombre del activo>`; debe ser único) y
   pulse **«Dar de alta un agente»**.
3. Confirme su identidad con su **contraseña** y un **código de su aplicación autenticadora** y
   pulse **«Dar de alta»**.
4. Aparece el **token de instalación**. Se muestra **una sola vez** (el servidor solo guarda su
   huella), sirve para **un único enrolamiento** y **caduca en una hora**. Cópielo con el botón de
   copiar y pulse **«Ya lo he guardado»** cuando lo tenga.
5. Junto al token, la pantalla muestra la orden de instalación con las cuentas de las credenciales
   del activo ya rellenas:

   ```bash
   sudo ./instalar.sh --backend https://<servidor-passwd> --cuentas <cuenta1,cuenta2> \
        --binarios . --sumas SHA256SUMS --token -
   ```

   El token **no va en la línea de órdenes**: se pega cuando el instalador lo pide, para que no
   quede en el historial del shell ni a la vista de `ps`. Requisitos, verificación y resolución de
   problemas en [`guia-instalacion-agente-linux.md`](guia-instalacion-agente-linux.md).
6. Al enrolarse, la insignia pasa de **«Pendiente de instalar»** a **«Conectado»** y el panel muestra
   el host, la versión, el último latido, la validez de la identidad y la huella de su clave.

Si el token caduca antes de instalar, el panel avisa: «El token de instalación caducó sin que el
agente llegara a instalarse». Emita otro con **«Reinstalar»** (§4 ter.5).

### 4 ter.2 Elegir qué credenciales rotan por el agente

Tener agente no cambia nada por sí solo: **cada credencial** decide su vía. En el panel **«Rotación
de la contraseña»** de la credencial, la línea **«Vía de rotación»** muestra **«Manual»** o
**«Agente del activo»**, y un administrador la cambia con **«Rotar con el agente»** o **«Rotar a
mano»**. El cambio:

- solo se ofrece cuando la credencial **no tiene una solicitud abierta**, y el servidor lo rechaza
  mientras haya un trabajo despachado al agente;
- exige que el activo tenga un agente **enrolado**: con uno dado de alta pero aún «Pendiente de
  instalar», el servidor lo rechaza;
- queda en la bitácora (`credencial_via_rotacion_cambiada`).

### 4 ter.3 Rotar con el agente

Con la vía «Agente del activo», el panel de la credencial ofrece **«Rotar ahora»** en lugar de
«Solicitar rotación». No es un atajo: crea la **misma solicitud** del §4 bis, con motivo y tipo, y
el agente no recibe nada hasta que **otro administrador la autoriza**. Al autorizarla:

1. El sistema genera la contraseña nueva y **despacha un trabajo** al agente de ese activo. El
   asiento pasa a **«En ejecución»** y el panel dice «En manos del agente …» con la hora límite
   para recogerlo (30 minutos por defecto).
2. El agente lo recoge, cambia la contraseña de la cuenta local, **comprueba** que la nueva
   autentica en el sistema operativo y confirma. Solo entonces el inventario guarda la nueva y la
   anterior pasa al historial cifrado. El asiento dice **«Ejecutada por el agente …»** y
   «Comprobada en el sistema operativo».
3. Si la nueva no funciona, el agente **restaura la anterior** e informa «revertido»; si no pudo
   cambiarla, «fallado». En los dos casos la contraseña registrada **no cambia**, la solicitud se
   cierra y se avisa por correo al equipo de seguridad (si las alertas están activas). Para volver
   a intentarlo, abra otra solicitud.

> **Qué significa «verificación local».** Demuestra que la contraseña autentica la cuenta en el
> sistema operativo, no que siga sirviendo para el servicio declarado (SSH, RDP…), que puede tener
> sus propias restricciones. La comprobación contra el servicio llega en la 2.2.0.

**Si el trabajo no sale o no se recoge.** Una autorización nunca se pierde. Si al autorizar no se
pudo despachar (agentes desactivados, identidad del agente caducada, versión por debajo de la
mínima, otro trabajo en curso, intervalo mínimo) o si nadie recogió el trabajo dentro de su ventana
(agente apagado o sin red), la solicitud queda **«Autorizada, pendiente de aplicar»** y el panel lo
explica. El motivo queda en la bitácora (`rotacion_no_despachada`, `trabajo_rotacion_expirado`).
Entonces puede:

- pulsar **«Enviar al agente»** (admin u operador) cuando el agente vuelva a estar disponible, o
- cambiar la contraseña a mano y registrarla con **«Registrar la rotación»**, como en la 1.3.0.

**Intervalo mínimo.** Una credencial rotada hace menos de 24 horas (ajuste «Intervalo mínimo entre
rotaciones por agente») no se despacha al agente: corta un bucle de rotaciones. Solo una solicitud
de tipo **emergencia** lo salta, y queda en la bitácora.

**Cancelar.** El servidor admite cancelar una solicitud despachada mientras el agente **no** haya
recogido el trabajo; una vez recogido, no: puede estar aplicándolo, y hay que esperar su resultado.
La interfaz solo ofrece **«Cancelar la solicitud»** mientras espera autorización.

### 4 ter.4 Resolver una rotación «sin confirmar»

Si el agente recoge el trabajo y no informa del resultado (se apagó, perdió la red o se revocó a
mitad), pasado el plazo del trabajo más un margen de 15 minutos la rotación queda **«Sin
confirmar»**: la contraseña pudo cambiar en el activo o no. Se avisa por correo, aparece en
**Rotación → «Rotaciones sin confirmar»** y en **Métricas**, y la credencial **no admite otra
rotación** hasta resolverla. Nunca se deja un estado indeterminado en silencio.

1. Compruebe en el servidor qué contraseña vale ahora.
2. En el panel de la credencial, un administrador pulsa:
   - **«Sí, quedó la nueva»**: el inventario registra la contraseña nueva;
   - **«No, sigue la anterior»**: el inventario conserva la anterior y la rotación se cierra como
     fallida.
3. Confirme su identidad (contraseña + código) y pulse **«Confirmar»**.

El asiento queda cerrado con «Sin comprobación automática» —lo comprobó una persona, no el
sistema— y con quién lo resolvió (`trabajo_rotacion_resuelto_a_mano`).

### 4 ter.5 Reinstalar un agente

**«Reinstalar»** emite un token de instalación nuevo (con reautenticación: diálogo «Emitir un token
de instalación nuevo» → **«Emitir token»**) y **anula al momento la identidad vigente** del agente,
que vuelve a «Pendiente de instalar» hasta que se instale con el token nuevo. Úselo cuando:

- la insignia dice **«Identidad caducada»**: el agente estuvo apagado más de lo que dura su
  identidad (24 horas por defecto) y ya no puede renovarla;
- el servidor se reinstaló o se sospecha que su identidad se copió;
- el token de instalación caducó antes de usarse.

### 4 ter.6 Revocar un agente

**«Revocar»** (con confirmación) retira la identidad del agente **al momento**: deja de recibir
trabajos y sus credenciales **vuelven a rotarse a mano**. Si tenía un trabajo sin recoger, se
cancela y la rotación vuelve a quedar autorizada; si ya lo había recogido, queda «sin confirmar»
(§4 ter.4). El agente revocado se conserva como historia (el libro mayor lo nombra) y el activo
queda libre para dar de alta otro. Un agente revocado no se puede reactivar: dé de alta uno nuevo.

Revoque también el agente antes de dar de baja o reutilizar un servidor, y desinstálelo de la
máquina ([`guia-instalacion-agente-linux.md`](guia-instalacion-agente-linux.md)).

### 4 ter.7 La página Agentes y las insignias

La página **Agentes** lista el parque: agente y host, activo (enlace a su ficha), estado, versión,
último latido y trabajo en curso. **«Mostrar también los revocados»** incluye la historia. Los
agentes se dan de alta desde la ficha de cada activo, no desde aquí.

| Insignia | Qué significa | Qué hacer |
|---|---|---|
| **Sin agente** | Las contraseñas del activo se rotan a mano | Nada, o dar de alta un agente |
| **Pendiente de instalar** | Dado de alta, aún no instalado con su token | Instalarlo; si el token caducó, «Reinstalar» |
| **Conectado** | Late con normalidad y puede ejecutar rotaciones autorizadas | Nada |
| **Sin contacto** | Más de 24 horas (por defecto) sin latir | Comprobar el servicio `passwd-agente` en el servidor |
| **Identidad caducada** | Estuvo apagado más de lo que dura su identidad | «Reinstalar» con un token nuevo |

La insignia se **calcula** en cada consulta a partir del último latido y de la caducidad de la
identidad: no depende de que corra ningún proceso de fondo. Una versión «por debajo de la mínima»
se marca en rojo; «en periodo de gracia», en ámbar.

### 4 ter.8 Métricas de los agentes

Con los agentes activos, **Métricas** añade el panel **«Agentes de rotación»**: cuántos hay
**Conectados**, **Sin contacto**, con **Identidad caducada** y **Pendientes de instalar**, cuántas
**Rotaciones sin confirmar** hay, y la lista de los que piden atención (sin contacto o caducados).
Los recuentos respetan el control de acceso por objeto.

### 4 ter.9 Ajustes

En **Configuración → Agentes de rotación**: el interruptor, la validez de un trabajo despachado, el
intervalo mínimo entre rotaciones, la vida de la identidad, el umbral de «sin contacto», la cadencia
del latido, la conservación de la telemetría, la versión mínima y su gracia, y el aviso de
renovaciones desde otra IP. Valores y efecto de cada uno en
[`referencia-configuracion.md`](referencia-configuracion.md).

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
- **Agentes de rotación** (desde la 1.4.0): interruptor general, validez del trabajo despachado,
  intervalo mínimo entre rotaciones, vida de la identidad, umbral de «sin contacto», cadencia del
  latido, conservación de la telemetría, versión mínima y su gracia, y aviso de renovaciones desde
  otra IP (§4 ter.9).

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
- **Agentes (desde la 1.4.0):** el respaldo guarda los agentes **solo como historia** y la
  restauración los repone **revocados**: una identidad de máquina restaurada sería un acceso que
  nadie ha vuelto a conceder. Las credenciales que rotaban por agente vuelven a la vía manual, y
  los **trabajos y la telemetría no se respaldan nunca**. Tras restaurar, dé de alta y reinstale
  los agentes que necesite. Detalle en [`manual-operativo.md`](manual-operativo.md) §21.4.

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
- **Resuelva cuanto antes las rotaciones «sin confirmar»** y revise los agentes **sin contacto**:
  mientras tanto, esas credenciales no se pueden rotar (§4 ter.4).
- **Revoque el agente** de un servidor antes de darlo de baja o reutilizarlo (§4 ter.6).

---

## 9. Documentos relacionados

- [`manual-usuario.md`](manual-usuario.md) — uso general (todos los roles).
- [`control-acceso.md`](control-acceso.md) — roles y concesiones por activo.
- [`referencia-cli.md`](referencia-cli.md) — comandos de línea de comandos.
- [`referencia-api-rest.md`](referencia-api-rest.md) — API REST de solo lectura.
- [`guia-implementacion.md`](guia-implementacion.md) — instalación, producción y operación.
- [`guia-instalacion-agente-linux.md`](guia-instalacion-agente-linux.md) — instalar, comprobar y
  retirar el agente en un servidor Linux.
- [`arquitectura-agentes.md`](arquitectura-agentes.md) y [`contrato-agente.md`](contrato-agente.md)
  — cómo funciona el agente y qué tiene prohibido.
- [`plan-rotacion-agentes.md`](plan-rotacion-agentes.md) — por qué el ciclo es como es, y qué llega
  en las versiones siguientes (telemetría ampliada, conectores).
</content>
