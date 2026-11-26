# Arquitectura de los agentes de rotación

**Sistema:** Gestor de Contraseñas de Servidores
**Versión:** 1.4.0 (agente Linux)
**Audiencia:** quien opera, audita o revisa el sistema y necesita entender cómo una rotación
autorizada llega a cambiar la contraseña de una cuenta Linux real.
**Propósito:** explicar cómo encajan las piezas, qué recorre una rotación de punta a punta, qué
estados existen, qué protege cada frontera de confianza y qué garantiza la base de datos.

> El **porqué** de cada decisión está en [`plan-rotacion-agentes.md`](plan-rotacion-agentes.md)
> (§1.7 H14 y H15, §2, §4, §5 y §8.2). Lo que el agente puede y no puede hacer, en forma
> normativa, está en [`contrato-agente.md`](contrato-agente.md); los endpoints de `/api/agent`,
> con sus cuerpos y códigos, en [`referencia-api-agent.md`](referencia-api-agent.md). La
> instalación paso a paso, en [`guia-instalacion-agente-linux.md`](guia-instalacion-agente-linux.md).
> Este documento describe **lo que hace el código**; donde el plan dice otra cosa, manda el código.

---

## 1. Visión de conjunto

La 1.3.0 introdujo la gobernanza de dos administradores: una persona **solicita** la rotación con
motivo, otra distinta la **autoriza** reautenticándose con aplicación autenticadora, y una persona
cambia después la contraseña a mano en el activo y la registra. La 1.4.0 añade una segunda forma
de ejecutar el último paso: si la credencial **rota por agente**, la rotación autorizada se
**despacha** al agente instalado en el activo, que la aplica, la verifica, confirma o revierte, e
informa. El backend sigue siendo el único que escribe la contraseña en el inventario.

```
                       navegador (panel Next.js)
                                │  sesión + CSRF + RBAC
                                ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ backend FastAPI                                                              │
│  /api/web/agentes, /api/web/rotacion   ──►  app/servicios/agentes.py          │
│  /api/agent  (Bearer por agente)       ──►  app/servicios/rotacion.py         │
│                                              (único punto que escribe         │
│  mantenimiento periódico (cada 6 h)          Credencial.password_cifrada)     │
│  tablas: agentes, trabajos_rotacion, telemetria_agente, rotaciones_credencial │
└──────────────────────────────────────────────────────────────────────────────┘
                                ▲
                                │ HTTPS, solo saliente, el agente pregunta (pull)
                                │ latido · trabajo sellado · resultado · telemetría
┌───────────────────────────────┼──────────────────────────────────────────────┐
│ servidor Linux                │                                              │
│  passwd-agente.service  (usuario passwd-agente, sin privilegios)             │
│     identidad.json 0600 · journal.bin cifrado      IPAddressAllow = backend  │
│                │                                                             │
│                │ /run/passwd-agente/helper.sock  (0660, grupo del agente)    │
│                ▼                                                             │
│  passwd-agente-helper.socket ──Accept=yes──► passwd-agente-helper@.service   │
│     root, sin red (PrivateNetwork), una petición por conexión                │
│     helper.json de root (lista exacta de cuentas) · PAM (solo pam_unix)      │
│     · chpasswd                                                               │
└──────────────────────────────────────────────────────────────────────────────┘
```

Lo que **no** hace: el agente no escucha en la red, no ejecuta órdenes del backend, no crea
cuentas, no decide rotar por su cuenta y no se configura desde la red. Los dispositivos de red no
admiten agente (`app/servicios/agentes.py`, `MODELOS_ACTIVO`): los cubrirán los conectores de la
2.3.0.

---

## 2. Componentes

### 2.1 Backend

| Pieza | Archivo | Responsabilidad |
|---|---|---|
| API de los agentes | `app/api_agent/__init__.py` | `POST /api/agent/enrolar`, `POST /saludo`, `GET /trabajos/pendiente`, `POST /trabajos/{id}/resultado`, `POST /telemetria`. Solo traduce HTTP ↔ servicio. Con `agentes_enabled` apagado, **todo el prefijo responde 404**. Tope de cuerpo de 4 KiB (16 KiB la telemetría), límite de 120 peticiones por agente y 300 por IP cada 5 min, y 10 enrolamientos por IP cada 15 min. Detalle en [`referencia-api-agent.md`](referencia-api-agent.md). |
| Servicio de agentes | `app/servicios/agentes.py` | Alta, enrolamiento, identidad de vida corta y su renovación, revocación, cobertura derivada, versión mínima, vía de rotación de una credencial, telemetría y aviso de agentes sin contacto. |
| Servicio de rotación | `app/servicios/rotacion.py` | El ciclo de gobernanza de la 1.3.0 más el despacho, la entrega sellada, el resultado, la expiración y la resolución manual de un trabajo. Sigue siendo el **único** que escribe `Credencial.password_cifrada` (`_escribir_password`). |
| Cifrado del trabajo | `app/servicios/cifrado_agente.py` | Sella el trabajo a la clave X25519 del agente al entregarlo (§5, H14). |
| Panel en JSON | `app/api_web/agentes.py`, `app/api_web/rotacion.py` | Alta y reemisión del token de instalación (con reautenticación), revocación (sin ella), vía de rotación de una credencial, cobertura de un activo, reenvío de una rotación autorizada al agente (`/despachar`) y resolución de un «sin confirmar» (con reautenticación). |
| Mantenimiento | `app/main.py`, `ejecutar_mantenimiento` | Al arrancar y cada 6 h (`INTERVALO_MANTENIMIENTO_S`): expira trabajos, purga la telemetría antigua y avisa de los agentes sin contacto. |
| Respaldo | `app/backup.py` | Respalda los agentes como historia; nunca los trabajos ni la telemetría (§9). |

