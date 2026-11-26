# Referencia de la API de los agentes (`/api/agent`)

API **exclusiva de los agentes de rotación** (versión 1.4.0). La usa el binario instalado en cada
activo Linux para enrolarse, latir, recoger su trabajo de rotación, informar del resultado y enviar
telemetría. Está implementada en [`app/api_agent/__init__.py`](../app/api_agent/__init__.py), que
solo traduce HTTP ↔ servicio: las reglas viven en [`app/servicios/agentes.py`](../app/servicios/agentes.py)
y [`app/servicios/rotacion.py`](../app/servicios/rotacion.py).

> **No es una API para personas ni para integraciones.** Para SIEM y automatización está
> [`/api/v1`](referencia-api-rest.md), que no cambia en la 1.4.0. El panel de agentes (alta,
> revocación, re-enrolamiento) usa `/api/web`, documentada en
> [`../frontend/API_CONTRACT.md`](../frontend/API_CONTRACT.md). Lo que un agente **debe** y **no
> debe** hacer está en [`contrato-agente.md`](contrato-agente.md); este documento describe el
> intercambio HTTP.

## Características de seguridad

- **Autenticación:** cabecera `Authorization: Bearer <token del agente>`. **Sin cookies ni CSRF.**
  La única ruta que no la lleva es el enrolamiento, que canjea un token de un solo uso.
- **Interruptor:** con `agentes_enabled` apagado, **todo el prefijo responde 404** (ver abajo).
- **Identidad de vida corta:** el token caduca en `agentes_token_vida_horas` (24 h por omisión) y se
  renueva en el saludo. En la base de datos solo se guarda su **hash SHA-256**.
- **Un agente, un activo:** cada agente solo recibe trabajos de su propio activo, sellados a su
  clave pública X25519.
- **Topes de cuerpo propios:** 4 KiB por petición y 16 KiB para la telemetría, muy por debajo del
  límite global de la aplicación. Se rechaza lo que excede; no se amplía el límite.
- **Límites de tasa** por dirección, por agente y para el enrolamiento.
- **Auditoría** de todo cambio de estado y de todo rechazo; el latido rutinario no deja asiento.
- **Úsese siempre sobre TLS.** El agente se niega a hablar por `http` salvo hacia *loopback*.

### Convenciones

- Cuerpos en JSON (`Content-Type: application/json`). Envíe también `Accept: application/json`: sin
  ella, los errores 403 y 404 se devuelven como página HTML.
- Las fechas van en ISO 8601 con precisión de segundos, **en UTC y sin sufijo de zona**
  (`2026-11-26T10:15:00`).
- Un error devuelve `{"detail": "<mensaje>"}`; un error de validación (422), `{"detail": [ … ]}` con
  la lista de campos que fallaron.
- Los campos que el servidor no conoce se ignoran.

## Interruptor `agentes_enabled`

Mientras `agentes_enabled` (`PASSWD_AGENTES_ENABLED`, o el panel de configuración) esté **apagado**,
que es el valor por omisión, cualquier petición a `/api/agent/*` con un método que la ruta admite
responde **404** `{"detail":"Not Found"}`, antes de mirar el cuerpo o la identidad: la superficie no
existe hasta que alguien decide activarla. El interruptor se evalúa en cada petición, así que
encenderlo o apagarlo desde el panel surte efecto sin reiniciar.

> Un método que la ruta no admite (p. ej. `GET /api/agent/saludo`) responde **405** aunque el
> interruptor esté apagado.

## Autenticación — respuestas

| Situación | Código | Cuerpo |
|---|---|---|
| Falta la cabecera o no empieza por `Bearer ` | `401` | `{"detail":"Falta la identidad del agente."}` |
| Token inexistente, caducado, de un agente pendiente o revocado (también el anterior pasado su solapamiento) | `401` | `{"detail":"Identidad de agente no válida, revocada o caducada."}` |
| Límite por dirección superado | `429` | `{"detail":"Demasiadas peticiones desde esta dirección."}` |
| Límite por agente superado | `429` | `{"detail":"Demasiadas peticiones de este agente."}` |

**Todo 401 lleva `WWW-Authenticate: Bearer`**, también los del enrolamiento. Un 401 con un token
que funcionaba significa que la identidad caducó o se revocó: no hay renovación posible y hay que
**volver a enrolar** el agente desde su ficha en el panel (ver [`contrato-agente.md`](contrato-agente.md) §4.5).

