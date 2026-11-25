# Plan maestro — Rotación asistida por agentes y monitoreo de activos

**Compilación completa de la consulta** realizada en la ventana de planificación sobre el sistema
v1.2.0. Recoge, desglosada e integrada, toda la información de los planes sucesivos (§1): la
arquitectura de agentes, la gobernanza de autorización, el contrato de límites de seguridad y los
indicadores de cobertura — **segmentado por versiones** (§8), cada una funcional por sí sola,
retrocompatible y desplegable sin romper el sistema.

> **Estado:** propuesta aprobada en consulta y **revisada contra el código de la v1.2.0** (§1.7).
> El proyecto no incorpora funciones sin consultarlas antes; este documento es el registro de esa
> consulta y de su verificación. **Pendiente de arranque**: al iniciar la primera versión, registrar
> su fase en [`hoja-de-ruta.md`](hoja-de-ruta.md) y declarar la versión objetivo en el PR según
> [`versionado.md`](versionado.md).
>
> **Relación con otros planes:** se construye sobre la interfaz Next.js + `app/api_web/` como
> interfaz principal, pero **no la da por única mientras exista la interfaz clásica** (§2.4). La
> serie se intercala con [`plan-v2.0.md`](plan-v2.0.md) en el camino
> `1.2.x → 1.3.0 → 1.4.0 → 2.0.0 → 2.1.0 → 2.2.0 → 2.3.0` (§8.8). La lógica vive en
> `app/servicios/`, módulo que **todavía no existe** y cuya creación forma parte de la v1.3.0.

---

## 1. Trazabilidad de la consulta — los planes anteriores y qué aportó cada uno

### 1.1 Antecedentes de la sesión

- Despliegue del sistema v1.2.0 completo en Docker (backend FastAPI + frontend Next.js + nginx TLS)
  con `.env` local, certificado autofirmado y admin inicial.
- Corrección del healthcheck de nginx en `docker-compose.frontend.yml` y
  `docker-compose.nginx.yml` (`busybox wget` devuelve 1 ante un error HTTP, no 8 como `GNU wget`).
  Antecedente relevante: los healthchecks y supuestos de las imágenes alpinas deben probarse en la
  realidad del despliegue — lección aplicada a los agentes (§4) y, de forma más general, a toda
  premisa de este plan: **lo que el plan asume del código se verifica contra el código** (§1.7).

### 1.2 Plan 1 — Arquitectura base de agentes (primera consulta)

**Pedido del usuario:** rotar las contraseñas almacenadas directamente desde el sistema, de forma
segura, mediante agentes instalados en los servidores; para dispositivos de red, por API/conectores
(«en veremos»); y que los agentes no solo roten sino que **monitoreen recursos, especificaciones y
estado activo/inactivo**.

**Aportaciones que quedan en este plan:**
- Modelo **pull** de comunicación (el agente pregunta, no escucha): sin puertos de entrada,
  NAT/firewall-friendly, y **la rotación de cualquier cuenta local no puede bloquear al agente**
  (usa su identidad propia, no la contraseña rotada).
- **Rotación en dos fases con rollback** (§2.2): el backend genera la nueva contraseña (CSPRNG,
  misma política del generador), el agente aplica → verifica → confirma o revierte; **journal
  cifrado** en el agente para sobrevivir a su propia muerte a mitad de ciclo.
- Componentes backend: tablas de agentes/trabajos/telemetría, API `/api/agent`, planificador,
  notificaciones, métricas, panel.
- Agente por SO (Linux/Windows) con verificación local (Linux: PAM · Windows: `LogonUser`).
- Dispositivos de red como **conectores** ejecutados por el backend (SSH con plantillas por
  fabricante + SNMPv3 opcional), fase posterior.
- Fases de entrega A–F (hoy reproyectadas como versiones §8).

### 1.3 Plan 2 — Gobernanza, autorización y trazabilidad temporal (segunda consulta)

**Pedido del usuario:** «no puedo hacer una rotación sin autorización o una debida notificación o
verificación en varios pasos, de forma que siempre la rotación quede auditada, e indique por quién
fue aprobada y en qué punto fue rotada (a los dos días o a los 90 exactos), de manera que se puedan
identificar patrones de comportamiento raros».

**Aportaciones que quedan en este plan:**
- **Ciclo de 5 pasos** `SOLICITADA → AUTORIZADA → DESPACHADA → APLICADA/REVERTIDA/FALLADA → CERRADA`
  con regla de **dos pares** (prohibido auto-aprobarse, con prueba), **reautenticación** del
  autorizador (contraseña + segundo factor, mecanismo de «Mi seguridad»), **motivo obligatorio**,
  y registro de la **edad de la contraseña al autorizar y al rotar** (`dias_al_rotar`,
  `desvio_dias`) — el dato clave para patrones.
- **Libro mayor permanente** `RotacionesCredencial` (nunca se purga) separado del ciclo efímero de
  los jobs.
- **Notificaciones por transición** (§3.7) y **detección de patrones por reglas** (§3.8): rotaciones
  tempranas repetidas, fuera de horario, concentración, correlación con exfiltración, anomalías del
  agente.
- RBAC nuevo (`rotacion.solicitar` / `rotacion.autorizar`), vía de emergencia sin excepciones de
  control, rotaciones programadas que generan *solicitudes* aprobables en lote (modo pre-aprobado
  por política **apagado por defecto**).

### 1.4 Plan 3 — Contrato y límites del agente (tercera consulta)

**Pedido del usuario:** definir los límites del agente — un agente con poder de crear/cambiar
contraseñas puede volverse una gran brecha; establecer qué no puede hacer y qué sí puede, con un
despliegue seguro que no deje hueco latente, para los servidores propios **y de cualquier
organización que use el sistema**.

**Aportaciones que quedan en este plan:**
- Principio: el agente es un **brazo ejecutor mínimo**, no un intérprete de comandos: 4 llamadas
  conocidas y 1 tipo de trabajo; todo lo demás se rechaza por código y se audita.
- **Modelo de amenaza con radio de explosión acotado por diseño** (§4.1): comprometer un agente
  solo da la cuenta designada de ese servidor; un operador malicioso no puede canalizar el agente
  (dos pares); el backend completo no gana RCE por el protocolo (enum cerrado de jobs); MITM
  rechazado (TLS + pinning).
- **14 prohibiciones arquitectónicas** con su garantía (§4.1): no crear cuentas, no tocar grupos/
  sudoers/llaves, no comandos arbitrarios, no configuración remota, sin sockets de escucha, egress
  solo al backend, sin auto-actualización en esta serie, máx. 1 job, anti-thrash, versión mínima…
- **Mínimo privilegio real** (§4.2): Linux con agente sin privilegios + helper root de acción única
  (sudoers allowlist exacta) y unidad systemd endurecida; Windows `LocalSystem` con firewall acotado.
- **Acotaciones del backend**: binding agente↔activo validado por credencial, enrolamiento de un
  solo uso ligado al activo, detección de anomalías del agente (IP distinta, versión vieja,
  reversiones en serie).
- Contrato normativo **multi-despliegue** (`docs/contrato-agente.md`): cualquier organización que
  use el sistema hereda las mismas reglas deny-by-default.
- **Tests de contrato** del agente y del backend como criterio de aceptación.

### 1.5 Plan 4 — Indicadores de cobertura visual (cuarta consulta)

**Pedido del usuario:** con agentes ligados a un servidor concreto, debe existir un indicador visual
que diga que ese servidor no tiene agente desplegado o corriendo — que ese servidor «solo existe de
forma manual en el inventario».

**Aportaciones que quedan en este plan:**
- **Taxonomía de insignias** 🟢🟡🟠🔴⚪ (§5) por activo, en listados (con filtros), ficha, credencial
  (define la acción disponible), métricas (tarjeta de cobertura «X de Y activos rotables») y
  alertas de regresión (activo que pierde su agente).
- Definición operativa de **activo rotable** (credencial local SSH/RDP/consola); los dispositivos
  de red quedan ⚪ con nota «vía conector — fase futura» hasta la versión de conectores.
- Garantías: sin estados fantasma al revocar; contador de cobertura consistente con el inventario
  (prueba).

### 1.6 Decisiones cerradas en la consulta

| Decisión | Elección |
|---|---|
| Tecnología del agente | **Go** (binario único por SO; cero dependencias en el servidor gestionado) |
| Cuenta rotada | **La registrada en la credencial** (`usuario_acceso`), con verificación + rollback |
| Estado activo/inactivo | **Alertar y sugerir** — el sistema nunca marca el estado por su cuenta |
| Primera entrega | Solo agentes para servidores físicos, hipervisores y VMs |
| Interfaz | Next.js + `app/api_web/` como principal; la clásica **no se ignora**, se blinda (§2.4) |
| Modelo de comunicación | **Pull**: el agente pregunta; sin puertos de entrada en el servidor |
| Dispositivos de red | Conectores SSH/SNMPv3 en la última versión de la serie |
| Actualización del agente | **Manual** en esta serie (auto-actualización firmada en el endurecimiento) |

**Decisiones añadidas en la revisión (§1.7):**

| Decisión | Elección | Por qué |
|---|---|---|
| Esquema de versiones | **Híbrido**: v1.3.0 y v1.4.0 antes de la 2.0; el resto después (§8) | Rotación real pronto sin congelar la 2.0 ni duplicar más trabajo del necesario |
| Punto único de escritura | **Ninguna** escritura de `Credencial.password_cifrada` fuera de `app/servicios/rotacion.py` (§2.4) | Sin esto la gobernanza es contabilidad, no control |
| Reautenticación del autorizador | **Solo TOTP** (`permitir_correo=False`) | Un OTP a un buzón compartido no es una segunda persona |
| Vía de emergencia | **Break-glass acotado** con un solo admin, marcado y revisado (§2.3) | Sin salida instrumentada, la emergencia ocurre fuera del sistema |
| Mínimo operativo | **Dos administradores** | La regla de dos pares no es aplicable con uno solo |
| Cadena de auditoría | **HMAC con clave** como dependencia de la v1.3.0 | El libro mayor solo prueba algo si no se puede recalcular desde la BD |
| Agente en servidores en vez de conector SSH | **Agente** | Un conector SSH para servidores convertiría el servidor del vault en un *jump host* con acceso saliente a todo el parque: peor radio de explosión que un agente por activo. Los conectores se reservan para lo que no admite agente (§6) |

### 1.7 Correcciones respecto a la consulta original

Trazabilidad de la revisión: qué asumía el plan, qué dice el código de la v1.2.0 y qué se cambió.

