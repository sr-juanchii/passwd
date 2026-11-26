# Notas de la versión 1.4.0

| | |
|---|---|
| **Versión** | 1.4.0 |
| **Etiqueta** | `v1.4.0` |
| **Fecha** | pendiente de publicación |
| **Versión anterior** | 1.3.0 (2026-11-20) |
| **Tipo (SemVer)** | MENOR — funcionalidad nueva retrocompatible, apagada por omisión |
| **Fase de la hoja de ruta** | Serie de agentes de rotación ([`plan-rotacion-agentes.md`](plan-rotacion-agentes.md) §8.2), fuera de las fases 9–12 |
| **Migración de datos** | `0011` (aditiva) |
| **Compatibilidad** | API `/api/v1` sin cambios (rutas y claves congeladas por prueba); variables de entorno anteriores aceptadas; las credenciales manuales se comportan exactamente como en la 1.3.0 |
| **Pre-release** | `v1.4.0-rc.1`, para pruebas funcionales en calidad |

El registro completo, entrada por entrada, está en [`CHANGELOG.md`](../CHANGELOG.md). Este
documento cataloga los cambios, explica qué hacer al actualizar y deja constancia de cómo se
verificó la versión.

> **Lo que cambia de verdad en esta versión:** la rotación que dos personas autorizan en la 1.3.0
> ya no tiene por qué aplicarla nadie a mano. Un agente instalado en el servidor Linux recibe el
> trabajo **solo después** de la autorización, cambia la contraseña de la cuenta local, comprueba
> que la nueva funciona y, si no, deja la anterior. Todo está **apagado por omisión**: hasta que
> alguien lo activa, la 1.4.0 se comporta como la 1.3.0. Si solo lee un apartado, lea el 2.

## 1. Catálogo de cambios

Cada cambio lleva un identificador para poder citarlo en revisiones y auditorías.

### Agente de rotación para Linux

| ID | Cambio | Dónde |
|---|---|---|
| AGE-01 | **Agente en Go** (`passwd-agente`), binario estático sin dependencias, que corre como un usuario **sin privilegios** y sin forma de ganarlos. Late, envía telemetría acotada y ejecuta solo lo que el backend le entrega tras una autorización. | `agente/cmd/passwd-agente`, `agente/internal/` |
| AGE-02 | **Helper root de acción única** (`passwd-agente-helper`), sin sudo ni setuid (hallazgo H15): systemd lo arranca por cada conexión a un socket local que solo el usuario del agente puede abrir, comprueba quién llama (`SO_PEERCRED`), atiende una petición y termina. **Sin red.** Solo toca las cuentas de una lista que es de root, y solo si existen: **nunca crea una cuenta**. | `agente/cmd/passwd-agente-helper`, `agente/internal/helper` |
| AGE-03 | **Dos fases con journal**: antes de tocar la cuenta, el agente apunta en un journal cifrado (AES-256-GCM, 0600) qué va a hacer; aplica, **verifica la nueva con PAM** y, si no autentica, **restaura la anterior**. Tras un reinicio a mitad, el journal le dice qué pasó y lo informa. | `agente/internal/ejecutor`, `agente/internal/journal` |
| AGE-04 | **Antes de aplicar se comprueba que la contraseña actual del inventario sigue valiendo** en el servidor. Si alguien la cambió por fuera, no se toca nada y se informa. | `agente/internal/helper` |
| AGE-05 | **Contrato del trabajo** validado en el agente: tipo admitido, cuenta con patrón, sin saltos de línea ni NUL, ventana vigente, un solo trabajo a la vez y **anti-thrash local** de una hora. | `agente/internal/contrato` |
| AGE-06 | **Instalador** `instalar.sh`: no toca nada hasta que pasan todas las comprobaciones (root, systemd, arquitectura, **SHA-256 de los binarios** contra el archivo de sumas, backend https, cuentas existentes, token). Unidades systemd endurecidas (exposición 1,2 el agente y 1,6 el helper, sobre 10) y salida de red del agente **solo hacia el backend** y el DNS. Modo `--simular`. | `agente/instalacion/` |

### Protocolo `/api/agent`