Permisos (`app/rbac.py`): `agentes.ver` lo tienen administrador, operador y auditor;
`agentes.gestionar`, solo el administrador.

### 2.2 Panel (frontend)

| Dónde | Archivo | Qué hay |
|---|---|---|
| Ficha del servidor físico, hipervisor o VM | `frontend/src/components/agentes/panel-agente-activo.tsx` | Tarjeta «Agente de rotación» con la insignia de cobertura, nombre, host, versión, «Último latido», «Identidad válida hasta» y huella de la clave. Botones «Dar de alta un agente», «Reinstalar» y «Revocar». |
| Token de instalación | `frontend/src/components/agentes/token-una-vez.tsx` | El token, visible **una vez**, con la orden de instalación sugerida y el botón «Ya lo he guardado». |
| `/agentes` | `frontend/src/app/(app)/agentes/page.tsx` | El parque entero: estado, versión, último latido y trabajo en curso (marcado «sin confirmar» en rojo). Casilla «Mostrar también los revocados». |
| Credencial | `frontend/src/components/rotacion/panel-credencial.tsx` | «Vía de rotación» con «Rotar con el agente» / «Rotar a mano», el botón «Rotar ahora», «Enviar al agente» y la resolución de un «Sin confirmar». |
| `/rotacion` | `frontend/src/app/(app)/rotacion/page.tsx` | Tarjeta «Rotaciones sin confirmar». |
| `/metricas` | `frontend/src/app/(app)/metricas/page.tsx` | Tarjeta «Agentes de rotación» (§11). |

Las insignias (`frontend/src/lib/agentes.ts`) solo ponen nombre y color a lo que calcula el
backend: «Sin agente», «Pendiente de instalar», «Conectado», «Sin contacto» e «Identidad
caducada».

### 2.3 Agente (`passwd-agente`)

Binario Go estático (`CGO_ENABLED=0`) que corre como el usuario de sistema `passwd-agente`, sin
capacidades ni forma de ganarlas. Órdenes: `enrolar`, `ejecutar` y `version`
(`agente/cmd/passwd-agente/main.go`).

| Paquete | Responsabilidad |
|---|---|
| `internal/config` | Lee `/etc/passwd-agente/config.json` (campos desconocidos = error). `backend` solo `https`; `http` únicamente hacia loopback. `anti_thrash_min` por omisión 60. |
| `internal/identidad`, `internal/archivo` | Identidad (`agente_id`, nombre, token y su caducidad, clave privada X25519) escrita de forma atómica con 0600; no se lee si alguien abrió sus permisos. |
| `internal/cliente` | HTTPS hacia `<backend>/api/agent/…`: TLS ≥ 1.2, CA del sistema o `ca_file`, pin SPKI opcional comprobado **además** de la cadena, sin seguir redirecciones, respuestas de 256 KiB como máximo. |
| `internal/sobre` | Abre el sobre sellado (X25519 + HKDF-SHA256 + Fernet), verificado contra los mismos vectores que el backend (`tests/vectores/cifrado_agente.json`). |
| `internal/contrato` | Decide si un trabajo se puede ejecutar **antes** de tocar nada (§3, paso 5). |
| `internal/journal` | Trabajo en curso cifrado con AES-256-GCM y una clave derivada por HKDF de la clave privada del agente. |
| `internal/ejecutor` | El bucle: latido → telemetría → recuperación del journal → trabajo → dos fases → resultado → purga. |
| `internal/rotador` | Habla con el helper por su socket (30 s por petición como máximo). |
| `internal/telemetria` | CPU, RAM y disco agregados, tiempo encendido, SO, kernel, CPU, RAM total y discos; recortado a 12 KiB antes de enviar. |

Sin `helper` en la configuración, el agente solo late y envía telemetría: no pide trabajos.

### 2.4 Helper root (`passwd-agente-helper`)