El orden de comprobación es: interruptor → tope de cuerpo → límite por dirección → identidad →
límite por agente → validación del cuerpo (422) → reglas del servicio. En el enrolamiento, que no
lleva identidad, la validación del cuerpo va justo después del tope, antes de los límites de tasa.

### Obtener la identidad

1. Un administrador da de alta el agente en la ficha del activo. El panel muestra **una sola vez**
   un **token de enrolamiento** de un solo uso que caduca en **1 hora**.
2. El instalador lo canjea en `POST /api/agent/enrolar` y guarda la identidad recibida.
3. A partir de ahí el agente usa su token en cada petición y lo renueva en el saludo.

Si el token de enrolamiento caduca sin usarse o la identidad del agente caduca, el administrador
**reemite** el enrolamiento desde la ficha (con reautenticación) y se vuelve a enrolar con un par de
claves nuevo. Ver [`guia-instalacion-agente-linux.md`](guia-instalacion-agente-linux.md).

## Límites de tasa

Ventanas deslizantes. Los valores son constantes del módulo, no ajustes de configuración.

| Límite | Clave | Cuántas | Ventana | Qué cuenta |
|---|---|---|---|---|
| Por dirección | IP del cliente | **300** | 5 min | Toda petición que llega a autenticarse o a enrolarse, y todo 413 por tope de ruta. Se aplica **antes** de autenticar: frena el barrido de tokens. |
| Por agente | Agente autenticado | **120** | 5 min | Toda petición autenticada de ese agente. Un agente sano hace tres o cuatro por ciclo. |
| Enrolamiento | IP del cliente | **10** | 15 min | Todo intento de enrolamiento, válido o no. Frena la fuerza bruta del token de un uso. |

- El límite vive en la memoria **de cada proceso** salvo con `PASSWD_RATE_LIMIT_BACKEND=bd`; con
  varios *workers* o réplicas, use `bd` para que el presupuesto sea uno.
- Detrás de un proxy inverso, declare el proxy en `PASSWD_TRUSTED_PROXIES`: si no, todos los
  agentes comparten la dirección del proxy y, con ella, los 300 y los 10 de su ventana.
- Al recibir un 429, el agente espera al ciclo siguiente.

## Topes de cuerpo

| Ruta | Tope | Respuesta al excederlo |
|---|---|---|
| `POST /api/agent/telemetria` | **16 KiB** (16 384 bytes) | `413` `{"detail":"La telemetría excede 16384 bytes: recórtela en el agente."}` |
| Cualquier otra de `/api/agent` | **4 KiB** (4096 bytes) | `413` `{"detail":"La petición excede 4096 bytes."}` |

El tope se comprueba **antes de autenticar**, cuenta para el límite por dirección y se audita.
Ninguna petición del protocolo se acerca a 4 KiB (la mayor, un resultado con su detalle, ronda los
2,5 KiB); el agente de referencia recorta la telemetría a 12 KiB antes de enviarla.

Un cuerpo por encima del **límite global** de la aplicación (`PASSWD_MAX_REQUEST_BYTES`, 64 KiB por
omisión) lo corta antes el *middleware* general con `413`
`{"detail":"La petición excede el tamaño permitido."}`, que no pasa por la API de agentes: no se
audita ni cuenta para sus límites, y se responde así aunque el interruptor esté apagado.

## Qué se audita y qué no

| Se audita (acción en la bitácora) | Cuándo |
|---|---|
| `agente_enrolado` | Enrolamiento correcto. |
| `agente_enrolamiento_rechazado` | Token de enrolamiento inexistente, ya usado o caducado (además del rechazo general). |
| `agente_token_renovado` | El saludo emitió un token nuevo. |
| `agente_anomalia_ip` | Renovación desde una IP distinta de la de la renovación anterior, dentro de una vida de token. |
| `trabajo_rotacion_entregado` | **Cada** entrega de un trabajo, también las re-entregas. |
| `trabajo_rotacion_resultado` | Resultado aceptado. |
| `rotacion_aplicada` | Además del anterior, cuando el resultado es `aplicado`. |
| `trabajo_rotacion_resultado_rechazado` | Resultado de un trabajo ajeno, o de uno que no está `entregado`. |
| `trabajo_rotacion_expirado`, `trabajo_rotacion_sin_confirmar` | Vencimientos que detecta la consulta del trabajo (o el mantenimiento). Sujeto: `sistema`. |
| `agente_acceso_rechazado` | **Todo** rechazo de la API (401, 400, 403, 404, 409, 413, 429), con el detalle `«código» «método» «ruta»: «mensaje»`. Un 429 se audita **una vez por ventana y dirección**. El asiento se confirma aparte, de modo que sobrevive a la anulación de la transacción de la petición. |

