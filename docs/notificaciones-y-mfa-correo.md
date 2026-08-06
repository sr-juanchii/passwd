# Notificaciones dinámicas, MFA por correo y restablecimiento automatizado

Documenta tres funcionalidades que comparten un mismo canal —el correo— y una
misma regla de contenido.

---

## Regla de contenido: el hecho, no el secreto

Los avisos de este sistema comunican **qué pasó**, nunca **el secreto implicado**.
Un aviso de que se actualizó la contraseña de un servidor dice qué activo cambió,
quién lo cambió y cuándo; **no incluye la contraseña nueva, ni la anterior, ni
ninguna pista sobre ellas** (longitud, prefijo, parecido con la previa).

El motivo es de modelo de amenaza: el correo es un canal que la aplicación **no
controla** —buzones ajenos, reenvíos automáticos, copias en servidores
intermedios, respaldos de correo, clientes móviles sincronizados—. Todo secreto
que salga por ahí queda fuera de la custodia del vault, sin cifrado en reposo, sin
control de acceso, sin límite de tasa y sin bitácora. Quien necesite la contraseña
vigente entra en la aplicación y la revela allí, donde su permiso se comprueba, el
acceso se limita y el hecho queda registrado — que es exactamente el control que
un correo con el secreto dentro eludiría.

`tests/test_avisos_dinamicos.py` verifica esta propiedad de forma explícita contra
el texto real de los correos, con la contraseña anterior **y** la nueva
(`test_el_aviso_de_credencial_nunca_incluye_la_contrasena` y un barrido general
sobre todos los avisos de un flujo completo). Si alguien añadiera el valor al
cuerpo «para comodidad del usuario», la suite lo detiene.

### Las dos excepciones deliberadas

Hay exactamente dos mensajes que **sí** llevan un secreto, y ambos cumplen tres
condiciones: son de un solo uso, tienen vida corta o cambio forzado, y van al
buzón **de su propio titular** (nunca al de un tercero).

| Mensaje | Secreto | Por qué es aceptable |
|---|---|---|
| OTP del MFA de respaldo | Código de 8 dígitos | Un solo uso, caduca en 10 min, y sin la contraseña no sirve de nada |
| Contraseña temporal de un reset administrativo | Contraseña temporal | Cambio forzado en el primer acceso, y el MFA sigue exigiéndose |

Ninguna de las dos da acceso por sí sola. Y la alternativa que sustituyen es
peor: que un administrador vea el secreto en pantalla y lo reenvíe a mano por
chat o correo personal, donde queda sin caducidad y sin auditoría.

---

## 1. MFA de respaldo: OTP enviado al correo

### Para qué

Cubre al usuario que no tiene acceso a su aplicación autenticadora (dispositivo
perdido, cambiado, roto o sin batería) **ni** a sus códigos de recuperación.
Puede pedir un código de un solo uso a su buzón registrado y completar con él el
segundo factor.

### Cómo funciona

```
1. El usuario envía usuario + contraseña          → sesión en etapa 'mfa_pendiente'
2. Pulsa «Enviarme un código por correo»          → POST /mfa/otp-correo
3. Recibe un código de 8 dígitos en su buzón      → caduca en 10 minutos
4. Lo introduce en la pantalla de verificación    → POST /mfa/verificar
```

El orden de preferencia que intenta el servidor en `/mfa/verificar` es
**TOTP → código de recuperación → OTP de correo**: el método de respaldo se
prueba en último lugar.

### Controles aplicados

| Control | Detalle |
|---|---|
| Requiere contraseña válida | Solo alcanzable desde la etapa `mfa_pendiente`; **no es un punto de entrada** |
| Un solo uso | `usado_en` en base de datos; emitir uno nuevo invalida el anterior |
| Caducidad | `PASSWD_EMAIL_OTP_TTL_MINUTES` (10 min por defecto) |
| Tope de intentos | 5 fallos invalidan el código |
| Límite de tasa | 3 solicitudes por cuenta **y** 3 por IP cada 15 min |
| Solo hash en BD | SHA-256; el valor en claro solo existe en el correo |
| CSRF | Obligatorio en la solicitud |
| Comparación en tiempo constante | `hmac.compare_digest` sobre el hash |
| Normalización canónica única | Misma función al emitir y al verificar (ver §Lección abajo) |
| Auditoría | `mfa_otp_correo_solicitado` y `mfa_otp_correo_usado` |
| Alerta al equipo de seguridad | Cada acceso por esta vía notifica a `PASSWD_NOTIFY_TO` |
| El código nunca vuelve en la respuesta | La API confirma el envío y devuelve el buzón **enmascarado** |

### ⚠️ Este factor es más débil que el TOTP