Binario con cgo (enlaza `libpam`). systemd lo arranca **por cada conexión** al socket
(`Accept=yes`), le pasa la conexión como entrada y salida estándar, atiende **una** petición JSON
(`verificar`, `aplicar` o `restaurar`) y termina (`agente/cmd/passwd-agente-helper/main.go`,
`agente/internal/helper/helper.go`). Es el único componente con privilegios. Verifica con PAM
(servicio propio `passwd-agente-helper`, solo `pam_unix`, sin `faillock`) y fija con
`/usr/sbin/chpasswd`, con la contraseña por la entrada estándar y entorno limpio.

---

## 3. Una rotación de punta a punta

```mermaid
sequenceDiagram
    participant S as Solicitante
    participant A as Autorizador
    participant B as Backend
    participant G as Agente
    participant H as Helper root
    S->>B: «Rotar ahora» con motivo
    B-->>B: asiento SOLICITADA
    A->>B: «Autorizar» + contraseña + código TOTP
    B-->>B: AUTORIZADA → despachar: trabajo PENDIENTE (Fernet del backend), asiento DESPACHADA
    G->>B: POST /saludo, POST /telemetria
    G->>B: GET /trabajos/pendiente
    B-->>G: sobre sellado a la clave X25519 del agente (trabajo ENTREGADO)
    G-->>G: abre el sobre, valida el contrato, journal «aplicando»
    G->>H: aplicar (actual → nueva)
    H-->>G: ok / error
    G->>H: verificar nueva [y, si no vale, actual; restaurar]
    G-->>G: journal «cerrada» con el resultado
    G->>B: POST /trabajos/{id}/resultado
    B-->>B: escribe la nueva, historial, libro mayor CERRADA, purga secretos
    G-->>G: purga el journal
```

1. **Solicitud.** Quien tiene `rotacion.solicitar` pulsa «Rotar ahora» en la credencial (con la vía
   «Agente del activo», el botón de la 1.3.0 «Solicitar rotación» se llama así) e indica motivo y
   tipo. Se crea el asiento `SOLICITADA` en el libro mayor `rotaciones_credencial`. Nada se toca.
2. **Autorización.** Otro administrador pulsa «Autorizar» y se reautentica con su contraseña y un
   código de aplicación autenticadora (`app/servicios/autenticacion.py`, `reautenticar`; el código
   por correo no sirve). El asiento pasa a `AUTORIZADA` y, como la credencial rota por agente, se
   intenta el despacho en el mismo momento (`_intentar_despacho`).
3. **Despacho** (`despachar`). Exige: interruptor encendido, asiento `AUTORIZADA`, credencial con
   vía `agente`, agente vigente **del activo de esa credencial** en estado `activo`, identidad no
   caducada, rotaciones habilitadas en el agente, versión admitida, ningún otro trabajo activo de
   ese agente y el anti-thrash del backend (§7). El backend genera la contraseña nueva con su
   generador (CSPRNG, `app/security/passwords.py`) y crea un `TrabajoRotacion` `pendiente` con la
   nueva y la actual **cifradas con el Fernet del backend** y una ventana de validez
   (`rotacion_ventana_job_min`, 30 min). El asiento pasa a `DESPACHADA`. Si algo falla, la
   autorización **se mantiene**: queda el asiento de bitácora `rotacion_no_despachada` con el
   motivo, y el panel ofrece «Enviar al agente» (vuelve a llamar a `despachar`) o registrar la
   rotación a mano.
4. **Entrega sellada** (`entregar`). En cada ciclo (cada `agentes_telemetria_intervalo_min`, 15 min
   por omisión) el agente envía su latido y su telemetría, resuelve lo que su journal tenga a medias
   y pide trabajo. El backend expira lo vencido de ese agente, marca el trabajo `entregado`, cuenta
   el intento y lo **sella a la clave pública X25519 del agente**. Mientras la ventana siga abierta,
   el mismo trabajo se vuelve a entregar al mismo agente: si se reinició tras recibirlo, su journal
   decide con el `trabajo_id` qué hacer.
5. **Contrato.** El agente abre el sobre y comprueba (`agente/internal/contrato/contrato.go`): tipo
   `rotar_cuenta` y ningún otro; identificador; ningún otro trabajo en curso en su journal; ventana
   no vencida (con el reloj **del servidor**); cuenta con el patrón `^[a-z_][a-z0-9_.-]{0,31}$`;
   contraseñas no vacías, de 256 bytes como máximo, UTF-8 y sin saltos de línea ni NUL; nueva
   distinta de la actual; y el anti-thrash local (§7). Un trabajo que no pasa se informa como
   `fallado` con el motivo y no se ejecuta.
6. **Fase 1: journal.** El agente escribe en el journal la entrada `aplicando` **antes** de tocar la
   cuenta. Si no puede escribirlo, no toca la cuenta e informa `fallado`.