**No se audita:**

- el **saludo sin renovación** y la **consulta sin trabajo** (204): quedan como «último contacto»
  del agente; auditar cada latido llenaría la bitácora de «sigue vivo»;
- la **telemetría** aceptada;
- el **422** de validación del cuerpo y el **413** del límite global, que no llegan a la API de
  agentes (ver arriba);
- el 404 del interruptor apagado y el 405.

Los asientos nunca contienen contraseñas. En la bitácora el agente figura como `agente:<nombre>`;
un rechazo sin identidad, como `agente:desconocido`.

---

## `POST /api/agent/enrolar`

Canjea el **token de enrolamiento de un solo uso** por la identidad del agente. No lleva
`Authorization`. El token de enrolamiento queda **anulado** al canjearse: un segundo uso responde 401.

**Cuerpo:**

| Campo | Tipo | Máx. | Descripción |
|---|---|---|---|
| `token_enrolamiento` | string | 200 | El token mostrado en el panel. |
| `clave_publica` | string | 100 | Clave pública **X25519** del agente: 32 bytes en **base64 estándar**. El par lo genera el agente en ese momento; la privada no sale del activo. |
| `nombre_host` | string | 255 | Nombre del host, informativo. |
| `version` | string | 40 | Versión del agente (`X.Y.Z`). |

**Respuesta `200`:**

```json
{
  "agente_id": 7,
  "nombre": "agente-srv-bd-nomina",
  "token": "<token del agente>",
  "token_expira_en": "2026-11-27T10:00:00",
  "intervalo_min": 15
}
```

| Campo | Descripción |
|---|---|
| `token` | Identidad del agente. Se entrega **esta única vez**; en el servidor solo queda su hash. |
| `token_expira_en` | Caducidad de la identidad (UTC). |
| `intervalo_min` | Cadencia de latido que debe seguir el agente (`agentes_telemetria_intervalo_min`). |

**Errores:**

| Código | Cuándo | `detail` |
|---|---|---|
| `400` | La clave pública no es base64 válido o no mide 32 bytes | `La clave pública del agente no es base64 válido.` · `La clave pública del agente debe ser X25519 (32 bytes).` |
| `401` | Token inexistente o ya canjeado | `Token de enrolamiento no válido o ya usado.` |
| `401` | Token caducado (más de 1 h desde su emisión) | `El token de enrolamiento caducó: emita otro desde el panel.` |
| `413` | Cuerpo de más de 4 KiB | `La petición excede 4096 bytes.` |
| `422` | Un campo excede su longitud máxima o el JSON no es válido | lista de errores |
| `429` | Límite por dirección o de enrolamiento | `Demasiadas peticiones desde esta dirección.` · `Demasiados intentos de enrolamiento desde esta dirección.` |

### Ejemplo

En la práctica lo hace el instalador (`passwd-agente enrolar --token …`). A mano, solo para
diagnóstico:

```bash
curl -s https://passwd.su-organizacion.tld/api/agent/enrolar \
  -H "Content-Type: application/json" -H "Accept: application/json" \
  -d '{"token_enrolamiento":"<token de enrolamiento>",
       "clave_publica":"<clave pública X25519 en base64>",
       "nombre_host":"srv-bd-nomina","version":"1.4.0"}'
```

---

## `POST /api/agent/saludo`

El **latido**. Registra el contacto del agente (fecha e IP), actualiza su versión y, si toca,
**renueva su identidad**. Es `POST` y no `GET` porque escribe.

**Cuerpo:**

| Campo | Tipo | Máx. | Descripción |
|---|---|---|---|
| `version` | string | 40 | Versión del agente. Vacía, se conserva la anterior. |

**Respuesta `200`:**

```json
{
  "token_nuevo": null,
  "token_expira_en": "2026-11-27T03:04:57",
  "intervalo_min": 15,
  "version_minima": "",
  "version_admitida": true,
  "version_en_gracia": false
}
```