| ID | Cambio | Dónde |
|---|---|---|
| PRO-01 | **API propia del agente**, separada de `/api/web` y `/api/v1`, con identidad de máquina (`Authorization: Bearer`), sin cookies ni CSRF. Con `agentes_enabled` apagado, **todo el prefijo responde 404**. | `app/api_agent/` |
| PRO-02 | **Enrolamiento de un solo uso** ligado al activo: el token de instalación caduca en una hora y no sirve dos veces. El agente genera su par X25519 y solo envía la clave pública. | `app/servicios/agentes.py` |
| PRO-03 | **Identidad de vida corta** (24 h por omisión) **renovada en cada saludo**, con un solapamiento para no perder la respuesta. Una identidad caducada no se resucita: hay que reinstalar con un token nuevo. Dos renovaciones desde IPs distintas en la misma vida son una **anomalía** auditada y alertada. | ídem |
| PRO-04 | **El trabajo nunca viaja ni se guarda en claro** (hallazgo H14): en reposo, cifrado con la clave del backend; al entregarlo, **sellado a la clave pública del agente** (X25519 + HKDF-SHA256 + Fernet). Vector compartido entre Python y Go. | `app/servicios/cifrado_agente.py`, `agente/internal/sobre`, `tests/vectores/` |
| PRO-05 | **Un resultado por trabajo** (anti-replay), ventana de validez, un agente no cierra el trabajo de otro, y el agente no puede declarar una verificación remota que no hizo. | `app/servicios/rotacion.py` |
| PRO-06 | **Límites**: de tasa por IP, por agente y de enrolamiento; **tope de cuerpo** de 4 KiB por petición (16 KiB la telemetría), que se rechaza antes de autenticar. Todo rechazo queda en la bitácora; el latido rutinario no, para no esconder lo que importa. | `app/api_agent/` |
| PRO-07 | **Versión mínima del agente** con periodo de gracia. | `app/servicios/agentes.py` |

### Rotación y gobernanza

| ID | Cambio | Dónde |
|---|---|---|
| ROT-11 | Cada credencial elige **vía de rotación**: «a mano» (como en la 1.3.0, el valor por omisión) o **por el agente de su activo**. Una credencial no puede rotar por el agente de otro activo. | `app/servicios/agentes.py` |
| ROT-12 | **Autorizar despacha.** Con la vía «agente», la autorización de la 1.3.0 crea el trabajo; nada se despacha sin ella. Si no se puede despachar (agente sin contacto, interruptor apagado), la autorización **se mantiene** y queda dicho por qué. | `app/servicios/rotacion.py` |
| ROT-13 | **Rotación «sin confirmar»**: si el agente recogió el trabajo y calla, la credencial queda bloqueada para otra rotación hasta que un administrador, **reautenticándose**, declare si quedó la nueva o sigue la anterior. Alerta al equipo de seguridad. | ídem, `app/api_web/rotacion.py` |
| ROT-14 | **Anti-thrash del backend**: no se despacha una segunda rotación de la misma credencial en 24 h, salvo por la vía de emergencia. | `app/servicios/rotacion.py` |
| ROT-15 | El libro mayor anota **qué agente** aplicó la rotación y que la verificación fue **local** (en el propio servidor). | `app/models.py` |

### Panel