7. **Fase 2: aplicar y decidir.** Pide al helper `aplicar`. El helper comprueba quién llama
   (`SO_PEERCRED`), que la cuenta esté en su lista y exista, que la contraseña **actual del
   inventario** autentique por PAM, y solo entonces fija la nueva con `chpasswd`.

   - Si el helper **rechaza la petición antes de tocar la cuenta** (cuenta fuera de la lista o
     inexistente, la actual del inventario no autentica, petición mal formada, llamante no
     autorizado), lo dice con la marca `sin_cambios` y el agente cierra el trabajo como `fallado`
     con el detalle «no se cambió nada: <motivo>». No comprueba ni restaura nada: la cuenta sigue
     como estaba.
   - Si no, el agente decide qué quedó (`ejecutor.go`, `decidir`):

   | Comprobación | Resultado que informa |
   |---|---|
   | La nueva autentica | `aplicado`, verificación `local` |
   | La nueva no, la actual sí | `fallado`: «la contraseña nueva no se aplicó; la cuenta conserva la anterior» |
   | Ninguna autentica → `restaurar` la actual → la actual autentica | `revertido`: «la contraseña nueva no verificó y se restauró la anterior» |
   | Ninguna autentica, ni tras restaurar | `fallado`: «ni la contraseña nueva ni la anterior autentican la cuenta: requiere intervención manual» |

   Una respuesta «no autentica» del helper es un dato; un helper que **no contesta** (socket
   inactivo, error de PAM o de su configuración) no lo es. En ese caso el agente no concluye nada:
   deja el journal en `aplicando`, registra «no se puede saber qué contraseña quedó; se
   reintentará» y lo vuelve a intentar cada minuto. Si no lo consigue antes de que venza la
   ventana más el margen, el backend lo marca «sin confirmar» (§4.5).
8. **Resultado.** El agente guarda el resultado en el journal (fase `cerrada`) y lo informa. Si el
   backend lo acepta, o responde 409, 404 o 403 (ya cerrado, por ejemplo resuelto a mano,
   inexistente o ajeno) o 400 o 422 (un resultado que nunca admitirá), purga el journal y, si fue
   `aplicado`, apunta la hora para su anti-thrash; en los casos descartados, el backend lo verá
   «sin confirmar» si seguía abierto. Si no hay red, el resultado espera en el journal, se
   reintenta cada minuto y **no se acepta trabajo nuevo** mientras tanto. Lo pendiente del journal
   se entrega siempre, también si la versión del agente ha dejado de estar admitida.
9. **Libro mayor y purga** (`registrar_resultado`). El backend admite un único resultado por
   trabajo, solo del agente dueño y solo si está `entregado` (anti-replay). Con `aplicado` escribe
   la nueva por `_escribir_password`: la anterior pasa a `HistorialCredencial`, se reinicia
   `password_rotada_en` y el asiento registra los días que duró la anterior y su desviación
   respecto a la política. El asiento queda `CERRADA` con resultado `aplicada`, `revertida` o
   `fallada`. El trabajo se cierra y **sus dos contraseñas cifradas se ponen a NULL**. Si no fue
   `aplicado`, se envía una alerta (§10).

**Caída a mitad.** Al rearrancar, el agente lee su journal: con la entrada `aplicando`, vuelve a
decidir qué contraseña vale (paso 7) y la informa; con `cerrada`, solo la informa. Nunca queda un
estado indeterminado en silencio; si el agente no vuelve, el backend lo marca «sin confirmar»
(§4.5).

---

## 4. Estados

### 4.1 Agente (lo que se guarda)

```
alta en el panel ──► pendiente ──enrolar (token de un uso, 1 h)──► activo ──revocar──► revocado
                        ▲                                            │
                        └──────────── «Reinstalar» (reemitir) ───────┘
```

| Estado | Significado |
|---|---|
| `pendiente` | Dado de alta; tiene un token de instalación de un solo uso que caduca en 1 h (`VIDA_ENROLAMIENTO`). También tras «Reinstalar», que **anula la identidad vigente** al momento. |
| `activo` | Enrolado: tiene clave pública X25519 e identidad. La identidad es un token de `agentes_token_vida_horas` (24 h) del que solo se guarda el hash; se renueva en el latido cuando le queda un cuarto de vida o menos, y el anterior sigue valiendo 30 min (`SOLAPAMIENTO`). |
| `revocado` | Sin identidad; se conserva como historia. Un revocado no se puede volver a enrolar: hay que dar de alta otro (con **otro nombre**: el nombre es único también entre revocados). |

### 4.2 Cobertura (derivada, nunca guardada)

`cobertura()` en `app/servicios/agentes.py` se calcula en cada consulta a partir de las fechas: la
insignia no puede mentir porque un proceso de fondo dejara de correr.