| Campo | Descripción |
|---|---|
| `token_nuevo` | `null`, o un token nuevo. Se emite cuando al token le queda **un cuarto o menos** de su vida, o cuando el agente entró con el **token anterior** (señal de que no recibió el último). El agente debe usarlo desde la petición siguiente y guardarlo. |
| `token_expira_en` | Caducidad del token vigente (el nuevo, si lo hay). |
| `intervalo_min` | Cadencia de latido. |
| `version_minima` | Versión mínima exigida (`agentes_version_minima`), o `""` si no hay. |
| `version_admitida` | `false`: el agente no recibirá trabajos hasta actualizarse. |
| `version_en_gracia` | `true`: está por debajo del mínimo pero dentro del período de gracia. |

**Renovación y solapamiento.** Tras emitir un token nuevo, el que estaba vigente sigue valiendo
**30 minutos**. Si el agente se presenta con él en ese plazo, el saludo le emite otro token nuevo.
Si la renovación llega desde una IP distinta de la anterior, se registra `agente_anomalia_ip` y,
salvo que `agentes_alertar_ip_distinta` esté apagado, se avisa al equipo de seguridad.

**Errores:** `401`, `413`, `422`, `429` (ver las tablas anteriores).

### Ejemplo

```bash
curl -s https://passwd.su-organizacion.tld/api/agent/saludo \
  -H "Authorization: Bearer $TOKEN_AGENTE" \
  -H "Content-Type: application/json" -H "Accept: application/json" \
  -d '{"version":"1.4.0"}'
```

---

## `GET /api/agent/trabajos/pendiente`

Devuelve el **trabajo de rotación** del agente, **sellado** a su clave pública, o `204` si no tiene
ninguno. Antes de responder cierra lo que haya vencido para ese agente (un pendiente sin recoger
vuelve a quedar autorizado; un entregado sin resultado pasada su ventana y 15 minutos queda «sin
confirmar»). Refresca el «último contacto».

**Sin cuerpo.**

**Respuesta `200`:**

```json
{
  "trabajo_id": 42,
  "expira_en": "2026-11-26T10:15:00",
  "sobre": {
    "v": 1,
    "efimera": "<clave efímera X25519 en base64>",
    "token": "<token Fernet>"
  }
}
```

| Campo | Descripción |
|---|---|
| `trabajo_id` | Identificador del trabajo; debe coincidir con el del contenido del sobre. |
| `expira_en` | Fin de la ventana de validez (`rotacion_ventana_job_min`, 30 min por omisión desde el despacho). Pasado ese momento el agente no lo aplica. |
| `sobre` | El trabajo cifrado a la clave del agente: X25519 + HKDF-SHA256 + Fernet. Esquema exacto en [`contrato-agente.md`](contrato-agente.md) §6; vector de prueba en [`tests/vectores/cifrado_agente.json`](../tests/vectores/cifrado_agente.json). |

**Contenido del sobre, una vez abierto:**

```json
{
  "trabajo_id": 42,
  "tipo": "rotar_cuenta",
  "usuario": "deploy",
  "nueva": "<contraseña nueva>",
  "actual": "<contraseña actual>",
  "expira_en": "2026-11-26T10:15:00"
}
```

`rotar_cuenta` es el único tipo. Las reglas que el agente aplica a cada campo están en
[`contrato-agente.md`](contrato-agente.md) §5.2.

**Respuesta `204`** (sin cuerpo) cuando:

- el agente no tiene trabajo asignado;
- su trabajo ya pasó su ventana;
- su versión no está admitida.

**Entrega y re-entrega.** La primera entrega marca el trabajo como `entregado`. Mientras la ventana
siga abierta, pedirlo de nuevo devuelve **el mismo trabajo** con un sobre nuevo (clave efímera
distinta) e incrementa su contador de intentos: si el agente se reinició tras recibirlo, su journal
decide con el `trabajo_id` si ya lo había empezado. Cada entrega se audita.

**Errores:** `401`, `413`, `429`.

### Ejemplo

```bash
curl -s -o trabajo.json -w '%{http_code}\n' \
  https://passwd.su-organizacion.tld/api/agent/trabajos/pendiente \
  -H "Authorization: Bearer $TOKEN_AGENTE" -H "Accept: application/json"
```

Imprime `200` (y deja el sobre en `trabajo.json`) o `204`. El sobre solo se abre con la clave
privada del agente.

---

## `POST /api/agent/trabajos/{trabajo_id}/resultado`

Cierra el trabajo con lo que informa el agente. **Un resultado por trabajo** (anti-replay), y solo
el agente al que pertenece.

**Cuerpo:**