| ID | Cambio | Dónde |
|---|---|---|
| PAN-01 | En la **ficha de cada servidor, hipervisor y VM**, el agente con su cobertura: ⚪ sin agente, 🟠 pendiente de instalar, 🟢 conectado, 🟡 sin contacto, 🔴 identidad caducada. Alta y reinstalación con **reautenticación**, y el token de instalación se ve **una sola vez**, con la orden de instalar que lo lee por la entrada estándar. | `frontend/src/components/agentes/` |
| PAN-02 | En la **ficha de rotación** de la credencial: «Rotar con el agente» / «Rotar a mano», «Enviar al agente» y la resolución de las rotaciones sin confirmar. | `frontend/src/components/rotacion/panel-credencial.tsx` |
| PAN-03 | Página **`/agentes`** con el parque entero, y **métricas** de agentes (conectados, sin contacto, caducados, pendientes, rotaciones sin confirmar) en `/metricas`. | `frontend/src/app/(app)/agentes`, `frontend/src/app/(app)/metricas` |
| PAN-04 | **Alerta de agente sin contacto** desde el mantenimiento periódico, una vez por silencio. | `app/servicios/agentes.py`, `app/main.py` |
| PAN-05 | Permisos `agentes.ver` (administrador, operador, auditor) y `agentes.gestionar` (administrador). Un agente de un activo restringido no existe para quien no alcanza el activo. | `app/rbac.py`, `app/api_web/agentes.py` |
| PAN-06 | Diez ajustes nuevos en el grupo «Agentes de rotación» de la consola, todos en caliente: `PASSWD_AGENTES_ENABLED` (apagado), `PASSWD_ROTACION_VENTANA_JOB_MIN` (30), `PASSWD_ROTACION_ANTI_THRASH_HORAS` (24), `PASSWD_AGENTES_TOKEN_VIDA_HORAS` (24), `PASSWD_AGENTES_UMBRAL_SIN_CONTACTO_HORAS` (1), `PASSWD_AGENTES_TELEMETRIA_INTERVALO_MIN` (15), `PASSWD_AGENTES_RETENCION_TELEMETRIA_DIAS` (30), `PASSWD_AGENTES_VERSION_MINIMA` (vacía), `PASSWD_AGENTES_GRACIA_VERSION_DIAS` (14) y `PASSWD_AGENTES_ALERTAR_IP_DISTINTA` (sí). | `app/config.py`, `app/ajustes.py` |

### Datos

| ID | Cambio | Dónde |
|---|---|---|
| DAT-01 | Migración **`0011`**, aditiva: tablas `agentes`, `trabajos_rotacion` y `telemetria_agente`, y columnas nuevas en credenciales y libro mayor. Una base de la 1.3.0 se pone al día sin perder el libro mayor. | `app/models.py`, `migrations/` |
| DAT-02 | **Invariantes en la base de datos**, no solo en el código: un único agente vigente por activo y un único trabajo activo por agente, con columnas `UNIQUE` anulables. | `app/models.py` |
| DAT-03 | **Respaldo**: repone los agentes (revocados, sin identidad válida) y **nunca** los trabajos: un restore no resucita un trabajo con secretos y ventana vencida. | `app/backup.py` |

### Correcciones

| ID | Cambio | Dónde |
|---|---|---|
| COR-01 | **Las fechas del panel salían con el desfase de la zona horaria.** El backend envía UTC sin zona y el navegador lo leía como hora local: en Caracas, cuatro horas de más en la auditoría, los tokens, las concesiones, el último acceso y el historial. Defecto anterior a esta versión. Una prueba impide que vuelva. | `frontend/src/lib/fechas.ts` |
| COR-02 | El diálogo de autorizar ya no se cierra cuando la petición falla: se puede corregir el código y reintentar. | `frontend/src/components/rotacion/dialogo-autorizar.tsx` |
| COR-03 | Con los agentes apagados, la ficha del activo ya no ofrece un alta de agente que fallaría al enviarla: dice que están desactivados y dónde activarlos. | `app/api_web/agentes.py`, `frontend/src/components/agentes/panel-agente-activo.tsx` |
| COR-04 | El instalador ya no pasa el token de instalación por la línea de órdenes del enrolamiento (visible en `ps`): va por una tubería a `passwd-agente enrolar --token -`. Pegado a mano se pide sin eco, y `--backend` y `--pin` se validan antes de escribirse en la configuración. | `agente/instalacion/instalar.sh`, `agente/cmd/passwd-agente` |
| COR-05 | Si el helper rechaza el cambio sin tocar la cuenta, el agente informa ese motivo en vez de deducir «no autentica» y restaurar a ciegas; si el helper no contesta, no concluye nada y reintenta. Lo pendiente se entrega aunque la versión ya no se admita, y un resultado que el backend nunca admitirá deja de bloquear al agente. | `agente/internal/{helper,rotador,ejecutor}` |
| COR-06 | Valores por omisión que escondían estados: el umbral de «sin contacto» pasa de 24 h (igual a la vida de la identidad, así que nunca se veía) a **1 h**, y la ventana del trabajo de 15 min (igual al latido) a **30 min**. Una prueba guarda ambas relaciones. | `app/config.py` |

### Calidad