| Valor | Insignia | Condición, en este orden |
|---|---|---|
| `sin_agente` | «Sin agente» | El activo no tiene agente, o está revocado. |
| `pendiente` | «Pendiente de instalar» | Estado `pendiente`. Si además caducó el token de instalación, el panel añade «Token de instalación caducado: reinstálelo». |
| `caducado` | «Identidad caducada» | `token_expira_en` vencido. Hay que reinstalarlo con un token nuevo. |
| `sin_contacto` | «Sin contacto» | Último contacto más antiguo que `agentes_umbral_sin_contacto_horas` (1 h). |
| `conectado` | «Conectado» | Lo demás. |

> **El orden en que se ve un agente que deja de latir.** Con los valores por omisión pasa a
> «Sin contacto» a la hora (cuatro latidos perdidos) y a «Identidad caducada» entre 6 y 24 h
> después del último latido: la identidad dura 24 h y solo se renueva en sus últimas 6 h. La
> caducidad se comprueba antes que el silencio, así que el umbral de «sin contacto» **debe** ser
> menor que la vida de la identidad; si no, la etapa intermedia no se vería nunca
> (`tests/test_servicio_agentes.py::test_los_valores_por_omision_dejan_ver_cada_estado`).

En la lista `/agentes`, un agente revocado aparece con la insignia «Revocado».

### 4.3 Trabajo (`trabajos_rotacion`)

```
pendiente ──entregar──► entregado ──resultado del agente──► aplicado | revertido | fallado
    │                       │
    │                       └─ventana + 15 min sin resultado, o agente revocado─► «sin confirmar»
    │                                                (sigue entregado) ──persona──► aplicado | fallado
    ├─ventana vencida sin recoger──► expirado     (el asiento vuelve a AUTORIZADA)
    └─solicitud cancelada / agente revocado──► cancelado
```

- **Pendiente** vencido: nadie lo recogió. Se purga y el asiento vuelve a `AUTORIZADA`: la
  decisión de dos personas sigue en pie y se puede «Enviar al agente» otra vez.
- **Entregado** no se puede cancelar: el agente puede estar aplicándolo.
- Al revocar un agente: su trabajo pendiente se cancela (el asiento vuelve a `AUTORIZADA`); el
  entregado queda «sin confirmar».
- La expiración es perezosa: se aplica al entregar, al abrir el panel de rotación, la ficha de una
  credencial, la lista de agentes o las métricas, y en el mantenimiento cada 6 h.

### 4.4 Asiento del libro mayor

La 1.4.0 añade el estado `DESPACHADA` al ciclo de la 1.3.0:

```
SOLICITADA ──► AUTORIZADA ──despachar──► DESPACHADA ──resultado──► CERRADA
     │              ▲                        │
     │              └── trabajo expirado ────┘   (o cancelado al revocar el agente)
     └── rechazada / cancelada
```

Una credencial con un asiento `DESPACHADA` no admite otra solicitud ni cambiar su vía de rotación.
Con el trabajo aún `pendiente`, la solicitud se puede cancelar; con el trabajo `entregado`, no.

### 4.5 «Sin confirmar» y su resolución

Un trabajo `entregado` cuyo agente no informó en la ventana más un margen de 15 min
(`MARGEN_CONFIRMACION`), o cuyo agente se revocó, se marca **sin confirmar**: la contraseña pudo
cambiar en el activo o no. **No se purgan sus secretos**, porque la nueva puede ser la que vale
ahora. Se audita (`trabajo_rotacion_sin_confirmar`), se alerta y la credencial queda bloqueada para
otra rotación hasta que alguien lo resuelva.

- Si el agente vuelve y entrega su resultado antes, se acepta: el trabajo sigue `entregado`.
- Si no, un administrador (`rotacion.autorizar`) comprueba el servidor y, en la credencial, pulsa
  «Sí, quedó la nueva» o «No, sigue la anterior», con **reautenticación** (contraseña y código de
  aplicación autenticadora: puede escribir una contraseña en el inventario). Con «sí», la nueva se
  escribe por el punto único; con «no», se descarta. En los dos casos el asiento se cierra
  (`aplicada` o `fallada`, verificación `ninguna`: lo comprobó una persona), los secretos se purgan
  y queda el asiento `trabajo_rotacion_resuelto_a_mano` (`app/servicios/rotacion.py`,
  `resolver_sin_confirmar`).

---

## 5. Fronteras de confianza