| # | Lo que asumía el plan | Lo que dice el código | Corrección aplicada |
|---|---|---|---|
| H1 | La gobernanza cubre la rotación porque la UI es solo Next.js | Hay **tres** rutas que cambian la contraseña (`app/routes/credentials.py:230-233` en Jinja, `app/api_web/credentials.py:208-211` en JSON, `app/importacion.py:173` en CSV) más el **alta** en ambas interfaces (`:148` y `:130`) | §2.4 punto único de escritura; criterio de aceptación en v1.3.0 |
| H2 | La serie v1.3.0–v1.8.0 convive con las fases 9–12 | `plan-v2.0.md` §3 ya asigna la 1.3.0 y salta a la **2.0.0** con ocho roturas R1–R8 | §8 reescrito con el esquema híbrido; §8.8 coordina ambos planes |
| H3 | «La lógica vive en `app/servicios/` desde el primer día» | `app/servicios/` **no existe**; es la Fase 9 pendiente | Crear la capa es parte del alcance de la v1.3.0 (§8.1) |
| H4 | Verificar con PAM/`LogonUser` prueba que la rotación fue buena | Prueba autenticación **local**; la credencial declara `servicio` y `puerto` (`app/models.py:409-410`) y puede quedar inservible para su uso real | Campo `verificacion` (`local`/`remota`), verificación remota en v2.2.0, riesgo residual en §7 |
| H5 | Existe el «operador a cargo de la credencial» | `app/rbac.py` y `app/access.py` solo modelan concesiones al analista y restricción frente al operador | §3.10 lo define como «credenciales que el rol ya puede gestionar», sin modelo nuevo |
| H6 | Sin segundo admin, la vía es manual | Con un solo administrador la rotación por agente **nunca** se puede autorizar: las versiones con agente no entregan nada usable | §2.3 break-glass acotado + mínimo operativo documentado |
| H7 | «Bitácora encadenada» basta para la no repudiación | La cadena es SHA-256 **sin clave** (`app/models.py:874-875`, `app/audit.py:103`); el HMAC está en la Fase 10 de `plan-v2.0.md` | HMAC adelantado a la v1.3.0 (§3.6) |
| H8 | Reautenticación con «contraseña + segundo factor» | `segundo_factor.comprobar()` admite OTP por correo (`app/security/segundo_factor.py:132`) | §3.5 exige TOTP |
| H9 | Hace falta un planificador nuevo | Ya existe `_mantenimiento_periodico` (`app/main.py:253`), con la nota «uno por proceso» | Se reutiliza, con clave de idempotencia por si algún día hay varios *workers* (§3.1) |
| H10 | Ajustes anidados `rotacion.*` / `agentes.*` | `CLAVES_EDITABLES` usa nombres planos (`app/config.py:255-278`) | §3.9 renombrado a claves planas |
| H11 | La telemetría cabe sin más | `max_request_bytes` por defecto es 64 KB (`app/config.py:123`) | §3.3 y §4.4 acotan el tamaño por contrato |
| H12 | El respaldo «incluye las tablas nuevas» | `app/backup.py:154-164, 328-336` repone `password_rotada_en` | §8.0 precisa: se repone el libro mayor y los agentes, **nunca** trabajos pendientes |
| H13 | El alcance es el inventario | `EntradaVault` también tiene `password_rotada_en` (`app/models.py:792`) | §10 lo declara fuera de alcance explícitamente |
| H14 | El trabajo se guarda «cifrado al par del agente» como defensa en reposo (§3.1) | Al confirmar `aplicado`, el backend escribe la contraseña nueva en la credencial (`app/servicios/rotacion.py`), y no tiene la clave privada del agente | En reposo, Fernet del backend como cualquier credencial; el **sellado** al par del agente se hace al **entregar** el trabajo (`app/servicios/cifrado_agente.py`). Hallado al diseñar los servicios de la v1.4.0 |

---

## 2. Arquitectura y protocolo

### 2.1 Comunicación (pull)

```
┌────────────────────────┐        HTTPS pull (solo salida)      ┌──────────────────────┐
│ Agente Go              │ ───────────────────────────────────► │ /api/agent/*         │
│ (systemd / servicio W) │   jobs · ACK · heartbeat · telemetría│ backend FastAPI      │
│ sin sockets de escucha │                                      │ (nginx TLS delante)  │
└────────────────────────┘                                      └──────────────────────┘
  • helper root de acción única (Linux)                                  │
  • identidad propia: no usa la contraseña rotada                        ▼
  → rotar cualquier cuenta local nunca puede bloquear al agente   gobernanza · auditoría
                                                                  notificaciones · métricas
```

- El agente se instala en **servidores físicos, hipervisores y VMs** (una VM lleva su propio
  agente, independiente del del hipervisor; las reglas de acceso por objeto siguen aplicando).
- Egress permitido **solo** al backend configurado (firewall del instalador + `IPAddressAllow`).
- **Identidad de vida corta** (corrección): el token del agente se **renueva en cada `saludo`**
  dentro de una ventana configurable. Un token robado del disco de un servidor caduca en horas, no
  en años. El token viejo sigue válido durante un solapamiento corto para no romper al agente que
  no pudo contactar; dos renovaciones desde IPs distintas en la misma ventana son anomalía (§3.8).

### 2.2 Protocolo de rotación en dos fases (con rollback)

1. **Disparo**: «Rotar ahora» en la credencial, programación por política con *jitter*, o masiva
   por etiqueta del activo — **siempre** a través del ciclo de gobernanza (§2.3).
2. El backend genera la nueva contraseña (CSPRNG, política actual del generador, 20 caracteres) y
   crea un **`TrabajoRotacion`** único (anti-replay, ventana de validez configurable, p. ej. 15 min)
   cuyo payload va **cifrado dirigido al par del agente** (defensa en profundidad en reposo):
   `{tipo: "rotar_cuenta", usuario, nueva, actual}` — incluye la **actual** para permitir el
   rollback determinista. Mientras el job no confirme, **no** es la contraseña de la credencial.
3. El agente aplica `vieja → nueva` en la cuenta local (`usuario_acceso` de la credencial, que es
   una **cuenta local existente**): Linux vía PAM (helper root de acción única) · Windows vía
   `NetUserChangePassword`.
4. **Verificación en varias etapas**: el agente comprueba que la nueva contraseña autentica la
   misma cuenta (Linux: PAM in-process · Windows: `LogonUser`). Si verifica → **ACK
   `aplicado`**: el backend guarda la nueva (Fernet), la anterior pasa al **historial** existente
   (`HistorialCredencial`), `password_rotada_en` se resetea y el ciclo se cierra. Si no verifica →
   el agente **revierte** a la vieja, verifica la vieja, y reporta **`revertido`**: el sistema queda
   como estaba, con alerta.
5. **Journal cifrado en el agente** (§4.3): si el agente muere entre «apliqué» y «confirmé», al
   reiniciar completa o revierte. Nunca queda un estado indeterminado silencioso; si lo hubiera,
   el sistema lo marca y **exige confirmación manual** (nunca silencio).
6. **Purga**: al cerrar el job, el backend elimina los secretos del job y el agente purga la
   memoria y el journal de ese trabajo.

#### 2.2.1 Alcance de la verificación (corrección H4)

La verificación del paso 4 demuestra que **la contraseña nueva autentica la cuenta en el sistema
operativo**. No demuestra que la credencial siga sirviendo para lo que el inventario dice que
sirve. La credencial declara `servicio` (SSH, RDP, iLO/IPMI, panel web…) y `puerto`
(`app/models.py:409-410`), y una cuenta puede autenticar por PAM y aun así quedar inservible:

- `PasswordAuthentication no` o `KbdInteractiveAuthentication no` en `sshd`;
- cuenta fuera de `AllowUsers` / `AllowGroups`, o en `DenyUsers`;
- RDP denegado por política de grupo o cuenta sin pertenencia a *Remote Desktop Users*;
- consola o panel web que no usan la base de cuentas local.

Decisiones:

- El libro mayor registra el campo **`verificacion`**: `local` (PAM/`LogonUser`) o `remota`
  (comprobada desde el backend contra `servicio`+`puerto`).
- La **verificación remota post-rotación** entra en la v2.2.0 (§8.5): intento de conexión desde el
  backend, bajo el mismo límite de tasa y auditoría, como señal independiente que **no** revierte
  por sí sola, sino que alerta.
- Mientras no exista, consta como **riesgo residual aceptado** en §7, y la UI muestra «verificación
  local» en el resultado para que nadie lo lea como «probado de extremo a extremo».

### 2.3 Ciclo de gobernanza (5 estados)

```
SOLICITADA ──► AUTORIZADA ──► DESPACHADA ──► APLICADA / REVERTIDA / FALLADA ──► CERRADA
     │              │              │                      │
     └─ rechazada ──┴─ cancelada ──┴─ expirada ────────────┴─ (con detalle_error si falla)
```

| Paso | Quién | Requisitos | Registro |
|---|---|---|---|
| **Solicitud** | admin u operador con gestión sobre esa credencial (§3.10) | **Motivo obligatorio**; tipo (`programada`/`manual`/`emergencia`/`masiva`); el formulario muestra edad actual, fecha programada, últimas N rotaciones con deltas y el campo «usada por» (§3.1) | `solicitado_por`, `motivo`, `tipo`, `solicitado_en` |
| **Autorización** | **otro admin** (nunca el solicitante) | **Reautenticación** (contraseña + **TOTP**, §3.5); rotación **temprana** exige motivo reforzado y marca `temprana` | `autorizado_por`, `autorizado_en`, `reautenticado`, edad al autorizar |
| **Despacho** | el sistema | Agente conectado (o cola offline autorizada explícitamente); job único con ventana | referencia al `TrabajoRotacion` |
| **Ejecución** | agente | Protocolo de dos fases (§2.2) | `entregado_en`, `confirmado_en`, resultado, `verificacion` |
| **Cierre** | el sistema | Notificación a solicitante + autorizador | evento de auditoría con `dias_al_rotar` |

- **Rotaciones programadas**: el planificador crea *solicitudes* (no jobs) al acercarse la fecha de
  política; el admin las aprueba en lote en el panel «Pendientes de autorización». El modo
  «pre-aprobado por política» existe en configuración y **viene apagado por defecto**.
- **Rotación manual bajo gobernanza** (desde v1.3.0, sin agente): tras autorizar, el operador
  cambia la contraseña en el servidor y la registra en el sistema por el flujo normal de
  credenciales (mismo cifrado e historial); el ciclo se cierra con el resultado `manual`. Ese
  registro **solo es posible contra una solicitud autorizada abierta** (§2.4).

#### 2.3.1 Emergencia y break-glass acotado (corrección H6)

La emergencia es **prioridad, no atajo**. El camino normal es: notificación urgente a todos los
admins y autorización de **otro admin** con reautenticación; despacho inmediato tras autorizar.

Pero la regla de dos pares no puede dejar al sistema sin salida. Con un solo administrador
disponible —instalación pequeña, madrugada, vacaciones— el plan original empujaba la operación
fuera del sistema («cámbiala a mano y regístrala luego»), que es exactamente el bypass que la
gobernanza quiere evitar, solo que sin instrumentar. Se define una salida acotada:

| Elemento | Regla |
|---|---|
| Quién | Un admin, sobre su propia solicitud, **solo** con `tipo = emergencia` |
| Requisito | Reautenticación con **TOTP** (nunca OTP por correo) + motivo reforzado obligatorio |
| Ventana | Configurable (por defecto 60 min desde la solicitud); fuera de ella, vuelve a exigir dos pares |
| Marca | `emergencia_sin_segundo_par = true` en `RotacionesCredencial`, **imborrable** |
| Ruido | Notificación urgente inmediata a **todos** los admins y entrada destacada en `/metricas` |
| Revisión | Queda **abierta** una tarea de revisión posterior; otro admin debe marcarla revisada, y mientras no lo haga aparece en el panel y en los avisos |
| Límite | Contador por ventana configurable: superarlo dispara regla de patrón (§3.8) |

**Mínimo operativo documentado:** el sistema requiere **dos administradores** para operar la
rotación con gobernanza plena. Con uno solo, todas las rotaciones caen por la vía de emergencia
marcada, que es visible y revisable pero no sustituye al control. El arranque de la v1.3.0 avisa en
la consola si hay menos de dos administradores activos.

### 2.4 Punto único de escritura (corrección H1)

**La corrección más importante de esta revisión.** La gobernanza solo vale si no hay forma de rotar
por fuera. Hoy, en la v1.2.0, hay tres caminos que escriben la contraseña de una credencial:

| # | Camino | Código | Qué hace hoy |
|---|---|---|---|
| 1 | Interfaz clásica (Jinja) — cambio de contraseña | `app/routes/credentials.py:230-233` | Escribe `HistorialCredencial`, `password_cifrada` y `password_rotada_en` |
| 2 | API JSON (Next.js) — cambio de contraseña | `app/api_web/credentials.py:208-211` | Idéntico, lógica duplicada |
| 3 | Importación CSV | `app/importacion.py:173` | Escribe `password_cifrada` directamente |
| 4 | Alta de credencial (ambas interfaces) | `app/routes/credentials.py:148`, `app/api_web/credentials.py:130` | Escribe `password_cifrada` al crear |

El camino 4 es **alta, no rotación**: no debe generar asiento en el libro mayor, pero sí pasar por
el servicio, para que `password_rotada_en`, `via_rotacion` y la auditoría queden coherentes desde el
primer día de vida de la credencial. La distinción alta/rotación es parte del contrato del servicio.

Si la puerta de gobernanza se coloca solo en el camino 2, un operador rota sin solicitud, sin
motivo, sin autorizador y sin `dias_al_rotar` usando el camino 1 o el 3 — y las reglas de patrón
(§3.8) quedan ciegas justo ante el comportamiento que deben detectar.

**Regla normativa de esta serie:**

> Ninguna escritura de `Credencial.password_cifrada` ocurre fuera de `app/servicios/rotacion.py`.

Cómo queda cada camino desde la v1.3.0:

| Camino | Resultado |
|---|---|
| Interfaz clásica | El formulario de credencial deja de aceptar cambio de contraseña suelto; delega en el servicio, que exige una solicitud autorizada abierta. Es una **duplicación deliberada y temporal** de la puerta: desaparece con la retirada de la interfaz clásica en la 2.0.0 (R1) |
| API JSON | Igual, por el mismo servicio |
| Importación CSV | **Alta** de credenciales nuevas, que es su propósito (migración), y pasa por el servicio. Al implementar la v1.3.0 se comprobó que la importación **nunca sobrescribe** una credencial existente —solo inserta—, de modo que la prohibición de sobrescritura que este plan preveía no hacía falta y no se añadió: habría sido un ajuste de configuración sin nada que gobernar |
| CLI y respaldo/restauración | `restaurar` repone estado, no rota: no genera asientos nuevos y nunca repone trabajos pendientes (§8.0) |

**Criterio de aceptación (test de arquitectura):** una prueba recorre `app/routes/`,
`app/api_web/` y `app/importacion.py` y **falla** si alguno asigna `password_cifrada` —tanto en alta
como en cambio— fuera de `app/servicios/`. Es la prueba que impide que la regresión vuelva por la
puerta de atrás dentro de seis meses, cuando nadie recuerde por qué estaba prohibido.

---

## 3. Especificación del backend

### 3.1 Modelo de datos (todas las migraciones aditivas: `schema_sync` + Alembic)

| Tabla | Campos esenciales | Reglas |
|---|---|---|
| `Agentes` | `nombre` (único), `token_hash` (solo hash, patrón `TokenApi`), `token_expira_en`, `estado` (`pendiente`/`activo`/`revocado`; «conectado» y «sin contacto» se **derivan** de `ultimo_contacto_en`, ver §9.4), FK uno-de a `ServidorFisico`/`Hipervisor`/`MaquinaVirtual` (CHECK uno-de), `clave_publica`, `version_agente`, `ultimo_contacto_en`, `ip_ultimo_contacto`, `rotacion_habilitada`, `intervalo_telemetria_min`, `creado_por_id`, `creado_en`, `revocado_en` | un agente ↔ un activo; token revocable y **de vida corta** (§2.1) |
| `TrabajosRotacion` | `agente_id`, `credencial_id`, `estado` (`pendiente`→`entregado`→`aplicado`/`revertido`/`fallado`/`expirado`/`cancelado`), `nueva_cifrada`, `actual_cifrada` (**se purgan al cerrar**), `ventana_expira_en`, `intentos`, `disparado_por_id`, `creado_en`, `entregado_en`, `confirmado_en`, `detalle_error` | máx. 1 job activo por agente; payload cifrado para el agente |
| `RotacionesCredencial` | `credencial_id`, `agente_id` (nullable), `solicitado_por_id`, `motivo`, `tipo` (`programada`/`manual`/`emergencia`/`masiva`/`importacion`), `autorizado_por_id`, `autorizado_en`, `reautenticado`, **`emergencia_sin_segundo_par`**, **`revisada_por_id`**, **`revisada_en`**, `dias_al_rotar`, `fecha_programada`, `desvio_dias`, `ejecutado_en`, `confirmado_en`, `resultado` (`aplicada`/`revertida`/`fallada`/`manual`/`cancelada`), **`verificacion`** (`local`/`remota`/`ninguna`), `detalle_error` | **libro mayor permanente**: la purga de jobs no lo borra; entra al respaldo cifrado |
| `TelemetriaAgente` | `agente_id`, `fecha`, `cpu_pct`, `ram_pct`, `disco_pct`, `uptime_s`, `sistema_operativo`, `kernel`, `cpu_modelo`, `ram_total`, `discos_json` | índice `(agente_id, fecha)`; retención configurable; tamaño acotado (§3.3) |
| `Credencial.via_rotacion` | `manual`/`agente`/`conector` (columna aditiva, default `manual`) | valida qué vía ofrece la UI |
| `Credencial.usada_por` | texto libre: servicios y automatismos que consumen la cuenta (cron, tareas programadas, respaldos, Ansible, monitorización) | **corrección**: se muestra en la pantalla de solicitud y en la de autorización |
| `SolicitudesProgramadas` (índice) | único `(credencial_id, fecha_programada)` | **corrección H9**: idempotencia del planificador aunque corra en varios procesos |
| `Agentes.min_version_requerida` (ajuste del backend) | versión mínima aceptada | el agente viejo deja de recibir jobs al vencer la gracia |

**Sobre el cifrado del job hacia el agente (corregido por H14).** En reposo, `nueva_cifrada` y
`actual_cifrada` llevan el **Fernet del backend**, la misma protección que cualquier credencial:
no pueden ser legibles solo por el agente, porque al confirmar `aplicado` el backend tiene que
escribir esa contraseña. El trabajo se **sella al par X25519 del agente al entregarlo**: protege la
contraseña en vuelo además de TLS y la ata a la clave del agente, de modo que un token robado sin
la clave privada no basta para leer un trabajo. No protege frente al compromiso del backend
completo, que ya tiene todas las contraseñas (§4.1). Se implementa con primitivas de
`cryptography` —**X25519 + HKDF-SHA256 + Fernet**— y **nunca** con un esquema propio
(`app/servicios/cifrado_agente.py`; vectores compartidos con el agente en
`tests/vectores/cifrado_agente.json`). La clave pública del agente se registra en el enrolamiento;
el libro mayor registra qué par de claves se usó.

### 3.2 Máquina de estados y quiénes pueden

- **Solicitud**: crear (admin/operador con gestión sobre la credencial) · rechazar (otro admin) ·
  cancelar (propietario, si no está despachada; admin siempre) · autorizar (**otro admin**, con
  reautenticación TOTP; excepción acotada de emergencia §2.3.1).
- **Trabajo**: crear (sistema, tras autorización) · entregar (agente dueño) · confirmar
  (`aplicado`/`revertido`/`fallado`, agente dueño) · expirar (sistema, al vencer ventana) ·
  cancelar (admin, si no entregado).
- **Invariantes probadas**:
  1. Imposible despachar sin `AUTORIZADA`.
  2. Imposible autorizar la propia solicitud (salvo emergencia marcada y dentro de ventana).
  3. Job vencido se purga; `RotacionesCredencial` sobrevive a toda purga.
  4. **Ninguna escritura de `password_cifrada` fuera del servicio de rotación** (§2.4).
  5. Una rotación `manual` solo se registra contra una solicitud autorizada abierta.

### 3.3 API `/api/agent/*` (Bearer por agente, sin cookies/CSRF)

| Endpoint | Método | Entrada | Salida / efectos |
|---|---|---|---|
| `/api/agent/enrolar` | POST | `token_un_uso` + huella/hostinfo + clave pública | token del agente (solo-hash en BD) con caducidad; token de uso único, ligado al activo, con expiración corta |
| `/api/agent/saludo` | POST (no GET: renueva la identidad y escribe el contacto) | versión | heartbeat: versión mínima exigida, ajustes de cadencia, **token renovado** si entra en la ventana de renovación; actualiza `ultimo_contacto`/IP |
| `/api/agent/trabajos/pendiente` | GET | — | job único cifrado para ese agente (o 204); marca `entregado`; registra anti-replay |
| `/api/agent/trabajos/{id}/resultado` | POST | `estado` (`aplicado`/`revertido`/`fallado`) + evidencia + `verificacion` | cierra el job, aplica los efectos en credencial/libro mayor, notifica, purga secretos |
| `/api/agent/telemetria` | POST | métricas agregadas + specs | persiste con retención; refresca latido |

Límites: rate limit por agente, **tamaño máximo de cuerpo coherente con `max_request_bytes`
(64 KB por defecto, `app/config.py:123`)** — la telemetría se acota por contrato (§4.4) y el
servidor rechaza lo que exceda en vez de ampliarlo; auditoría encadenada de **cada** llamada;
binding agente↔activo validado por credencial antes de despachar; rechazo de versiones antiguas
tras la gracia.

**Alcance de la auditoría (decisión del 2026-11-25).** Se audita todo cambio de estado
(enrolamiento, renovación de identidad, entrega de un trabajo, su resultado) y **todo rechazo**;
el latido rutinario y la consulta sin trabajo no dejan asiento y quedan como «último contacto».
Auditar cada latido —unas 96 entradas por agente y día— llenaría la bitácora de «sigue vivo» y
escondería lo que importa. Los rechazos sin identidad se acotan por IP, y un 429 repetido se
audita una vez por ventana, para que nadie pueda llenar la bitácora a base de peticiones. **`/api/v1` (SIEM) no cambia**: sigue de solo lectura y sin secretos.

### 3.4 API `/api/web` nueva (sesión + CSRF, para el frontend)

Gestión de agentes (CRUD/revocar, token de enrolamiento de un solo uso), solicitudes (crear,
listar, autorizar con reautenticación, rechazar, cancelar, marcar revisada una emergencia), cierre
manual (aplicar-manual), historial/timeline por credencial y por activo, telemetría por agente,
cobertura, métricas.

Toda la lógica vive en `app/servicios/rotacion.py` y `app/servicios/agentes.py`. **Dependencia real
(H3): `app/servicios/` no existe todavía.** Su creación —con credenciales y autenticación migradas,
que es el bloque A1 de [`plan-v2.0.md`](plan-v2.0.md)— forma parte del alcance de la v1.3.0 y no se
da por disponible.

### 3.5 Reautenticación del autorizador

Mismo mecanismo de «Mi seguridad» ya existente (`app/security/segundo_factor.py`): contraseña +
código del segundo factor en la acción de autorizar.

**Corrección H8:** `segundo_factor.comprobar()` admite OTP por correo
(`app/security/segundo_factor.py:132`). Para `rotacion.autorizar` y para el break-glass se invoca
con **`permitir_correo=False`**: un código enviado a un buzón —que puede ser compartido, o estar
abierto en la misma sesión del navegador— no constituye una segunda persona ni un segundo factor
independiente. Coherente con el modelo de amenaza de
[`resistencia-bypass-mfa.md`](resistencia-bypass-mfa.md). Implementación compartida en
`app/servicios/`, lista para que la Fase 10 de `plan-v2.0.md` la generalice a otras acciones de
alto impacto.

### 3.6 Auditoría (bitácora encadenada, SEC-9)

Eventos nuevos con usuario, IP, agente y credencial: `rotacion.solicitada`, `rotacion.autorizada`,
`rotacion.rechazada`, `rotacion.cancelada`, `rotacion.despachada`, `rotacion.entregada`,
`rotacion.aplicada`, `rotacion.revertida`, `rotacion.fallada`, `rotacion.manual_registrada`,
`rotacion.expirada`, `rotacion.emergencia_sin_par`, `rotacion.emergencia_revisada`,
`rotacion.verificacion_solo_local`, `rotacion.importacion_sobrescribe`, `agente.enrolado`,
`agente.token_renovado`, `agente.revocado`, `agente.rechazo_job`, `agente.sin_contacto`,
`agente.ip_distinta`. Nunca contienen secretos.

**Corrección H7 — la cadena debe estar firmada.** Hoy el encadenamiento es SHA-256 sin clave
(`app/models.py:874-875`, `app/audit.py:103`): quien pueda escribir en la base de datos puede
recalcular la cadena entera y reescribir quién aprobó qué. El producto principal de la v1.3.0 es
precisamente «quién aprobó y cuándo se rotó», de modo que **el HMAC con clave de la Fase 10 de
[`plan-v2.0.md`](plan-v2.0.md) se adelanta y entra como dependencia de la v1.3.0**, con el tramo
anterior marcado como heredado y `verificar-auditoria` validando ambos (R6).

### 3.7 Notificaciones por transición (nunca con secretos)

| Evento | Destinatarios |
|---|---|
| Solicitud creada | todos los admins |
| Autorizada / rechazada | solicitante + admins |
| Aplicada / revertida / fallada | solicitante + autorizador |
| **Emergencia sin segundo par ejecutada** | **todos los admins, urgente, con la tarea de revisión** |
| **Emergencia pendiente de revisión** (recordatorio) | todos los admins, hasta que se revise |
| **Resultado con verificación solo local** | solicitante + autorizador (informativo) |
| **Importación que sobrescribe una contraseña** | todos los admins |
| Agente sin contacto con rotación pendiente | admins |
| Regla de patrón disparada / regresión de cobertura / IP distinta | admins (configurable) |
| Emergencia solicitada | todos los admins (urgente) |