Conviene tenerlo explícito: **quien controle el buzón del usuario y conozca su
contraseña completa la autenticación.** Eso añade el proveedor de correo a la
cadena de confianza del acceso a un sistema que custodia las contraseñas de todos
los servidores. Un buzón comprometido —phishing, robo de sesión de webmail, fuga
en el correo corporativo— pasa a valer tanto como el segundo factor.

Recomendación por orden de preferencia:

1. **TOTP** (aplicación autenticadora) — el método normal.
2. **Códigos de recuperación** — el proyecto ya emite 8 al enrolar el MFA; es el
   respaldo *más fuerte* y no depende de ningún canal externo. Guárdelos.
3. **OTP por correo** — último recurso.

Si su política de seguridad no acepta esta dependencia, se desactiva sin tocar el
resto del MFA:

```bash
PASSWD_EMAIL_OTP_ENABLED=false
```

También es modificable **en caliente** desde la consola de configuración, sin
reiniciar. Al desactivarlo, el botón desaparece de la pantalla y el endpoint
responde `409`.

Está **activo por defecto** (según lo solicitado), pero solo funciona si el correo
está configurado: sin SMTP el código no podría entregarse y el método se anuncia
como no disponible.

### Lección aplicada del hallazgo anterior

La normalización del código vive en **una sola función**
(`otp_correo.normalizar`), usada tanto al emitir como al verificar. Es la misma
disciplina que cerró la vulnerabilidad de reutilización de TOTP documentada en
[`resistencia-bypass-mfa.md`](resistencia-bypass-mfa.md): si el registro y la
comparación normalizaran distinto, el control de un solo uso se eludiría cambiando
el formato del código.

---

## 2. Restablecimiento administrativo con envío automático

### Qué cambió

| Antes | Ahora |
|---|---|
| El admin veía la contraseña temporal en pantalla | Viaja **directo al buzón del titular** |
| El admin la reenviaba a mano (chat, correo personal) | No hay paso manual |
| El secreto pasaba por la pantalla y el portapapeles del admin | El admin **no la ve** |

La acción es **exclusiva de administradores** (permiso `usuarios.gestionar`, que
en la matriz RBAC solo tiene el rol `admin`). Está verificado con una prueba que
comprueba que operador, auditor y analista reciben `403`.

### Respuesta de la API

```json
{ "username": "ana.perez", "correo_enviado": true, "destino": "a*******z@ejemplo.com" }
```

El buzón se devuelve **enmascarado**: confirma a dónde salió sin exponer la
dirección completa. La contraseña **no** aparece en la respuesta.

### Contingencia si el correo falla

El restablecimiento ya ocurrió cuando se intenta el envío, así que si SMTP falla
la cuenta quedaría con una contraseña que nadie conoce. En ese caso —y solo en
ese— la contraseña se devuelve al administrador con un aviso explícito, y la
bitácora lo registra de forma **distinguible**:

> `...NO se pudo enviar por correo: entregada al administrador en pantalla`

Así queda constancia auditable de que el secreto pasó por pantalla.

### Nota de alcance

El **alta** de un usuario nuevo sigue mostrando la contraseña temporal en
pantalla: la petición era sobre el flujo de *restablecimiento*. El mismo
tratamiento es aplicable al alta si se desea; es un cambio pequeño y análogo.

---

## 3. Notificaciones dinámicas por matriz de permisos

### Qué cambió

Antes las alertas iban únicamente a una lista fija (`PASSWD_NOTIFY_TO`), pensada
para el equipo de seguridad. Ahora existen **dos familias**:

| Familia | Destinatario | Módulo |
|---|---|---|
| Estática | `PASSWD_NOTIFY_TO` (equipo de seguridad) | `notifications.enviar_alerta` |
| **Dinámica** | Resuelta en ejecución desde la matriz de permisos | `app/avisos.py` |

El resolutor (`access.usuarios_con_acceso_a_activo`) responde «¿quiénes tienen
acceso a este activo?» reutilizando **como predicado** las mismas funciones que
autorizan de verdad (`puede_ver_activo` / `puede_revelar_en_activo`). No duplica
la lógica: si mañana cambia la matriz de permisos, los destinatarios cambian con
ella y no pueden divergir de la autorización real.

### Los eventos

#### 3a. Actividad propia y permisos propios

| Evento | Aviso |
|---|---|
| Inicio de sesión | IP, cliente, rol y fecha (el aviso de mayor valor defensivo: delata una contraseña robada) |
| Actividad sensible | Revelado o copia de credenciales, **deduplicado por sesión y categoría** |
| Concesión de acceso | Activo y nivel concedido |
| Revocación de acceso | Activo cuyo acceso se retiró |
| Cambio de rol | Rol anterior → rol nuevo |