| Frontera | Qué la protege | Qué no protege |
|---|---|---|
| **Panel → backend** | Sesión, CSRF y permiso `agentes.gestionar` (solo administrador). Dar de alta un agente o reemitir su token exige **reautenticación** con aplicación autenticadora: crea una identidad de máquina que podrá recibir contraseñas, y una sesión robada no debe bastar. Revocar no la exige: protege. | — |
| **Token de instalación** | Un solo uso, 1 h de vida, solo se guarda su hash y se anula al canjearlo. 10 intentos por IP cada 15 min. | Mientras dura, cualquiera que lo tenga puede enrolar un agente para ese activo. |
| **Agente → backend (red)** | Solo conexiones salientes, `IPAddressAllow` limitado al backend y al DNS, TLS ≥ 1.2 con la CA del sistema o una propia, pin opcional de la clave pública (SPKI) del servidor, sin redirecciones. Identidad Bearer de vida corta con renovación y aviso si se renueva desde otra IP. | Un token copiado del disco vale hasta que caduca (24 h por omisión). |
| **Trabajo en reposo y en tránsito (H14)** | En la base de datos, la nueva y la actual van cifradas con el **Fernet del backend**, como cualquier credencial: al confirmar `aplicado` el backend tiene que escribir la nueva, y no tiene la clave privada del agente. Al **entregarlo**, se sella a la clave X25519 del agente (X25519 efímera + HKDF-SHA256 + Fernet): un token de agente robado sin su clave privada no abre un trabajo. Al cerrarse, los secretos se ponen a NULL. | Quien tenga la base de datos **y** la clave Fernet del backend lee los trabajos en curso, como lee ya todo el inventario. |
| **Agente → helper (H15)** | Sin `sudo` ni binarios setuid: el agente corre con `NoNewPrivileges`, sin capacidades y con `RestrictSUIDSGID`. El helper es un servicio root aparte, activado por un socket que solo el grupo del agente puede abrir (0660) y que comprueba por `SO_PEERCRED` que quien llama es el usuario del agente (o root invocándolo a mano). Corre **sin red** (`PrivateNetwork`), con las capacidades justas para `chpasswd` y PAM, solo puede escribir en `/etc`, atiende una petición de 4 KiB como máximo y vive 60 s como máximo. Una ejecución remota de código en el agente no es root. | Quien controle el proceso del agente puede pedir `restaurar`, que fija un valor **sin comprobar la contraseña actual**, sobre cualquier cuenta **de la lista**: la comprobación de `aplicar` protege la coherencia con el inventario, no es una frontera frente a un agente comprometido. El radio de explosión es la lista de cuentas de ese servidor. |
| **Helper → sistema** | Solo las cuentas de `/etc/passwd-agente/helper.json`, que debe ser de root y no escribible por grupo ni otros (si no, el helper se niega a arrancar); solo cuentas que existen (nunca crea una); servicio PAM propio con solo `pam_unix` y `nodelay`, sin contar fallos para el bloqueo; `chpasswd` por ruta absoluta y la contraseña por la entrada estándar. | La verificación es **local** (PAM): no prueba que la cuenta siga sirviendo por SSH o por el servicio declarado (plan, H4). |
| **Disco del servidor** | `identidad.json` 0600 (el agente no la lee si sus permisos se abrieron); journal cifrado con una clave derivada de la identidad, que solo guarda el trabajo en curso y se purga al cerrarlo. Re-enrolar deja ilegible cualquier resto. | Los bloques antiguos del disco no se sobrescriben: por eso el journal va cifrado. |
| **Configuración** | `config.json` y `helper.json` son de root; el agente puede leer su configuración pero no cambiarla, y nada se configura desde la red. | — |

---

## 6. Invariantes impuestos por la base de datos

Lo que el código podría olvidar, la base de datos lo impide (`app/models.py`):

| Invariante | Mecanismo |
|---|---|
| Un solo agente **vigente** por activo | `agentes.vinculo_vigente` `UNIQUE`: vale `"tipo:id"` (p. ej. `fisico:12`) mientras el agente no está revocado y NULL después. Ni SQLite ni MySQL cuentan los NULL como repetidos, y MySQL no tiene índices parciales: es la forma portable de conservar los revocados como historia sin bloquear al siguiente. |
| Un solo trabajo **activo** por agente | `trabajos_rotacion.activo_agente_id` `UNIQUE`: vale el id del agente mientras el trabajo está `pendiente` o `entregado`, y NULL al cerrarse (`_cerrar_trabajo`). Mismo mecanismo. |
| Un agente pertenece a exactamente un activo, de tres tipos | `CHECK ck_agentes_un_activo`. |
| Estados cerrados | `CHECK ck_agentes_estado`, `ck_trabajos_estado`, `ck_trabajos_verificacion`. |
| Un token identifica a un único agente | `UNIQUE` en `token_hash`, `token_anterior_hash` y `enrolamiento_hash`. |
| Nombres únicos | `agentes.nombre` `UNIQUE`, incluidos los revocados. |

Una sola solicitud abierta por credencial la impone el servicio (`solicitud_abierta`), como en la
1.3.0.

---

## 7. Anti-thrash

Dos frenos independientes contra un bucle de rotaciones:

| | Backend | Agente |
|---|---|---|
| Dónde | `despachar`, en `app/servicios/rotacion.py` | `contrato.Validar`, en `agente/internal/contrato/contrato.go` |
| Intervalo | `rotacion_anti_thrash_horas`: **24 h** por omisión (0 a 720; 0 lo desactiva) | `anti_thrash_min` en `config.json`: **60 min** por omisión. El instalador no lo escribe; un 0 vale 60 y un negativo es error |
| Cuenta desde | `password_rotada_en` de la credencial, venga la rotación anterior de donde venga (también manual) | La última rotación **aplicada** por ese agente a esa cuenta (journal) |
| Excepción | Una solicitud de tipo **emergencia** lo salta; queda el asiento `rotacion_anti_thrash_saltado` | **Ninguna**: el agente no sabe si un trabajo es de emergencia |
| Si frena | No se despacha (409): la autorización se mantiene | El agente informa `fallado`; el asiento se **cierra** como `fallada` y hay que solicitar de nuevo |

---

## 8. Interruptor y ajustes

`agentes_enabled` (variable `PASSWD_AGENTES_ENABLED`, ajuste «Agentes de rotación activos» del
panel) está **apagado por omisión**. Apagado:

- todo `/api/agent` responde 404 (los agentes instalados lo registran como error y reintentan cada
  minuto) y ninguna identidad de agente autentica ni se renueva: si sigue apagado más que la vida
  de la identidad, al volver a encenderlo habrá que reinstalar esos agentes;
- en el panel, el alta, la reemisión del token, «Rotar con el agente» y «Enviar al agente»
  responden 409; una rotación autorizada de una credencial por agente se queda `AUTORIZADA`;
- no se avisa de agentes sin contacto, las métricas de agentes desaparecen y `/agentes` muestra
  «Agentes desactivados»;
- revocar y volver a la vía manual siguen funcionando, y las credenciales manuales se comportan
  exactamente como en la 1.3.0.

Ajustes del grupo de agentes (`app/config.py`, `app/ajustes.py`; editables en caliente):

| Ajuste | Variable | Por omisión |
|---|---|---|
| `agentes_enabled` | `PASSWD_AGENTES_ENABLED` | `false` |
| `rotacion_ventana_job_min` | `PASSWD_ROTACION_VENTANA_JOB_MIN` | 30 min |
| `rotacion_anti_thrash_horas` | `PASSWD_ROTACION_ANTI_THRASH_HORAS` | 24 h |
| `agentes_token_vida_horas` | `PASSWD_AGENTES_TOKEN_VIDA_HORAS` | 24 h |
| `agentes_umbral_sin_contacto_horas` | `PASSWD_AGENTES_UMBRAL_SIN_CONTACTO_HORAS` | 1 h |
| `agentes_telemetria_intervalo_min` | `PASSWD_AGENTES_TELEMETRIA_INTERVALO_MIN` | 15 min |
| `agentes_retencion_telemetria_dias` | `PASSWD_AGENTES_RETENCION_TELEMETRIA_DIAS` | 30 días |
| `agentes_version_minima` | `PASSWD_AGENTES_VERSION_MINIMA` | vacío (cualquiera) |
| `agentes_gracia_version_dias` | `PASSWD_AGENTES_GRACIA_VERSION_DIAS` | 14 días |
| `agentes_alertar_ip_distinta` | `PASSWD_AGENTES_ALERTAR_IP_DISTINTA` | `true` |

**Versión mínima.** Un agente por debajo de `agentes_version_minima` deja de recibir trabajos al
acabar la gracia. La gracia cuenta desde que se fijó el mínimo **en el panel**; fijado por variable
de entorno no hay fecha de la que contar y rige sin gracia. Un agente compilado sin versión
(`dev`) no se puede comparar y, con un mínimo fijado, no recibe trabajos. Referencia completa de
las variables: [`referencia-configuracion.md`](referencia-configuracion.md).

---

## 9. Respaldo y restauración

`app/backup.py` (H12 del plan):

- **Agentes, sí, como historia**: nombre, activo, host, versión, huella de la clave y fechas. Ni
  tokens, ni enrolamiento, ni clave. Se reponen **revocados**, con `vinculo_vigente` NULL: una
  identidad restaurada sería un acceso que nadie ha vuelto a conceder.
- **Trabajos y telemetría, nunca**: un restore no resucita un trabajo con secretos y ventana
  vencida.
- Las credenciales que rotaban por agente vuelven a la vía **manual**.
- Un asiento `DESPACHADA` (respaldo tomado con un trabajo en curso) vuelve a `AUTORIZADA` con una
  nota que pide comprobar el activo y registrar a mano lo que quedó.
- El resumen de la restauración informa de `agentes_repuestos_revocados` y
  `rotaciones_despachadas_reabiertas`.

Tras restaurar hay que dar de alta de nuevo cada agente (con otro nombre) y reinstalarlo.

---

## 10. Alertas y auditoría

Las alertas salen por correo a `PASSWD_NOTIFY_TO` si el correo y las notificaciones están activos
(`app/notifications.py`, `enviar_alerta`), y nunca llevan secretos:

| Alerta | Asunto | Cuándo |
|---|---|---|
| Rotación no aplicada | `[passwd] Rotación revertido\|fallado en <activo>` | El agente informa `revertido` o `fallado`. |
| Sin confirmar | `[passwd] Rotación sin confirmar en <activo>` | Al marcar un trabajo «sin confirmar» (§4.5), lo que ocurre en la siguiente expiración perezosa o en el mantenimiento. |
| IP distinta | `[passwd] Agente <nombre>: identidad renovada desde otra IP` | Dos renovaciones de identidad desde IPs distintas dentro de una misma vida. Se puede apagar (`agentes_alertar_ip_distinta`) por los falsos positivos detrás de un NAT con varias salidas; el asiento `agente_anomalia_ip` se deja siempre. |
| Sin contacto | `[passwd] Agente <nombre> sin contacto` | Desde el **mantenimiento periódico** (al arrancar y cada 6 h), para cada agente activo en «Sin contacto» o «Identidad caducada». Una vez por silencio: vuelve a avisar solo si el agente latió después del aviso anterior. Puede llegar con hasta 6 h de retraso. |

Se audita todo cambio de estado y todo rechazo; el latido rutinario y la consulta sin trabajo no
dejan asiento (quedan como «último contacto»). Acciones nuevas en `app/audit.py`:

| Grupo | Acciones |
|---|---|
| Ciclo del agente | `agente_alta`, `agente_enrolamiento_emitido`, `agente_enrolado`, `agente_enrolamiento_rechazado`, `agente_token_renovado`, `agente_anomalia_ip`, `agente_revocado`, `agente_sin_contacto`, `agente_acceso_rechazado` |
| Despacho | `credencial_via_rotacion_cambiada`, `rotacion_despachada`, `rotacion_no_despachada`, `rotacion_anti_thrash_saltado` |
| Trabajo | `trabajo_rotacion_entregado`, `trabajo_rotacion_resultado`, `trabajo_rotacion_resultado_rechazado`, `trabajo_rotacion_expirado`, `trabajo_rotacion_sin_confirmar`, `trabajo_rotacion_resuelto_a_mano`, `trabajo_rotacion_cancelado` |

Un trabajo aplicado deja además el asiento `rotacion_aplicada` sobre la credencial, como la vía
manual.

---

## 11. Métricas

`GET /api/web/metricas` devuelve un bloque `agentes` (NULL con el interruptor apagado), filtrado
por el control de acceso por objeto (`app/api_web/metrics.py`):

- `por_cobertura`: cuántos agentes vigentes hay `conectado`, `sin_contacto`, `caducado` y
  `pendiente`;
- `atencion`: los que están en «Sin contacto» o «Identidad caducada», con su activo y su último
  contacto;
- `sin_confirmar`: cuántos trabajos esperan que una persona diga qué quedó.

El panel lo muestra en `/metricas`, tarjeta «Agentes de rotación»: «Conectados», «Sin contacto»,
«Identidad caducada», «Pendientes de instalar» y «Rotaciones sin confirmar» (en rojo si hay
alguna), con la tabla de los que piden atención.

La telemetría de cada agente (`telemetria_agente`) solo guarda agregados del propio host, se
conserva `agentes_retencion_telemetria_dias` y la purga el mantenimiento.

---

## 12. Limitaciones conocidas

- **Verificación local** únicamente: la contraseña nueva autentica la cuenta en el sistema
  operativo; la verificación remota contra el servicio declarado llega en la 2.2.0.
- La detección de «sin confirmar» y de agentes sin contacto depende de que alguien abra el panel o
  de que corra el mantenimiento (cada 6 h).
- `IPAddressAllow` se escribe con las direcciones del backend resueltas **al instalar**: si
  cambian, el agente queda sin red hasta que se actualice el drop-in.
- El paquete se comprueba contra un `SHA256SUMS`; la firma de los binarios llega en la 2.3.0.
- Solo Linux con systemd; Windows llega en la 2.1.0.
- **El usuario del agente puede fijar la contraseña de las cuentas de la lista.** `restaurar` no
  comprueba nada (es la vuelta atrás) y `verificar` no tiene retardo ni bloqueo (PAM sin
  `faillock`). Es el alcance que se le da a propósito: quien controle `passwd-agente` ya puede
  rotar esas cuentas. Lo acota la **lista de cuentas**, que es de root; por eso conviene no incluir
  cuentas que no deban rotarse por agente. El instalador **no impide** incluir `root`.
- El **anti-thrash local** (1 h) no conoce la vía de emergencia: una emergencia sobre una cuenta que
  el agente rotó hace menos de una hora se rechaza como `fallado` y hay que rotarla a mano.
- **Reinstalar** un agente con un trabajo ya recogido lo deja «sin confirmar»: la identidad nueva no
  puede leer el journal de la anterior.
- El **nombre** de un agente es único también entre los revocados: para volver a dar de alta un
  activo, use otro nombre.
- Con el interruptor apagado, un método no admitido en `/api/agent` responde 405 en vez de 404, y el
  422 de validación y el 413 del límite global de la aplicación no se auditan.