| Campo | Tipo | Máx. | Valores |
|---|---|---|---|
| `estado` | string | 20 | `aplicado` · `revertido` · `fallado` |
| `verificacion` | string | 20 | `local` (por omisión) · `ninguna`. Un agente no puede declarar `remota`. |
| `detalle` | string | 2000 | Motivo legible, **sin contraseñas**. Opcional. |

| `estado` | Significado | Efecto en el backend |
|---|---|---|
| `aplicado` | La contraseña nueva autentica la cuenta en el activo. | Escribe la nueva en la credencial por el punto único de escritura, archiva la anterior en el historial, reinicia la antigüedad y cierra la rotación. Audita `rotacion_aplicada`. |
| `revertido` | La nueva no verificó y se restauró la anterior. | No toca la contraseña registrada; cierra la rotación y alerta. |
| `fallado` | No se aplicó (trabajo rechazado por el contrato, la actual no coincidía…) o el estado de la cuenta requiere intervención. | No toca la contraseña registrada; cierra la rotación y alerta. |

En los tres casos se purgan los secretos del trabajo. Con `aplicado`, el libro mayor guarda la
verificación declarada; con `revertido` o `fallado`, siempre `ninguna`.

**Respuesta `200`:**

```json
{"trabajo_id": 42, "estado": "aplicado"}
```

**Errores:**

| Código | Cuándo | `detail` |
|---|---|---|
| `400` | `estado` no es uno de los tres | `Resultado desconocido: <estado>.` |
| `400` | `verificacion` no es `local` ni `ninguna` | `Un agente solo puede declarar verificación local.` |
| `401` | Identidad | ver «Autenticación» |
| `403` | El trabajo es de otro agente | `Ese trabajo no es de este agente.` |
| `404` | No existe ese trabajo | `No existe ese trabajo.` |
| `409` | El trabajo no está `entregado`: ya tiene resultado, se resolvió a mano, venció sin recogerse o se canceló | `Este trabajo ya está en «<estado>».` |
| `413` | Cuerpo de más de 4 KiB | `La petición excede 4096 bytes.` |
| `422` | `trabajo_id` no es un entero, un campo excede su longitud o el JSON no es válido | lista de errores |
| `429` | Límites | ver «Límites de tasa» |

Un **409**, **404** o **403** significa que no hay nada que entregar: el agente descarta el
resultado y purga su journal. Cualquier otro error, o un fallo de red, lo conserva para reintentar
en el ciclo siguiente.

Un resultado tardío —después de la ventana, incluso con el trabajo marcado «sin confirmar»— se
acepta mientras el trabajo siga `entregado`: es la mejor evidencia de lo que quedó en el activo.

### Ejemplo

```bash
curl -s https://passwd.su-organizacion.tld/api/agent/trabajos/42/resultado \
  -H "Authorization: Bearer $TOKEN_AGENTE" \
  -H "Content-Type: application/json" -H "Accept: application/json" \
  -d '{"estado":"aplicado","verificacion":"local","detalle":""}'
```

---

## `POST /api/agent/telemetria`

Instantánea **agregada** del host: métricas y hardware. La telemetría informa, **nunca dispara
nada**. Refresca el «último contacto» (fecha e IP). Se conserva `agentes_retencion_telemetria_dias`
(30 por omisión).

**Cuerpo** (todos los campos son opcionales; `null` si no se pudieron leer):

| Campo | Tipo | Máx. en la petición | Qué guarda el servidor |
|---|---|---|---|
| `cpu_pct`, `ram_pct`, `disco_pct` | entero | — | Acotado a 0–100. El agente de referencia envía en `disco_pct` el uso de `/`. |
| `uptime_s` | entero | — | Segundos; negativo pasa a 0. |
| `sistema_operativo`, `kernel`, `cpu_modelo` | string | 255 | Primeros 120 caracteres. |
| `ram_total` | entero | — | Bytes; negativo pasa a 0. |
| `discos` | lista | 256 elementos | Los 32 primeros; si había más, marca `recortada`. |
| `discos[].montaje` | string | 255 | Primeros 120 caracteres. |
| `discos[].sistema_archivos` | string | **60** | Primeros 120 caracteres. |
| `discos[].total_bytes` | entero | — | Negativo pasa a 0. |
| `discos[].usado_pct` | entero | — | Acotado a 0–100. |
| `recortada` | booleano | — | `true` si el agente tuvo que recortar algo; el servidor también lo marca si recorta él. |