### 3.8 Detección de patrones (reglas simples, sin ML, en `/metricas`)

| Regla | Definición por defecto |
|---|---|
| Rotaciones tempranas repetidas | `dias_al_rotar` < 25 % del intervalo de política, N veces en ventana |
| Fuera de horario | nocturno/fin de semana según zona configurable |
| Concentración | ráfaga de solicitudes del mismo solicitante o sobre el mismo activo |
| Correlación de exfiltración | rotación seguida de pico de revelados/copiados (cruza el límite anti-exfiltración existente) |
| Anomalía de cumplimiento | distribución de `dias_al_rotar` del inventario fuera de lo esperado |
| **Abuso de emergencia** | más de N rotaciones `emergencia_sin_segundo_par` por ventana, o revisiones pendientes vencidas |
| Anomalía del agente | contacto desde IP distinta a la de gestión del activo; versión vieja; reversiones/fallos en serie; regresión de cobertura; **dos renovaciones de token desde IPs distintas en la misma ventana** |

**Corrección — arranque en modo observación.** En un inventario pequeño, «concentración» y «fuera de
horario» disparan constantemente y el resultado práctico es que los admins filtran los correos. Las
reglas se entregan con un ajuste de **modo observación activado por defecto durante una versión**:
se evalúan, se registran y se ven en `/metricas`, pero **no notifican**. Tras una versión de datos
reales se calibran umbrales y se activan las notificaciones una por una. Los valores por defecto se
documentan en [`referencia-configuracion.md`](referencia-configuracion.md).

### 3.9 Configuración en caliente (variables nuevas, defaults en `.env.example`)

**Corrección H10:** el registro `CLAVES_EDITABLES` de `app/config.py:255-278` usa nombres **planos**
(`rotation_max_days`, `reveal_rate_limit`…). Las claves nuevas siguen ese estilo, no uno anidado:

Un ajuste solo se añade cuando hay algo que gobernar en esa versión: una clave que no lee nadie es
configuración muerta que alguien tendrá que mantener y documentar. Los de la ejecución por agente
llegan con el agente.

**Entregados en la v1.3.0:**

| Clave | Defecto | Para qué |
|---|---|---|
| `rotacion_temprana_pct` | 25 | % de la vigencia por debajo del cual la rotación es temprana |
| `rotacion_emergencia_ventana_min` | 60 | Ventana del break-glass (§2.3.1) |
| `rotacion_emergencia_max_por_mes` | 3 | Umbral de la regla de abuso de emergencia |
| `rotacion_patrones_modo_observacion` | **true** | Las reglas registran pero no notifican |

El **intervalo de política** NO se duplica: es el `rotation_max_days` que ya existía y que rige las
alertas de antigüedad. Dos ajustes con el mismo significado acaban divergiendo, y entonces nadie
sabe cuál manda.

**Pendientes, con su versión:**

| Clave | Defecto | Versión |
|---|---|---|
| `rotacion_pre_aprobada_politica` | **false** | 2.1.0 (con la programación automática) |
| `rotacion_ventana_job_min` | 15 | 1.4.0 (validez del trabajo despachado) |
| `rotacion_anti_thrash_horas` | 24 | 1.4.0 |
| `rotacion_jitter_horas` | 24 | 2.1.0 |
| `agentes_telemetria_intervalo_min` | 15 | Cadencia de telemetría |
| `agentes_umbral_sin_contacto_horas` | 24 | Paso a 🟡 y alerta |
| `agentes_retencion_telemetria_dias` | 30 | Retención y purga |
| `agentes_version_minima` | — | Versión mínima aceptada |
| `agentes_gracia_version_dias` | 14 | Gracia antes de dejar de despachar |
| `agentes_token_vida_horas` | 24 | Caducidad del token del agente (§2.1) |
| `agentes_alertar_ip_distinta` | true | Con nota de NAT |

### 3.10 RBAC

| Permiso | admin | operador | auditor | analista |
|---|:-:|:-:|:-:|:-:|
| `rotacion.solicitar` | ✔ | ✔ (†) | ✘ | ✘ |
| `rotacion.autorizar` | ✔ **otro** admin; jamás la propia salvo emergencia marcada | ✘ | ✘ | ✘ |
| `rotacion.revisar_emergencia` | ✔ **otro** admin | ✘ | ✘ | ✘ |
| Ver timeline/libro mayor | ✔ | ✔ (lo suyo) | ✔ (supervisión, nunca secretos) | ✘ |
| Cancelar solicitud propia | ✔ | ✔ (si no está despachada) | ✘ | ✘ |
| Gestionar agentes | ✔ | ✘ | ✘ | ✘ |

**(†) Corrección H5 — qué significa «a cargo».** El plan original hablaba del «operador a cargo de
la credencial»; ese concepto **no existe** en el modelo (`app/rbac.py` solo tiene RBAC por tipo de
operación, y `app/access.py` modela concesiones al analista y restricción de activos frente al
operador). Introducir responsabilidad por activo sería una funcionalidad propia, con su modelo, su
UI y su migración. Se define, sin modelo nuevo:

> `rotacion.solicitar` alcanza **las credenciales que el rol ya puede gestionar hoy**, aplicando sin
> cambios `credenciales.gestionar` y las reglas de `app/access.py` (los activos restringidos siguen
> siendo inexistentes para el operador; el analista no entra).

Si más adelante se quiere responsabilidad nominal por activo, entra como funcionalidad aparte y se
consulta antes, como manda el proyecto.

---

## 4. Especificación del agente

### 4.1 Contrato deny-by-default

**Lo que SÍ puede (lista exhaustiva):**
1. Autenticarse con su identidad contra **su** backend configurado y solo contra él.
2. Recoger **un** trabajo: `{tipo: rotar_cuenta, usuario, nueva, actual}` (cifradas para su clave).
3. Ejecutarlo en dos fases: aplicar → verificar → confirmar o **revertir**.
4. Reportar resultado y telemetría **agregada de su propio host**.
5. Guardar su identidad y journal cifrados; purgar secretos de memoria al cerrar el job.
6. **Renovar su propio token** en `saludo`, dentro de la ventana configurada (§2.1).

**Lo que NO puede (imposibilidad arquitectónica):**

| # | Prohibición | Garantía |
|---|---|---|
| 1 | **Crear cuentas** nuevas | El rotador solo cambia contraseñas de cuenta existente; cuenta inexistente → fallo, nunca alta |
| 2 | Borrar/deshabilitar cuentas, grupos, sudoers, `authorized_keys`, llaves SSH | No existen en el protocolo |
| 3 | Ejecutar comandos o scripts arbitrarios del backend | Job sin comandos; tipo desconocido → rechazo + auditoría (**test de contrato**) |
| 4 | Conocer contraseñas de otros activos o agentes | Job cifrado para su clave y validado contra su activo (check en backend) |
| 5 | Decidir rotar por su cuenta | Solo ejecuta lo autorizado; la telemetría nunca dispara acciones |
| 6 | Configurarse desde la red | Configuración sensible local; sin config push en esta serie |
| 7 | Escuchar en la red | Sin sockets de escucha; solo conexiones salientes |
| 8 | Salir a cualquier destino | Egress solo al backend (firewall del instalador + `IPAddressAllow`) |
| 9 | Telemetría invasiva | Solo métricas agregadas y hardware: sin procesos, usuarios, teclas ni rutas; **tamaño acotado** (§4.4) |
| 10 | Auto-actualizarse | Paquete manual con SHA256 publicado (firmado desde la v2.3.0) |
| 11 | Persistir secretos en claro | Journal cifrado (0600); memoria purgada; logs redactados |
| 12 | Acumular trabajos | Máx. 1 job activo; ventana de validez; vencido se purga |
| 13 | Martillear rotaciones | Anti-thrash por cuenta y ventana — **excepción**: la vía de emergencia (§2.3.1) lo salta, y el salto queda registrado en el libro mayor y en la bitácora |
| 14 | Vivir desactualizado | Versión mínima; sin jobs al vencer la gracia |

> **Por qué la prohibición 13 admite excepción (corrección).** El anti-thrash de 24 h protege contra
> un bucle de rotaciones, pero ante una credencial filtrada hay que poder rotar dos veces el mismo
> día. Sin excepción instrumentada, el operador rota fuera del sistema. La excepción solo la abre la
> vía de emergencia, que ya es ruidosa y revisable.

**Modelo de amenaza (radio de explosión por diseño):**

| Compromiso | Alcance máximo | Por qué no pasa a más |
|---|---|---|
| Un agente | La cuenta designada de **ese** servidor + telemetría falsa de ese activo | Identidad ligada a 1 activo; no lee contraseñas ni jobs ajenos |
| **Token de agente robado del disco** | Suplantar a ese agente hasta que caduque | **Token de vida corta renovado en `saludo`** (§2.1); dos renovaciones desde IPs distintas = anomalía |
| Un operador malicioso | Nada automático | Dos pares + reautenticación TOTP |
| **Un admin solo, malicioso** | Rotaciones marcadas `emergencia_sin_segundo_par`, visibles y con revisión pendiente | No hay vía silenciosa: la marca es imborrable y notifica a todos |
| El backend completo | Ya es el tesoro (tiene todas las contraseñas); el protocolo **no le añade RCE** | Jobs con enum cerrado y parámetros validados |
| **Fuga de la BD sin la clave Fernet** | No revela la contraseña nueva en vuelo | Payload del job cifrado al par del agente (§3.1) |
| MITM / backend falso | Rechazado | TLS estricto + *pinning* (opcional desde v1.4.0, estándar en v2.3.0) |

### 4.2 Privilegios y sandboxing por SO

- **Linux (por defecto): agente sin privilegios + helper root de una sola acción.** Servicio como
  `passwd-agente` (sin shell, sin home con secretos). El cambio se hace vía `sudo` con allowlist
  exacta: `NOPASSWD: /usr/local/sbin/passwd-agente-helper rotate <cuenta> --stdin`. El helper
  valida parámetros, aplica por PAM, verifica y devuelve resultado JSON. Una RCE en el código de
  red del agente **no es root**. Alternativa documentada: modo root endurecido para entornos sin sudo.
- **Unidad systemd endurecida**: `ProtectSystem=strict`, `ProtectHome`, `PrivateTmp`,
  `CapabilityBoundingSet=` (vacía para el agente), `RestrictAddressFamilies`, `IPAddressAllow` del
  backend, `MemoryDenyWriteExecute`.
- **Windows**: servicio como `LocalSystem` (requisito de la API de cuentas locales) con regla de
  firewall **saliente** acotada al backend, sin logon interactivo y las mismas prohibiciones.
- **Instalador**: crea usuario/clave/permisos (0600), regla de egress y **falla** si algo no cumple.

### 4.3 Journal y manejo de secretos

- Journal local (SQLite/JSONL) **cifrado** con clave derivada de su archivo de identidad (0600).
  Contiene solo el trabajo en curso; se purga al cerrar.
- El agente recibe `nueva` y `actual` (ambas necesarias para el rollback determinista) en memoria
  únicamente; purga tras cerrar. Nunca en claro en disco ni en logs.
- El agente **nunca** recibe la contraseña actual «de la credencial» si no es en un job suyo: no
  existe endpoint de lectura de secretos para agentes.

### 4.4 Telemetría

- Con `gopsutil` (sin cgo): CPU/RAM/disco %, uptime; specs de SO, kernel, CPU, RAM total, discos.
- **Acotada por contrato (corrección H11):** el cuerpo de `/api/agent/telemetria` no supera un
  tamaño fijado muy por debajo de `max_request_bytes` (64 KB por defecto, `app/config.py:123`).
  `discos_json` se limita a un número máximo de discos y se recortan cadenas largas en el agente,
  no en el servidor. Si no cabe, el agente envía lo esencial y marca el recorte; el servidor
  **rechaza** lo que exceda en vez de ampliar el límite global de la aplicación.
- **Alcance recortado (corrección):** la telemetría es la parte con más superficie nueva y menos
  valor de seguridad del plan, y compite con la monitorización que ya exista en la organización. Se
  entrega **latido + specs + instantánea actual**; el **histórico** es opcional, con retención corta
  por defecto, y es lo primero que se recorta si hay que ajustar alcance.