**Sobre la deduplicación.** Un aviso por cada acción de la sesión convertiría el
trabajo normal en decenas de correos, y un usuario que recibe decenas de correos
crea un filtro y deja de leerlos — perdiendo justo la señal que se pretendía dar.
Por eso: **un aviso por tipo de actividad y sesión.** La bitácora de auditoría
conserva siempre el registro completo, acción por acción. Si prefiere el
comportamiento literal (un correo por acción) o un resumen diario, dígalo: ambos
son variantes pequeñas sobre la misma base.

#### 3b. Auditoría de credenciales compartidas

Al actualizar una credencial, el sistema identifica **automáticamente a los demás
usuarios con acceso a ese activo** y les avisa de la modificación. Se excluye al
autor del cambio (ya sabe lo que hizo) y a quien no tiene acceso al activo.

El aviso distingue si cambió la contraseña o solo otros datos, e **incluye
únicamente el hecho**: activo, servicio, usuario de acceso, autor y fecha. Ver la
regla de contenido al principio de este documento.

Utilidad práctica: quien use esa credencial en scripts o tareas programadas sabe
que debe actualizarla, evitando fallos de autenticación y bloqueos de cuenta por
intentos fallidos.

#### 3c. Alertas preventivas de caducidad (rotación)

Aviso proactivo cuando se acerca la fecha del cambio obligatorio, dirigido **solo
a quienes pueden revelar** la contraseña (los que pueden rotarla). El auditor ve
el activo pero nunca sus secretos, así que queda fuera.

```bash
# Tarea programada diaria (cron)
0 7 * * *  cd /srv/passwd && python -m app.cli avisar-rotacion

# Revisar el alcance antes de activarla, sin enviar nada:
python -m app.cli avisar-rotacion --simular
```

Ejecutarlo a diario es seguro: los avisos se **deduplican por credencial y umbral
con una ventana de 7 días**, así que el mismo aviso no se repite cada día. Se
distingue «rotación próxima» de «rotación VENCIDA».

### Configuración

| Variable | Defecto | Para qué |
|---|---|---|
| `PASSWD_NOTIFY_ENABLED` | `false` | Interruptor general del correo. **Sin él no sale nada.** |
| `PASSWD_NOTIFY_USERS_ENABLED` | `true` | Avisos dinámicos por usuario (dentro del anterior) |
| `PASSWD_NOTIFY_TO` | — | Lista fija del equipo de seguridad |
| `PASSWD_ROTATION_WARNING_DAYS` | `14` | Antelación del preaviso de rotación |
| `PASSWD_ROTATION_MAX_DAYS` | `90` | Política de rotación obligatoria |
| `PASSWD_EMAIL_OTP_ENABLED` | `true` | MFA de respaldo por correo |
| `PASSWD_EMAIL_OTP_TTL_MINUTES` | `10` | Vida del OTP de correo |

Todas son modificables **en caliente** desde la consola de configuración.

### ⚠️ Cambio de comportamiento al actualizar

Si su despliegue ya tenía `PASSWD_NOTIFY_ENABLED=true`, tras esta actualización
**los usuarios finales empezarán a recibir correos** (inicios de sesión, cambios
de permisos, credenciales compartidas), no solo la lista de seguridad. Es el
comportamiento solicitado. Para conservar el anterior:

```bash
PASSWD_NOTIFY_USERS_ENABLED=false
```

Conviene avisar a los usuarios antes de activarlo, para que no confundan los
avisos legítimos con phishing — un correo inesperado que habla de sus contraseñas
es exactamente lo que un atacante imitaría.

### Nota de despliegue: multi-worker

La deduplicación (de actividad sensible y de rotación) se apoya en el limitador de
tasa. Con `PASSWD_RATE_LIMIT_BACKEND=memoria` el estado es **por proceso**, así
que con varios workers podría salir un aviso por proceso. Con más de un worker o
réplica:

```bash
PASSWD_RATE_LIMIT_BACKEND=bd
```

Es la misma recomendación que ya aplica al límite de tasa de login.

### Envío individual, no en copia

Un aviso dirigido a varios usuarios se envía **como mensajes independientes**, uno
por destinatario. Agrupar las direcciones en un solo `To:` revelaría a cada
usuario quién más tiene acceso al activo, que es información de control de acceso.

---

## Documentos relacionados

- [`resistencia-bypass-mfa.md`](resistencia-bypass-mfa.md) — modelo de amenaza del
  segundo factor y por qué el TOTP sigue siendo el método preferente.
- [`control-acceso.md`](control-acceso.md) — la matriz de permisos que resuelve los
  destinatarios.
- [`referencia-configuracion.md`](referencia-configuracion.md) — todas las
  variables `PASSWD_*`.
- [`manual-administrador.md`](manual-administrador.md) — operación diaria.