Nada de procesos, usuarios, sesiones ni rutas más allá del punto de montaje de cada disco. Lo que no
cabe en los topes de contenido se **recorta y se marca**, no se rechaza: una métrica incompleta es
mejor que un agente que deja de informar. Lo que excede el **tope de cuerpo** (16 KiB) o la longitud
máxima de un campo sí se rechaza (413 o 422).

**Respuesta `204`** (sin cuerpo).

**Errores:** `401`, `413` (`La telemetría excede 16384 bytes: recórtela en el agente.`), `422`, `429`.

### Ejemplo

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  https://passwd.su-organizacion.tld/api/agent/telemetria \
  -H "Authorization: Bearer $TOKEN_AGENTE" \
  -H "Content-Type: application/json" -H "Accept: application/json" \
  -d '{"cpu_pct":12,"ram_pct":40,"disco_pct":61,"uptime_s":86400,
       "sistema_operativo":"debian 12","kernel":"6.1.0","cpu_modelo":"Xeon",
       "ram_total":17179869184,
       "discos":[{"montaje":"/","sistema_archivos":"ext4",
                  "total_bytes":107374182400,"usado_pct":61}],
       "recortada":false}'
```

---

## Ciclo típico de un agente

1. `POST /api/agent/saludo` → guardar `token_nuevo` si viene; adoptar `intervalo_min`.
2. `POST /api/agent/telemetria`.
3. Si `version_admitida` es `false`, esperar al ciclo siguiente.
4. Si el journal guarda un resultado sin entregar, reintentar
   `POST /api/agent/trabajos/{id}/resultado` y **no** pedir trabajo nuevo hasta entregarlo.
5. `GET /api/agent/trabajos/pendiente` → `204`: esperar `intervalo_min`; `200`: abrir el sobre,
   validar, aplicar en dos fases y `POST …/resultado`.
6. Ante un error de red, reintentar al minuto; ante un 401, avisar de que hay que re-enrolar.

El detalle normativo de cada paso está en [`contrato-agente.md`](contrato-agente.md) §7 y §8.

## Errores frecuentes

| Síntoma | Causa probable |
|---|---|
| `404` en todo el prefijo | `agentes_enabled` apagado. |
| `404` con una página HTML | Además, la petición no llevaba `Accept: application/json`. |
| `401` en el saludo de un agente que funcionaba | La identidad caducó (el agente estuvo apagado más de su vida) o se revocó. Reemita el enrolamiento desde la ficha del activo. |
| `401` al enrolar | Token de enrolamiento ya usado o con más de una hora. Emita otro. |
| `204` aunque el panel muestra una rotación despachada | La versión del agente no está admitida, o la ventana del trabajo ya pasó. |
| `422` en la telemetría | Un campo excede su máximo (por ejemplo, más de 256 discos). Los textos largos no dan 422: el agente los recorta a 120 caracteres y el servidor vuelve a acotarlos. |
| `429` de muchos agentes a la vez | Comparten dirección por un proxy no declarado en `PASSWD_TRUSTED_PROXIES`, o hay varios procesos sin `PASSWD_RATE_LIMIT_BACKEND=bd`. |

---

## Documentos relacionados

- [`contrato-agente.md`](contrato-agente.md) — lo que agente y backend deben y no deben hacer.
- [`arquitectura-agentes.md`](arquitectura-agentes.md) — arquitectura de los agentes y modelo de amenaza.
- [`guia-instalacion-agente-linux.md`](guia-instalacion-agente-linux.md) — instalación y enrolamiento del agente Linux.
- [`referencia-api-rest.md`](referencia-api-rest.md) — API de solo lectura `/api/v1` (sin cambios).
- [`referencia-configuracion.md`](referencia-configuracion.md) — `PASSWD_AGENTES_*`, `PASSWD_ROTACION_VENTANA_JOB_MIN`, `PASSWD_ROTACION_ANTI_THRASH_HORAS`.
- [`plan-rotacion-agentes.md`](plan-rotacion-agentes.md) §3.3 — diseño de esta API.
- Pruebas: [`tests/test_api_agente.py`](../tests/test_api_agente.py), [`tests/test_despacho_agentes.py`](../tests/test_despacho_agentes.py),
  [`tests/test_servicio_agentes.py`](../tests/test_servicio_agentes.py); trazabilidad criterio → prueba en la cabecera de
  [`tests/test_aceptacion_agentes.py`](../tests/test_aceptacion_agentes.py).