- Cadencia configurable; se envía junto al latido. Retención en backend configurable (§3.9).
- Copiar specs a los campos de hardware del activo es **opt-in por agente**, auditable y nunca
  silencioso. El estado activo/inactivo se **alerta y sugiere**, nunca se marca solo.

### 4.5 Ciclo de vida del agente

- **Enrolamiento**: token de un solo uso emitido desde la ficha del activo en el panel, con
  expiración corta; el agente presenta hostinfo y su clave pública recién generada. Estado ⚪→🟠→🟢.
- **Renovación de identidad** (corrección): `saludo` devuelve un token nuevo cuando el actual entra
  en su ventana de renovación; el anterior sigue válido durante un solapamiento corto. Si el agente
  estuvo apagado más allá de la caducidad, queda 🔴 y **requiere re-enrolamiento desde el panel**:
  un binario olvidado en una máquina dada de baja no conserva acceso indefinido.
- **Versiones**: `saludo` reporta versión; el backend exige versión mínima con período de gracia.
- **Revocación**: desde el panel; el agente deja de recibir jobs; el activo vuelve a ⚪ y la
  credencial a flujo manual — sin estados fantasma.

---

## 5. Indicadores de cobertura

| Insignia | Significado | Detalle al pasar el cursor |
|---|---|---|
| 🟢 Agente conectado | enrolado y con latido reciente | versión, última señal, próxima rotación |
| 🟡 Sin contacto | enrolado pero supera el umbral (p. ej. 24 h) | última señal conocida; alerta ya emitida |
| 🟠 Pendiente de enrolamiento | token emitido, el agente nunca conectó | emisión y expiración del token |
| 🔴 Desconectado/revocado | agente revocado, desactivado o con identidad caducada | quién y cuándo |
| ⚪ **Sin agente — gestión manual** | el activo existe solo en el inventario | asistente «Instalar agente» |

- **Ubicaciones**: listados de inventario (columna/insignia junto al estado del activo, con filtros
  «sin agente»/«sin contacto»/«pendientes»), ficha del activo (bloque «Cobertura de rotación» +
  telemetría si tiene), credencial (la insignia define la acción: «Rotar ahora» con gobernanza vs
  flujo manual con aviso), `/metricas` (tarjeta «X de Y activos rotables con agente (Z %)» + cola
  de activos sin agente) y alertas de regresión.
- **Rotable** = activo con credencial local (SSH/RDP/consola). Dispositivos de red: ⚪ con nota
  «vía conector — fase futura» hasta la v2.3.0.
- **Garantías**: los indicadores reflejan el estado real en tiempo de render; al revocar, el activo
  vuelve a ⚪ sin estados fantasma; el contador de cobertura cuadra con el inventario (prueba).

---

## 6. Dispositivos de red (conectores, v2.3.0)

No hay agente instalable en un switch: **conectores ejecutados por el backend**.

- **Conector SSH** con plantillas por fabricante (Cisco IOS/IOS-XE, Aruba, MikroTik…): mismo
  protocolo de dos fases (aplicar → verificar con la nueva → confirmar/revertir), bajo el mismo
  ciclo de gobernanza y auditoría. Aquí la verificación **sí** es remota por naturaleza, de modo
  que el campo `verificacion` queda en `remota` (§2.2.1).
- **SNMPv3 USM** opcional para fabricantes sin SSH o como complemento.
- `known_hosts`: primera conexión registra la huella en la BD (fijación) y alerta si cambia.
- *Threat model* propio: el backend usa credenciales ya custodiadas para SSH **saliente** hacia la
  IP de gestión; egress documentado; la conexión se ejecuta bajo el límite de tasa y auditoría.
- **Por qué esto no se extiende a los servidores** (§1.6): un conector SSH para todo el parque
  convertiría el servidor del vault en un *jump host* con acceso saliente a cada máquina. El agente
  por activo mantiene el radio de explosión acotado. Los conectores se usan solo donde no cabe un
  agente.
- La credencial del dispositivo se marca `via_rotacion = "conector"` y la insignia del dispositivo
  lo refleja.

---

## 7. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Bloqueo por cambio mal aplicado | verificación + rollback + journal cifrado + historial existente |
| Ventana indeterminada (agente muere a mitad) | journal; estado explícito exige confirmación manual; nunca silencio |
| **Verificación solo local: la credencial autentica pero no sirve para su `servicio`** | campo `verificacion` visible en UI y libro mayor; verificación remota en v2.2.0; **riesgo residual aceptado** hasta entonces (§2.2.1) |
| **Rotación fuera de la gobernanza por otra ruta de escritura** | punto único de escritura + test de arquitectura (§2.4); desaparece la duplicación con la 2.0.0 |
| **Instalación con un solo administrador** | break-glass acotado y marcado (§2.3.1); aviso en el arranque; mínimo operativo documentado |
| **Token del agente en el disco de cada servidor** | vida corta con renovación en `saludo`; re-enrolamiento obligatorio tras caducar; anomalía por IP |
| **Planificador duplicando solicitudes en despliegue multiproceso** | índice único `(credencial_id, fecha_programada)`; reutiliza `_mantenimiento_periodico` (§3.1) |
| **Reglas de patrón ruidosas que acaban ignoradas** | modo observación por defecto una versión, calibración con datos reales (§3.8) |
| **Cuenta usada por servicios y automatismos** (Linux y Windows) | campo «usada por» en la credencial, visible al solicitar y al autorizar; aviso en la UI al rotar |
| Cuentas deshabilitadas/lockeadas (Linux) | el agente comprueba estado antes de tocar |
| Backend falso / MITM | TLS estricto + pinning (opcional → estándar en v2.3.0) |
| **Cadena de auditoría recalculable desde la BD** | HMAC con clave adelantado a la v1.3.0 (§3.6) |
| cgo/arm64 en CI | build nativo + cross-compile; si costara, arm64 difiere a v2.3.0 |
| Telemetría escala | alcance recortado, retención configurable; instantánea actual en la ficha |
| Drift de reloj | hora del servidor como referencia; ventanas generosas |
| Regresión de cobertura | alerta cuando un activo rotable pierde su agente |
| **Go como segundo lenguaje a mantener años** | módulo aislado en `agente/`, CI propia (`go vet`, `govulncheck`), superficie mínima por contrato (§4.1); se asume con la decisión de §1.6 |

---

## 8. Segmentación por versiones (desglose detallado)

### 8.0 Reglas transversales — «sin romper el sistema»

Aplican a **todas** las versiones:

1. **Migraciones aditivas** (`schema_sync` + Alembic): dentro de la serie 1.x nunca se modifica ni
   elimina esquema existente. Los cambios no aditivos pertenecen a la 2.0.0, que ya los tiene
   presupuestados como roturas (R1–R8 de [`plan-v2.0.md`](plan-v2.0.md)).
2. **`/api/v1` y el export/import CSV existentes sin cambio de contrato** en la serie 1.x.
3. **Cada versión desplegable sola sobre la anterior**, con pruebas nuevas y entrada en
   `CHANGELOG.md` bajo `[Sin publicar]`; publicación SemVer según [`versionado.md`](versionado.md).
4. **El respaldo cifrado** (`respaldo`/`restaurar`) incluye desde su versión las tablas nuevas.
   Precisión (H12): se reponen **agentes** (revocados, sin token válido) y el **libro mayor**
   completo; **nunca** se reponen `TrabajosRotacion` pendientes — un restore no resucita un trabajo
   con secretos y ventana vencida. `app/backup.py` ya repone `password_rotada_en`, y el libro mayor
   restaurado debe quedar coherente con ese valor.
5. **Feature flags**: lo no terminado queda tras flag apagado en configuración en caliente, nunca
   a medias ni parcialmente activo.
6. **Despliegue por ambientes** ([`ambientes.md`](ambientes.md)): desarrollo → calidad →
   preproducción → producción; el flujo del agente se valida en calidad con contenedores de prueba
   antes de tocar producción.
7. **CI por versión**: suite completa (`pytest`, `ruff`, `bandit`, `pip-audit`, cobertura ≥ 70 %)
   más los tests de la versión; desde la primera versión con agente, job Go (`go vet`,
   `govulncheck`, build multiplataforma, unit tests); actualización de matrices CIS/ISO/OWASP.
8. **Disciplina de commit** (§9.3): un commit por capa, con la verificación de esa capa en verde
   antes de commitear. Ninguna versión se cierra sin su fila en el registro de ejecución (§9.4).

### 8.1 v1.3.0 — Gobernanza de rotación (sin agente)

**Objetivo.** Que todo el ciclo de autorización y trazabilidad funcione con **rotación manual**, y
que **no exista ninguna forma de rotar por fuera**. El operador cambia la contraseña a mano en el
servidor y la registra bajo el mismo circuito. Entrega valor inmediato, ejercita todo el código de
gobernanza antes de que exista agente y construye la base (`app/servicios/`, HMAC) que las
versiones siguientes y la 2.0 necesitan.

**Qué entrega.**
- **Capa `app/servicios/`** creada, con credenciales y autenticación migradas (bloque A1 de
  `plan-v2.0.md`) y `app/servicios/rotacion.py` como único escritor de contraseñas (§2.4).
- **HMAC con clave en la cadena de auditoría** (§3.6), con tramo heredado y `verificar-auditoria`
  validando ambos.
- Tabla `RotacionesCredencial` (libro mayor permanente) + columnas `Credencial.via_rotacion`
  (default `manual`) y `Credencial.usada_por`.
- **Ciclo de 5 estados** con máquina de estados completa (§3.2): solicitudes con **motivo
  obligatorio**, tipos, autorización de **dos pares** con **reautenticación TOTP**, rechazo y
  cancelación; invariantes 1–5 probadas.
- **Break-glass acotado** (§2.3.1) con marca imborrable, notificación urgente, tarea de revisión y
  aviso en el arranque si hay menos de dos administradores activos.
- **Punto único de escritura** aplicado a todos los caminos de §2.4, incluida el alta por
  importación CSV.
- Registro de `dias_al_rotar`, `fecha_programada`, `desvio_dias`, `reautenticado`, `verificacion`
  y edad al autorizar.
- **Línea de tiempo por credencial** («a los 89 días, autorizada por X, motivo Y, aplicada a las
  03:14 UTC, verificación manual») y libro mayor consultable por activo.
- **Panel «Pendientes de autorización»** con aprobación en lote (una acción = una autorización
  auditada, con la edad de cada credencial visible) y cola de emergencias por revisar.
- **Notificaciones por transición** (§3.7) y **reglas de patrón básicas** en `/metricas`
  (tempranas, fuera de horario, concentración, abuso de emergencia) **en modo observación**.
- Ajustes `rotacion_*` en configuración en caliente y auditoría de toda la cadena (§3.6).

**Qué NO incluye todavía.** Agentes, jobs, `/api/agent`, telemetría, programación automática,
conectores y verificación remota: todo eso llega desde la v1.4.0.

**Cambios por capa.**
- *Modelos:* `RotacionesCredencial`, `Credencial.via_rotacion`, `Credencial.usada_por`, campos HMAC
  en `RegistroAuditoria`; migración aditiva.
- *Servicios:* creación de `app/servicios/` con `credenciales.py`, `autenticacion.py` y
  `rotacion.py`; `app/audit.py` pasa a cadena con clave.
- *API:* `/api/web/rotacion/*`; `app/routes/credentials.py` y `app/api_web/credentials.py` delegan
  el alta y el cambio de contraseña en el servicio; `app/importacion.py` deja de sobrescribir.
- *Frontend:* `/rotacion` (pendientes, lote, emergencias por revisar), timeline en la credencial,
  formularios de solicitud y autorización con reautenticación.
- *Transversal:* notificaciones, métricas, configuración en caliente, auditoría.

**Commits previstos** (orden de §9.3): modelos+migración · servicios+HMAC · API web y delegación de
las rutas de escritura · frontend · pruebas de aceptación · documentación · CHANGELOG y versión.

**Aceptación (tests).**
- Imposible ejecutar sin `AUTORIZADA`.
- Imposible autorizar la propia solicitud (prueba explícita), salvo emergencia dentro de ventana y
  marcada; fuera de ventana vuelve a exigir dos pares.
- Reautenticación obligatoria del autorizador y **rechazo del OTP por correo** como segundo factor.
- Motivo obligatorio; motivo reforzado en rotación temprana y en emergencia.
- `dias_al_rotar` / `desvio_dias` correctos (casos de 2 días y de 90 exactos).
- **Test de arquitectura**: ningún controlador ni la importación asignan `password_cifrada`, ni en
  alta ni en cambio.