| ID | Cambio | Dónde |
|---|---|---|
| CAL-01 | **Job Go en la CI**: `gofmt`, `go vet`, `go test -race`, `govulncheck` y compilación para linux/amd64 y arm64, más la **prueba de integración real como root**: cuentas creadas con `useradd`, PAM y `chpasswd` de verdad. | `.github/workflows/ci.yml` |
| CAL-02 | **Prueba de sistema en cada push**: el runner de GitHub arranca con systemd, así que la CI instala el agente con `instalar.sh` y sus unidades endurecidas, y comprueba que una rotación autorizada por dos administradores cambia la contraseña de una **cuenta Linux real**. | `scripts/prueba_agente_sistema.py` |
| CAL-03 | **Pruebas de aceptación** con la trazabilidad de cada criterio a su prueba, `/api/v1` congelada y un volcado entero de la base tras una rotación por agente sin ninguna contraseña en claro. | `tests/test_aceptacion_agentes.py` |
| CAL-04 | Pruebas de navegador de los agentes: alta con reautenticación, token visible una vez, insignia que sigue a un agente real que se enrola, listado y revocación. | `frontend/e2e/agentes.spec.ts` |
| CAL-05 | **Paquetes del agente en cada Release**: `passwd-agente-<versión>-linux-amd64.tar.gz` y `…-arm64.tar.gz`, compilados en un runner nativo de cada arquitectura, con su `SHA256SUMS`. La prueba de sistema instala desde ese mismo paquete. Los flujos de publicación **completan** la Release si se creó desde la interfaz de GitHub (la de `v1.3.0-rc.1` quedó sin notas por eso). | `agente/empaquetar.sh`, `.github/workflows/binarios-agente.yml`, `prelanzamiento.yml`, `publicar.yml` |

## 2. Cambios de comportamiento que conviene conocer

1. **Nada cambia hasta que se activa.** `PASSWD_AGENTES_ENABLED` está apagado: `/api/agent` no
   existe (404), la ficha de cada activo dice que los agentes están desactivados en vez de ofrecer
   el alta, y toda credencial rota a mano, como en la 1.3.0.
2. **Activarlo no cambia ninguna credencial.** Todas siguen «a mano» hasta que un administrador
   elige, credencial por credencial, que rote su agente.
3. **El agente nunca decide.** Solo ejecuta rotaciones que ya autorizaron dos personas; la
   telemetría no dispara nada. Si el agente no puede, la autorización sigue en pie y se puede
   registrar la rotación a mano.
4. **Una rotación «sin confirmar» bloquea la credencial** hasta que alguien, reautenticándose, diga
   qué pasó. Es deliberado: si el agente recogió el trabajo y calló, la contraseña pudo cambiar o
   no, y nadie debe pedir otra rotación sobre esa duda.
5. **Dar de alta un agente y reemitir su token piden contraseña y código**: crean una identidad que
   podrá recibir las contraseñas de ese servidor, y una sesión robada no debe bastar.
6. **Las horas del panel cambian** (COR-01): ahora son las de quien mira. Si comparaba horas del
   panel con las de otro sistema, la diferencia que veía era el defecto.

## 3. Actualización desde la 1.3.0

1. Haga un respaldo cifrado (`python -m app.cli respaldo …`).
2. Despliegue la versión `v1.4.0` (backend y frontend a la vez: comparten contrato).
3. Aplique el esquema: `alembic upgrade head` (revisión `0011`, aditiva). En el despliegue por
   contenedor las tablas se crean solas al arrancar.
4. Compruebe `GET /healthz` → `"version": "1.4.0"`. Hasta aquí, nada cambia para nadie.
5. **Para usar agentes** (en calidad primero, [`ambientes.md`](ambientes.md)): active
   `PASSWD_AGENTES_ENABLED` (por entorno o desde la consola), dé de alta el agente en la ficha del
   servidor e instálelo con la [guía de instalación](guia-instalacion-agente-linux.md). Cuando la
   insignia diga «Conectado», elija «Rotar con el agente» en las credenciales que quiera.
6. Asegúrese de que llega el correo de alertas (`PASSWD_NOTIFY_TO`): por ahí avisan las rotaciones
   fallidas, las sin confirmar y los agentes que dejan de latir.