- Importación CSV: el alta funciona igual y **no** genera asiento (un alta no es una rotación).
- La purga de nada borra el libro mayor; el respaldo incluye rotaciones históricas y no repone jobs.
- Cadena de auditoría: HMAC verificado, tramo heredado reconocido, cadena manipulada detectada.
- Matriz restricciones × endpoints JSON completa (regla de la Fase 9 de `plan-v2.0.md`).
- Export/import CSV y `/api/v1` intactos.

**Docs.** Sección nueva en [`manual-administrador.md`](manual-administrador.md) y
[`manual-operativo.md`](manual-operativo.md) (gobernanza, emergencia y revisión), actualización de
[`control-acceso.md`](control-acceso.md) (permisos nuevos) y de
[`referencia-configuracion.md`](referencia-configuracion.md) (`rotacion_*`); matrices CIS/ISO/OWASP.

**Feature flags y garantías.** `rotacion_pre_aprobada_politica` apagado;
`rotacion_patrones_modo_observacion` encendido. Flujo manual activo por defecto. Sin cambio de contrato en nada existente; la credencial se sigue
editando igual salvo que el cambio de contraseña exige solicitud autorizada.

**Dependencias.** Ninguna externa: parte del backend y del frontend existentes. Internamente,
`app/servicios/` y el HMAC son prerrequisitos del resto de esta versión.

### 8.2 v1.4.0 — Agente Linux + protocolo `/api/agent` + panel base

**Objetivo.** Primera rotación **desde el sistema** por agente en Linux, con el contrato completo
(§4) vigente desde el primer binario y bajo la gobernanza ya probada en la v1.3.0.

**Qué entrega.**
- Tablas `Agentes` (con `clave_publica` y `token_expira_en`), `TrabajosRotacion`,
  `TelemetriaAgente`; binding agente↔activo con CHECK uno-de.
- **API `/api/agent/*` completa** (§3.3): enrolamiento de un solo uso ligado al activo, jobs
  cifrados para el agente (X25519+HKDF+Fernet), **renovación de token en `saludo`**, anti-replay,
  ventana de validez, rate limit, límite de tamaño, auditoría de cada llamada.
- **Agente Go Linux**: módulo propio `agente/` (`cmd/passwd-agente`, `internal/{config, enrolar,
  cliente, rotador, verificador, journal, telemetria}`); rotación vía **helper root de acción
  única** (sudoers allowlist exacta) + verificación PAM in-process; journal cifrado (0600);
  telemetría acotada con `gopsutil`; unidad systemd endurecida; instalador con validaciones que
  falla si no cumple.
- **Protocolo de dos fases** (§2.2) con ACK `aplicado`/`revertido`/`fallado`, campo `verificacion =
  local`, y efectos correctos en credencial (nueva Fernet, `HistorialCredencial`,
  `password_rotada_en`), libro mayor y purga de secretos.
- Botón «Rotar ahora» en la credencial: **crea una solicitud** de la v1.3.0; el despacho solo ocurre
  tras autorización. Insignia de vía y aviso de «verificación local».
- Insignias de cobertura base (⚪/🟠/🟢/🟡/🔴) y página `/agentes` (alta, token de un solo uso
  mostrado una vez, revocar, última señal, versión, caducidad de identidad).
- Métricas: agentes conectados/sin contacto; alerta de agente sin contacto.
- Exigencia de versión mínima con período de gracia.

**Qué NO incluye todavía.** Agente Windows y programación automática (2.1.0); telemetría completa y
cobertura plena (2.2.0); conectores y mTLS/firma (2.3.0); verificación remota (2.2.0).

**Cambios por capa.** Modelos y migración · servicios (`app/servicios/agentes.py`,
`app/servicios/rotacion.py` extendido con despacho) · nuevo router `app/api_agent/` · módulo Go
`agente/` · frontend (`/agentes`, bloques en ficha y credencial) · configuración (`agentes_*`) ·
notificaciones (latido, resultados) · CI (job Go).

**Commits previstos.** modelos+migración · servicios de agentes y despacho · `app/api_agent/` ·
agente Go (puede ir en dos commits: núcleo y helper+instalador, ambos con `go vet` y pruebas en
verde) · frontend · pruebas de contrato e integración · documentación · CHANGELOG y versión.

**Aceptación (tests).**
- **Contrato del agente (Go)**: rechaza tipos de job desconocidos, jobs vencidos, un segundo job
  concurrente, rotación antes del anti-thrash, cuenta inexistente (**nunca crea**), parámetros fuera
  de patrón.
- **Contrato del backend**: job para credencial de otro activo → rechazo; agente revocado → sin
  jobs; doble uso del token de enrolamiento → rechazo; anti-replay; cuerpo que excede el límite →
  rechazo; token caducado → 401 y estado 🔴.
- **Renovación de identidad**: token renovado en `saludo`, solapamiento respetado, caducidad obliga
  a re-enrolar; dos renovaciones desde IPs distintas → anomalía registrada.
- **Integración en contenedor**: rota un usuario real, verifica, **revierte** ante fallo, sobrevive
  a reinicio con journal, purga secretos al cerrar.
- Despacho imposible sin `AUTORIZADA` (se hereda y se vuelve a probar con agente de por medio).
- Enrolamiento/revocación correctos; insignias sin estados fantasma; respaldo incluye las tablas
  nuevas y **no** repone trabajos pendientes.

**Docs.** `docs/arquitectura-agentes.md`, `docs/contrato-agente.md` (normativo, multi-despliegue),
`docs/referencia-api-agent.md`, manual de instalación del agente Linux; matrices de cumplimiento
actualizadas (OWASP API6/API8, CIS).

**Feature flags y garantías.** `agentes_enabled` encendido en desarrollo y calidad; en producción se
activa en la fase de despliegue de esta versión. `/api/v1` intacto; las credenciales con
`via_rotacion = "manual"` se comportan exactamente igual que en la v1.3.0.

**Dependencias.** v1.3.0 completa: el despacho reutiliza la autorización, el libro mayor y el punto
único de escritura.

### 8.3 2.0.0 — Las roturas R1–R8 (plan de la versión 2.0)

**Objetivo.** Ejecutar la versión mayor ya planificada en [`plan-v2.0.md`](plan-v2.0.md) en el punto
del camino donde más ayuda a esta serie: con la gobernanza y el primer agente ya probados, y antes
de ampliar el parque a Windows, telemetría y conectores.

**Qué entrega (resumen; el detalle vive en `plan-v2.0.md`).** Las ocho roturas R1–R8 y los bloques
A–C: retirada de la interfaz clásica y las plantillas, `REQUIRE_ENV_KEYS` y `RATE_LIMIT_BACKEND`
por defecto, retirada de variables obsoletas, cifrado de notas del vault, `/api/v1/inventario`
restringido y paginado, reautenticación para exportar, y el resto de la capa de servicios.

**Qué aporta a esta serie.**
- **Desaparece la duplicación de la puerta de gobernanza** (§2.4): al morir
  `app/routes/credentials.py`, el punto único de escritura queda servido por una sola interfaz. Se
  retira el código de delegación de la interfaz clásica y se simplifica el test de arquitectura.
- La reautenticación de alto impacto, ya construida en `app/servicios/` para la v1.3.0, cubre R8
  sin trabajo nuevo.
- El HMAC de la cadena (R6) ya está entregado en la v1.3.0: en esta versión solo se documenta el
  punto de corte.

**Qué NO incluye.** Nada de la serie de agentes: Windows, programación, telemetría plena,
cobertura plena, conectores y endurecimiento del canal siguen después.

**Cambios por capa.** Los de `plan-v2.0.md`, más la limpieza del código de delegación de la
interfaz clásica introducido en la v1.3.0.

**Commits previstos.** Los que fije `plan-v2.0.md` para cada rotura, con la misma disciplina de
§9.3; uno específico de esta serie: «Retira la puerta de gobernanza duplicada de la interfaz
clásica».

**Aceptación (tests).** Los criterios de cierre del apartado 9 de `plan-v2.0.md`, más: el test de
arquitectura de §2.4 sigue en verde con una sola ruta de escritura, y la rotación por agente de la
v1.4.0 funciona sin cambios tras retirar la interfaz clásica.

**Docs.** Guía de migración 1.4.0 → 2.0.0, notas de versión y manual regenerado, según
`plan-v2.0.md`; actualización de este plan (§2.4 pasa de «duplicación temporal» a «puerta única»).

**Feature flags y garantías.** Las de `plan-v2.0.md`. Para esta serie: ninguna credencial cambia de
comportamiento y ningún agente necesita reinstalarse.

**Dependencias.** v1.4.0 (para no retirar la interfaz clásica con la gobernanza a medio probar) y
las propias de `plan-v2.0.md` (A2 antes que A3, C1 antes que A3).

### 8.4 2.1.0 — Agente Windows + programación automática

**Objetivo.** Paridad en Windows y operación desatendida con la gobernanza intacta.

**Qué entrega.**
- **Agente Windows** (servicio nativo, `LocalSystem` + firewall saliente acotado): rotación de
  cuentas locales (`NetUserChangePassword`) + verificación (`LogonUser`); instalador con
  validaciones y creación de la clave de identidad con ACL equivalentes a 0600; mismas 14
  prohibiciones y misma renovación de token.
- **Planificador**: barrido que crea **solicitudes** (no jobs) al acercarse la fecha de política,
  con **jitter** para no generar tormentas. **Reutiliza `_mantenimiento_periodico`**
  (`app/main.py:191-218`) en vez de introducir un bucle nuevo, y se apoya en el índice único
  `(credencial_id, fecha_programada)` para ser idempotente aunque el despliegue tenga varios
  procesos.
- Conexión del panel de aprobación en lote con el despacho real.
- **Umbral de no contacto** con alerta y sugerencia de estado (sin auto-marcar).
- Notificaciones completas del ciclo, incluida la emergencia urgente y su revisión.

**Qué NO incluye todavía.** Ficha de telemetría completa, copia opt-in de specs, cobertura plena,
verificación remota, conectores, endurecimiento del canal.

**Cambios por capa.** Agente (target Windows + servicio) · CI (build `windows/amd64`, pruebas con
mock del rotador en runners Linux y batería real en runner Windows) · planificador dentro del ciclo
de vida existente · panel (programación por credencial y por etiqueta del activo) ·
notificaciones · configuración.

**Commits previstos.** agente Windows (rotador + verificador) · instalador y servicio · planificador
e idempotencia · panel de programación · pruebas · documentación · CHANGELOG y versión.

**Aceptación (tests).**
- Misma batería de contrato sobre cuentas locales Windows, incluida «nunca crea cuenta».
- Programación con jitter probada de forma determinista; **dos procesos del planificador no generan
  solicitudes duplicadas** (prueba del índice único).
- **Ningún job despachado sin autorización** (se vuelve a probar con programación automática).
- Latido y no-contacto notifican; la sugerencia de estado nunca marca sola.
- La instalación valida permisos y regla de firewall, y falla si no se cumplen.

**Docs.** Manual de instalación del agente Windows; actualización de `arquitectura-agentes.md` y de
[`manual-operativo.md`](manual-operativo.md) (operación desatendida).

**Feature flags y garantías.** La programación automática se puede desactivar por ajuste. Los
servidores sin agente siguen 100 % manuales.

**Dependencias.** 2.0.0 (una sola interfaz) y v1.4.0 (protocolo y panel de agentes).

### 8.5 2.2.0 — Telemetría, cobertura plena y verificación remota

**Objetivo.** El monitoreo pedido en la consulta original, la visibilidad total de cobertura y el
cierre del riesgo de verificación solo local (§2.2.1).

**Qué entrega.**
- **Ficha de telemetría del activo**: specs detectadas, recursos actuales, latido e histórico breve
  (alcance recortado según §4.4).
- **Copia opt-in de specs a los campos de hardware** del activo: auditable, nunca silenciosa.
- **Sugerencia de estado activo/inactivo**: alertar y sugerir; el admin decide; nunca auto-marcar.
- **Verificación remota post-rotación** (corrección H4): tras un ACK `aplicado`, el backend intenta
  la conexión según `servicio`+`puerto` de la credencial, bajo límite de tasa y auditoría. El
  resultado se guarda en `verificacion` y **alerta** si falla; no revierte por sí solo, porque el
  fallo puede ser de red o de política y revertir a ciegas sería peor.
- **Cobertura plena**: tarjeta «X de Y activos rotables con agente (Z %)» y cola de activos sin
  agente; filtros de cobertura en todos los listados; insignias completas sin estados fantasma.
- **Alertas de regresión** (activo que pierde su agente) y de **IP distinta** (con nota de NAT).
- Retención de telemetría configurable con tarea de purga, enganchada al mantenimiento existente.
- **Reglas de patrón completas** (§3.8) y **salida del modo observación**: se activan las
  notificaciones regla por regla, con los umbrales calibrados sobre los datos reales acumulados
  desde la v1.3.0.

**Qué NO incluye todavía.** Conectores de red y endurecimiento del canal (2.3.0).

**Cambios por capa.** Servicios de telemetría, cobertura y verificación remota · frontend (ficha de
activo, métricas, listados, filtros) · configuración (`agentes_retencion_telemetria_dias`,
`agentes_alertar_ip_distinta`, `rotacion_patrones_modo_observacion`) · notificaciones · purga
programada.

**Commits previstos.** servicios de telemetría y retención · verificación remota · cobertura y
filtros · frontend · calibración y activación de reglas · pruebas · documentación · CHANGELOG y
versión.

**Aceptación (tests).**
- Los indicadores reflejan el estado real en todo listado y ficha; el contador de cobertura cuadra
  con el inventario (prueba de consistencia).
- Specs opt-in auditable y nunca silenciosa; el estado del activo no se marca solo.
- Verificación remota: éxito y fallo quedan en `verificacion`; el fallo alerta y **no** revierte.
- La retención respeta el ajuste y la purga no toca el libro mayor.
- Regresión de cobertura e IP distinta notifican.
- Telemetría que excede el límite de tamaño es rechazada y el agente degrada a lo esencial.

**Docs.** [`manual-operativo.md`](manual-operativo.md) (monitoreo y cobertura),
[`referencia-configuracion.md`](referencia-configuracion.md), actualización de §2.2.1 de este plan
cuando la verificación remota esté entregada.

**Feature flags y garantías.** La telemetría es de solo lectura de negocio: no altera credenciales
ni rotaciones. La verificación remota se puede desactivar por ajuste.

**Dependencias.** v1.4.0 (telemetría básica y protocolo) y 2.1.0 (alertas de latido).

### 8.6 2.3.0 — Conectores de red y endurecimiento del canal

**Objetivo.** Extender la rotación con gobernanza a switches, routers y firewalls —lo «en veremos»
de la consulta— y cerrar el canal del agente para producción a escala. Se entregan juntos porque
ampliar el parque de dispositivos sin el canal endurecido sería ampliar la superficie antes de
cerrarla.

**Qué entrega.**
- **Conectores**: conector SSH por plantilla de fabricante, con **uno de referencia de extremo a
  extremo** (Cisco IOS/IOS-XE, Aruba o MikroTik) y SNMPv3 USM opcional; mismo ciclo de gobernanza,
  verificación con la credencial nueva (`verificacion = remota`) y rollback; `known_hosts` con
  fijación de huella en la base de datos y alerta ante cambio; insignia propia en dispositivos;
  *threat model* documentado (§6).
- **Endurecimiento del canal**: mTLS opcional agente↔backend; *pinning* de certificado
  **recomendado por defecto en producción**; binarios del agente **firmados** con verificación en
  el instalador; auto-actualización firmada **solo si se decide en esta versión** (hasta entonces
  prohibida por el contrato, §4.1.10); alineación de contenedores con el endurecimiento de la 2.0.

**Qué NO incluye.** Lo declarado fuera de alcance en §10.

**Cambios por capa.** Servicios de conectores y plantillas · `known_hosts` en modelo y migración ·
agente (verificación de firma, pinning, mTLS opcional) · CI (firma de binarios y rotación de la
clave de firma) · frontend (insignia y ficha de dispositivo) · documentación de egress del backend.

**Commits previstos.** modelo de `known_hosts` y migración · conector SSH y plantilla de referencia ·
SNMPv3 · pinning y mTLS en agente y backend · firma de binarios en CI · frontend · pruebas ·
documentación · CHANGELOG y versión.

**Aceptación (tests).**
- Un fabricante de referencia rotado de extremo a extremo bajo gobernanza (emulador o laboratorio).
- Un fallo de conexión no deja estados indeterminados; la auditoría queda completa.
- Egress del backend acotado y documentado.
- Huella de host cambiada → alerta y rechazo.
- Binario alterado rechazado por el instalador; MITM con CA propia rechazado con pinning activo;
  rotación de la clave de firma documentada y probada.

**Docs.** `docs/conectores-red.md` (plantillas y threat model); actualización de
`contrato-agente.md` (firma y pinning) y guía de operación.

**Feature flags y garantías.** Los servidores con agente no cambian de comportamiento. El pinning se
activa por ajuste y se recomienda en producción.

**Dependencias.** v1.3.0 (gobernanza), v1.4.0 (canal del agente) y 2.2.0 (insignias y estado).

### 8.7 Resumen del camino

| Versión | Contenido | Por qué ahí |
|---|---|---|
| **1.2.x** | Solo correcciones | Estabilizar lo publicado |
| **1.3.0** | Servicios + HMAC + gobernanza + punto único de escritura | Cierra el bypass antes de dar poder a nadie |
| **1.4.0** | Agente Linux + `/api/agent` + panel base | Rotación real pronto, sobre gobernanza probada |
| **2.0.0** | Roturas R1–R8 de `plan-v2.0.md` | Muere la interfaz clásica; la puerta queda única |
| **2.1.0** | Agente Windows + programación automática | Paridad y operación desatendida |
| **2.2.0** | Telemetría, cobertura plena y verificación remota | Cierra el riesgo de verificación solo local |
| **2.3.0** | Conectores de red + endurecimiento del canal | Amplía el parque con el canal ya cerrado |

### 8.8 Coordinación con `plan-v2.0.md`

- El camino conjunto es `1.2.x → 1.3.0 → 1.4.0 → 2.0.0 → 2.1.0 → 2.2.0 → 2.3.0`. Sustituye al
  apartado 3 de [`plan-v2.0.md`](plan-v2.0.md), que preveía `1.2.x → 1.3.0 → 2.0.0 → 2.1.0`.
- La **v1.3.0 asume el contenido que `plan-v2.0.md` le asignaba** (avisos de retirada R1/R4/R7,
  capa de servicios para autenticación y credenciales, matriz de permisos, pruebas de navegador) y
  le añade la gobernanza de rotación y el HMAC. No son planes que compitan por la misma versión:
  comparten `app/servicios/` y la reautenticación, que es justo lo que la Fase 10 pide generalizar.
- La **v1.4.0 es una versión intercalada**: aditiva, sin roturas, y no condiciona ninguna de las
  ocho roturas de la 2.0.
- **De la 2.1.0 en adelante ambos planes comparten numeración.** El bloque D de `plan-v2.0.md`
  (funciones nuevas: sesiones activas, contraseñas filtradas, papelera del vault, generador
  configurable, enlaces de un solo uso, cola de correo, WebAuthn) no es bloqueante y se reparte
  entre esas versiones. Cada PR declara qué lleva de cada plan, de modo que el orden de la serie de
  agentes —Windows, telemetría, conectores— no se altera.
- Mientras conviva la interfaz clásica (v1.3.0 y v1.4.0), la puerta de gobernanza está
  **duplicada a propósito** (§2.4). La 2.0.0 la deja única; ese es uno de sus beneficios concretos
  para esta serie y conviene anotarlo en sus notas de versión.
- Al iniciar cada versión: registrar su fase en [`hoja-de-ruta.md`](hoja-de-ruta.md) y declarar la
  versión objetivo en el PR (plantilla de PR + [`versionado.md`](versionado.md)).

---

## 9. Checklists de operación del plan

### 9.1 Arranque de una versión

1. Confirmar vigencia de las decisiones de §1.6 (o reabrir en consulta las que hayan cambiado).
2. Releer §1.7 y **volver a verificar contra el código** las premisas que afecten a esa versión: un
   plan escrito hace meses envejece, y esta serie ya tuvo trece supuestos corregidos.
3. Registrar la fase en [`hoja-de-ruta.md`](hoja-de-ruta.md) con su alcance.
4. Crear rama `feature/<version>-<nombre>` y declarar la versión objetivo en el PR.
5. Implementar en el orden del desglose: **modelos → servicios → API → frontend → pruebas → docs**.
6. Un commit por capa, con su verificación en verde (§9.3).
7. CI completa al final de la versión; actualizar matrices de cumplimiento.
8. Validar en calidad con contenedores de prueba del agente antes de tocar producción
   ([`ambientes.md`](ambientes.md)).

### 9.2 Cierre de una versión

1. Entradas en `CHANGELOG.md` bajo `[Sin publicar]` (categorías Añadido/Cambiado/Corregido…).
2. Versión en `app/__init__.py` y `pyproject.toml`, sección `[X.Y.Z]` en el CHANGELOG y liberación
   SemVer según [`versionado.md`](versionado.md).
3. Verificación en caliente (`/healthz` expone la versión) y actualización de
   [`README.md`](README.md) si hay documentos nuevos.
4. Completar las filas del registro de ejecución (§9.4): ninguna versión se da por cerrada sin él.

### 9.3 Disciplina de commit y verificación

**Regla:** un commit por capa del desglose, en orden, y **ningún commit sin su verificación en
verde**. La traza de la ejecución vive en el historial de git, no en la memoria de nadie.

| # | Commit | Verificación obligatoria antes de commitear |
|---|---|---|
| 1 | Modelos + migración aditiva (`schema_sync` + Alembic) | `pytest tests/test_schema.py tests/test_migraciones_alembic.py` |
| 2 | Servicios (`app/servicios/`) | `pytest` de los servicios + `ruff check app tests migrations` + `bandit -r app --severity-level medium -q` |
| 3 | API (`app/api_web/`, `app/api_agent/`) | pruebas de la API + matriz restricciones × endpoints |
| 4 | Agente Go (`agente/`), en las versiones que lo tocan | `go vet ./...` + `govulncheck ./...` + pruebas unitarias Go |
| 5 | Frontend Next.js | `pnpm lint` + `pnpm vitest run` |
| 6 | Pruebas de la versión (los criterios de aceptación del desglose) | `pytest --cov=app --cov-report=term-missing --cov-fail-under=70` |
| 7 | Documentación (manuales, referencias, matrices de cumplimiento) | enlaces relativos resueltos; `docs/README.md` al día |
| 8 | `CHANGELOG.md` + versión | `pytest tests/test_version.py` |

Reglas de forma:

- **Un commit nunca mezcla capas.** Si una capa no funciona sola, se entrega detrás de un *feature
  flag* apagado (regla §8.0.5), nunca mezclada con la siguiente.
- **Mensaje en castellano, imperativo o tercera persona**, al estilo del historial del repositorio
  («Añade el libro mayor de rotaciones», «Evita que la importación sobrescriba contraseñas»).
  Primera línea ≤ 72 caracteres.
- El **cuerpo** del mensaje declara la **versión objetivo** y el **apartado de este plan** que cubre
  (p. ej. «v1.3.0 · §2.4 punto único de escritura»), más la verificación ejecutada.
- **Nada de secretos ni de datos reales** en el mensaje, el diff o los *fixtures*.
- Si una verificación falla, **no se commitea**: se corrige y se vuelve a ejecutar. No se commitea
  «para arreglarlo en el siguiente».
- Al cerrar la versión, el PR enlaza este plan y lista los commits por capa, de modo que la revisión
  pueda seguir el mismo orden.

### 9.4 Registro de ejecución

Tabla viva: se rellena **en el mismo commit de cierre de cada capa**, de modo que el plan guarde la
traza de cómo se construyó y con qué se verificó.