**Vuelta atrás:** la migración `0011` es reversible (`alembic downgrade 0010`), pero borra los
agentes, sus trabajos y su telemetría, y del libro mayor las columnas que dicen qué agente aplicó
cada rotación (los asientos se conservan). Antes, **revoque los agentes**
y pare su servicio en cada servidor (`systemctl disable --now passwd-agente.service`), y resuelva
las rotaciones sin confirmar: una vuelta atrás con una de ellas abierta deja sin saber qué
contraseña quedó en el servidor.

## 4. Verificación de la versión

Estado del pre-release `v1.4.0-rc.1`; se completa al publicar la versión final.

| Comprobación | Resultado |
|---|---|
| Pruebas del backend (`pytest`) | 472 superadas; cobertura 86,3 % |
| Análisis estático (`ruff`, `bandit`) | sin hallazgos |
| Agente Go: `gofmt`, `go vet`, `go test -race`, `govulncheck` | correctos; 50 pruebas unitarias, sin vulnerabilidades |
| Agente Go: integración real como root (PAM, `chpasswd`, cuentas reales) | correcta en local y en la CI |
| Instalación real con systemd y rotación de una cuenta Linux (CI) | correcta en cada push |
| Frontend: tipos, compilación y pruebas unitarias | correctos (31 pruebas, también en las zonas de Caracas y Tokio) |
| Frontend: linter | sin errores; 18 avisos de un tipo que ya existía |
| Recorrido en navegador (backend + frontend + SMTP simulado) | 34 de 34, también con el navegador en hora de Caracas |
| Versión en caliente (`GET /healthz`) | `1.4.0-rc.1` |

Garantías quitadas a mano para comprobar que sus pruebas fallan: lista de cuentas del helper,
comprobación de la contraseña actual antes de aplicar, UID de quien llama, cuenta inexistente,
journal escrito antes de tocar la cuenta, tope de cuerpo, deduplicación de la alerta, insignia que
ignora la caducidad, despacho de credenciales manuales y contraseña en la bitácora.

## 5. Limitaciones conocidas

- **Solo Linux**, y solo cuentas locales con contraseña en `/etc/shadow` (PAM `pam_unix`). El agente
  Windows y la **programación automática** de rotaciones llegan en la 2.1.0.
- La **verificación es local**: el agente comprueba la contraseña nueva en el propio servidor. La
  verificación remota (entrar desde fuera con ella) es de la 2.2.0, junto con la telemetría
  completa y la cobertura plena.
- Los **dispositivos de red** no admiten agente; sus conectores son de la 2.3.0, con mTLS y firma
  del canal.
- La **alerta de agente sin contacto** sale del mantenimiento periódico: puede llegar hasta un
  intervalo de mantenimiento (6 h) después de que el agente deje de latir. La insignia del panel
  lo refleja al momento.
- El canal agente ↔ backend es **TLS de servidor** (con CA propia o *pin* opcionales); la
  autenticación mutua por certificado es de la 2.3.0.

- La **lista de cuentas** del helper es la frontera: el usuario del agente puede fijar la
  contraseña de cualquier cuenta que figure en ella. El instalador no impide incluir `root`.
- **Reinstalar** un agente con un trabajo ya recogido deja esa rotación «sin confirmar», y el
  anti-thrash local (1 h) no conoce la vía de emergencia.

La lista completa, con su porqué, está en
[`arquitectura-agentes.md`](arquitectura-agentes.md) §12. El resto de limitaciones de la 1.3.0 sigue vigente. Todas están recogidas en la
[hoja de ruta](hoja-de-ruta.md).

## 6. Documentos de esta versión

- [`arquitectura-agentes.md`](arquitectura-agentes.md): cómo encajan backend, agente y helper.
- [`contrato-agente.md`](contrato-agente.md): lo que todo agente debe y no debe hacer (normativo).
- [`referencia-api-agent.md`](referencia-api-agent.md): la API `/api/agent`.
- [`guia-instalacion-agente-linux.md`](guia-instalacion-agente-linux.md): instalar, comprobar,
  reinstalar y retirar un agente.
- [`plan-rotacion-agentes.md`](plan-rotacion-agentes.md): el porqué de cada decisión y el registro
  de ejecución commit a commit (§9.4).