| Fecha | Versión | Capa | Commit | Verificación ejecutada | Notas |
|---|---|---|---|---|---|
| 2026-11-18 | v1.3.0 | Modelos + migración aditiva `0010` | `3e6a000` | `pytest tests/test_schema.py tests/test_migraciones_alembic.py`, `ruff` | Libro mayor, `via_rotacion`, `usada_por`, `hash_algoritmo` |
| 2026-11-18 | v1.3.0 | Servicios + HMAC de auditoría | `9acb7b3` | `pytest` (289), `ruff`, `bandit` | `app/servicios/{rotacion,autenticacion,patrones}.py`; cadena firmada con tramo heredado |
| 2026-11-18 | v1.3.0 | API web + delegación de las rutas de escritura | `639b13b` | `pytest` (289), `ruff`, `bandit` | `/api/web/rotacion/*`; seis pruebas existentes adaptadas al ciclo |
| 2026-11-18 | v1.3.0 | Frontend | `d63414d` | `tsc`, `eslint`, `vitest` (21), `next build` | Página `/rotacion` y panel en la ficha de la credencial |
| 2026-11-18 | v1.3.0 | Pruebas de aceptación | `165b751` | `pytest --cov` (314, 83,66 %) | 25 pruebas, incluida la de arquitectura del punto único de escritura |
| 2026-11-18 | v1.3.0 | Documentación | `f914f45` | Enlaces de `docs/` resueltos, `pytest` | Manuales, control de acceso, configuración, CLI, arquitectura y matrices |
| 2026-11-18 | v1.3.0 | CHANGELOG | (este) | `pytest tests/test_version.py` | Entradas bajo `[Sin publicar]`; **la versión no se publica todavía** |
| 2026-11-18 | v1.3.0 | Aviso de dos administradores (defecto propio) | `3dc9e44` | `pytest`, `ruff` | Los manuales afirmaban un aviso que no existía. De paso, `migrations/env.py` silenciaba los loggers de `app.*` |
| 2026-11-18 | v1.3.0 | Avisos de retirada R1, R4, R7 | `eac000c` | `pytest tests/test_avisos_retirada.py`, suite, `ruff` | Cabecera `Deprecation` en la superficie Jinja, aviso de configuración obsoleta y registro del cambio de `/api/v1/inventario` |
| 2026-11-18 | v1.3.0 | Servicio de credenciales (A1) | `2145361` | pruebas del servicio sin HTTP + suite | La entrega de una contraseña en claro dejó de estar escrita dos veces |
| 2026-11-19 | v1.3.0 | Autenticación: login, contraseña, cierre (A1) | `0815a61` | ídem + barrido de `test_bypass_mfa.py` | Una sola implementación del login; el hash ficticio deja de calcularse dos veces por proceso |
| 2026-11-19 | v1.3.0 | Autenticación: segundo factor y recuperación (A1) | `e0e8bab` | ídem | **Tres divergencias de seguridad** halladas al unificar, las tres con la interfaz clásica en el lado débil |
| 2026-11-19 | v1.3.0 | Matriz de permisos del registro de rutas (A4) | `9914120` | `pytest tests/test_matriz_permisos.py`, suite, prueba de que la prueba falla sin política | `_dep.permiso_requerido` hace autodescriptivo el registro de rutas |
| 2026-11-19 | v1.3.0 | Pruebas de navegador en CI (C1) | `944b628` | 22 de 22 desde cero (4,4 min), `eslint`, `tsc` | Backend + frontend `standalone` + receptor SMTP local; job `navegador` nuevo |
| 2026-11-19 | v1.3.0 | Corrección del aviso R4 (defecto propio) | `db668bf` | `pytest`, `ruff` | El aviso pedía sustituir `PASSWD_NOTIFY_ENABLED`, que sigue gobernando las alertas: habría dejado sin ellas a quien lo siguiera |
| 2026-11-19 | v1.3.0 | Pre-release `v1.3.0-rc.1` | `047d6e2` | suite (393), `ruff`, `GET /healthz` | La política admite pre-releases; `prelanzamiento.yml` publica al empujar la etiqueta |
| 2026-11-19 | v1.3.0 | Regla de nombres de rama | `0e1f0f0` | `ruff`, `pytest tests/test_version.py` | `CLAUDE.md` nuevo, para que la regla se aplique sola en sesiones futuras |
| 2026-11-19 | v1.3.0 | Ciclo de gobernanza en el navegador | `d1e567f` | 7 de 7 (3,5 min), `eslint`, `tsc` | Dos personas, dos segundos factores; la regla de dos pares comprobada en la interfaz real |
| 2026-11-19 | v1.3.0 | Documentación y notas de versión | `29fde2e` | 29 de 29 en navegador, enlaces de `docs/` resueltos | Notas 1.3.0, Fase 9 como parcial, registro de ejecución al día |
| 2026-11-19 | v1.3.0 | Publicación de la 1.3.0 | (este) | `pytest` (400), `ruff`, `GET /healthz` → `1.3.0` | Versión, CHANGELOG y cierre del registro |
| 2026-11-20 | v1.3.0 | Smoke de `/api/web` sobre MySQL al día | (este) | `scripts/verificar_api_web.py`, `pytest`, `ruff` | Lo destapó la CI del PR: el script no es parte de `pytest` y la verificación local nunca lo ejecutó |

**Estado de la v1.3.0: cerrada.** Se entregó todo el alcance que este plan comparte con
[`plan-v2.0.md`](plan-v2.0.md) §3: gobernanza de rotación, avisos de retirada R1/R4/R7, migración a
`app/servicios/` de credenciales y de la autenticación completa, matriz de permisos generada del
registro de rutas y pruebas de navegador en CI. Antes de publicar se liberó el pre-release
`v1.3.0-rc.1` para pruebas funcionales.

Queda **fuera** de esta versión, y pasa a la 2.0, el punto 2 de la Fase 9: retirar la interfaz
clásica. Ya está avisado —cabecera `Deprecation`, aviso en las páginas— y migrar a `app/servicios/`
el inventario, los usuarios y los accesos sigue pendiente. Decirlo aquí es parte del trato: una
versión se cierra con lo que entregó y con lo que no.

**Arranque de la v1.4.0 (§9.1, paso 2).** Premisas de §8.2 vueltas a comprobar contra `main` el
2026-11-25:

| Premisa | Resultado |
|---|---|
| `max_request_bytes` de 64 KB (`app/config.py:123`) | Vigente |
| `_mantenimiento_periodico` reutilizable (H9) | Vigente; se movió a `app/main.py:253` |
| Patrón `token_hash` de `TokenApi` para la identidad del agente | Vigente (`app/models.py:717-735`) |
| Libro mayor con `despachada`, `via` y `verificacion` | Vigente desde la migración `0010` |
| Libro mayor con `agente_id` (§3.1) | **No existe**: entra en la migración `0011` |
| `Credencial.via_rotacion` y `usada_por` | Vigentes (`app/models.py:429, 438`) |
| X25519 + HKDF disponibles en `cryptography` | Vigente (`>=41.0`); aún sin uso en `app/` |
| Módulo `agente/` y job Go en CI | No existen: los crea esta versión |

| Fecha | Versión | Capa | Commit | Verificación ejecutada | Notas |
|---|---|---|---|---|---|
| 2026-11-25 | v1.4.0 | Arranque | `d66521a` | enlaces de `docs/` resueltos, `pytest tests/test_version.py` | Rama `feature/1.4.0-agente-linux`; hoja de ruta; nginx en una sola versión en todo el repositorio |
| 2026-11-25 | v1.4.0 | Modelos + migración aditiva `0011` | `1e08fe7` | `pytest tests/test_schema.py tests/test_migraciones_alembic.py tests/test_agentes_modelo.py`, suite, `ruff`, `bandit`, `scripts/verificar_api_web.py`; paridad de índices, `UNIQUE`, `CHECK` y FK entre modelo y migración | `agentes`, `trabajos_rotacion`, `telemetria_agente`; `agente_id` en el libro mayor **sin FK** (el reconciliador no las crea). Un agente vigente por activo y un trabajo activo por agente, garantizados por `UNIQUE` sobre columnas que se anulan al cerrar. Estado del agente reducido a `pendiente`/`activo`/`revocado`: conexión y falta de contacto se derivan. Las claves `agentes_*` pasan al commit de servicios, que es quien las lee |
| 2026-11-25 | v1.4.0 | Servicios (2a): identidad del agente y cifrado | `de64607` | `pytest tests/test_servicio_agentes.py` (20), suite, `ruff`, `bandit`, `scripts/verificar_api_web.py`, `gitleaks` sobre el vector; tres garantías quitadas a mano y su prueba falla | Alta, enrolamiento de un solo uso, identidad de vida corta con solapamiento, anomalía de IP, revocación, cobertura derivada, versión mínima. **H14**: el sellado al agente es en la entrega, no en reposo. Ajustes `agentes_*` |
| 2026-11-25 | v1.4.0 | Servicios (2b): despacho y resultado | `f473d89` | `pytest tests/test_despacho_agentes.py` (17) y `tests/test_rotacion_gobernanza.py`, suite, `ruff`, `bandit`, `scripts/verificar_api_web.py`; cinco garantías quitadas a mano y su prueba falla | Despacho solo de lo `AUTORIZADA`, entrega sellada, resultado único por trabajo y escritura por `_escribir_password`; pendiente vencido vuelve a `AUTORIZADA`, entregado sin respuesta queda «sin confirmar» con sus secretos hasta que una persona lo resuelve. Respaldo: agentes revocados, nunca trabajos, y un asiento despachado vuelve a `AUTORIZADA` con nota. La prueba de arquitectura del punto único recorre ahora todo `app/` |
| 2026-11-25 | v1.4.0 | Servicios (3a): telemetría | `6d3ef75` | `pytest tests/test_servicio_agentes.py` (22), suite, `ruff`, `bandit`, `scripts/verificar_api_web.py`; el acotado quitado a mano y su prueba falla | Pieza de servicio que faltaba para la ruta de telemetría: acota porcentajes, discos y textos, y marca `recortada` en vez de ocultarlo. Commit propio para no mezclar capas con la API |
| 2026-11-25 | v1.4.0 | API del agente (3b): `/api/agent` | `36d4410` | `pytest tests/test_api_agente.py` (9), matriz de permisos y barrido pre-MFA, suite, `ruff`, `bandit`, `scripts/verificar_api_web.py`; cuatro garantías quitadas a mano y su prueba falla (una no fallaba: la prueba de superficie corría sin agentes en la base y se endureció) | Cinco rutas, 404 con el interruptor apagado, límite por IP y por agente, tope propio de 16 KB para la telemetría y rechazos auditados que sobreviven al rollback. `saludo` pasa a POST. `/api/agent` se excluye de la matriz como `/api/v1`, con su propia prueba que enumera el prefijo |
| 2026-11-25 | v1.4.0 | API del panel (3c): `/api/web/agentes` | (este) | `pytest tests/test_api_web_agentes.py` (8), matriz de permisos, suite, `ruff`, `bandit`, `scripts/verificar_api_web.py` con el ciclo del agente; tres garantías quitadas a mano y su prueba falla | Permisos `agentes.ver`/`agentes.gestionar`; **reautenticación** para el alta y para reemitir el token de instalación (decisión del usuario), y para resolver a mano un «sin confirmar»; despachar de nuevo una rotación autorizada; el smoke recorre por HTTP alta → enrolar → despacho → resultado → revocación, sobre MySQL en la CI |

Al arrancar cada versión se añaden sus filas según el desglose de §8. Una versión cerrada no deja
filas pendientes.

---

## 10. Fuera de alcance de esta serie (documentado, no comprometido)

- **Rotación de cuentas de dominio** (AD/LDAP) y de **claves de servicio** (bases de datos, colas).
- **Vault personal** (`EntradaVault`): aunque tiene `password_rotada_en` (`app/models.py:792`), es
  un almacén privado de cada usuario, no inventario, y **no entra** en el ciclo de gobernanza.
- Conectores por API REST de fabricantes más allá de SSH/SNMPv3 (v2.3.0).
- **Responsabilidad nominal por activo** («operador a cargo»): §3.10 resuelve la autorización con
  el modelo existente; un modelo de propiedad por activo es una funcionalidad aparte.
- Zero-knowledge del vault (candidata de la Fase 10 de [`plan-v2.0.md`](plan-v2.0.md); decisión
  aparte).
- **Multi-tenancy**: el contrato del agente (§4) hace el despliegue seguro para cualquier
  organización que use el sistema, pero el sistema sigue siendo de instancia única.
- LDAP/OIDC y WebAuthn (ya en la hoja de ruta general, fuera de esta serie).
- Alta disponibilidad multinodo y auditoría en tiempo real (diferidos en
  [`hoja-de-ruta.md`](hoja-de-ruta.md)).
