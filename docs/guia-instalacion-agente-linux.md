# Guía de instalación del agente Linux

**Sistema:** Gestor de Contraseñas de Servidores
**Versión:** 1.4.0
**Audiencia:** administradores (rol **admin**) que instalan el agente de rotación en un servidor
físico, hipervisor o máquina virtual Linux.
**Objetivo:** dejar el agente instalado, enrolado y comprobado, activar la rotación por agente en
una credencial y saber qué hacer cuando algo falla.

> Cómo encajan las piezas y qué protege cada una: [`arquitectura-agentes.md`](arquitectura-agentes.md).
> Lo que el agente puede y no puede hacer: [`contrato-agente.md`](contrato-agente.md). El diseño
> del aislamiento (agente sin privilegios + helper root por socket): plan, §4.2 y hallazgo H15 de
> [`plan-rotacion-agentes.md`](plan-rotacion-agentes.md).

---

## 0. Resumen

1. Compilar `passwd-agente` y `passwd-agente-helper` con su versión y generar `SHA256SUMS` (§2).
2. En la ficha del activo, «Dar de alta un agente» y copiar el token de instalación (§3).
3. Copiar binarios, sumas e instalador al servidor (§4).
4. `sudo ./instalar.sh … --token -` y pegar el token (§5).
5. Comprobar la insignia «Conectado» (§7) y pasar las credenciales a «Rotar con el agente» (§8).

El token de instalación **caduca en una hora**: compile y copie los archivos antes de darlo de alta.

---

## 1. Requisitos

**En el servidor donde se instala:**

- Linux arrancado con **systemd** (el instalador comprueba `/run/systemd/system`).
- Arquitectura **x86_64** o **aarch64** (`uname -m`).
- Acceso root (`sudo`).
- Las **cuentas que se van a rotar ya existen**. El agente nunca crea cuentas: el instalador falla
  si alguna no existe.
- `chpasswd` en `/usr/sbin/chpasswd` y PAM con `pam_unix` (cualquier distribución habitual).
- Salida de red hacia el backend por HTTPS y resolución DNS de su nombre.

**En el backend:**

- Publicado por **HTTPS** (ver [`guia-nginx-tls.md`](guia-nginx-tls.md)). El agente solo acepta
  `http` hacia `127.0.0.1`, `localhost` o `[::1]`, y solo para pruebas.
- La ruta `/api/agent/` tiene que llegar al backend. Con las plantillas de nginx del proyecto
  (`infrastructure/nginx/templates*/`) todo `/api/` va al backend; el servidor de Next.js por sí
  solo **no** reenvía `/api/agent`.
- El interruptor **«Agentes de rotación activos»** (`agentes_enabled`) encendido. Está apagado por
  omisión; con él apagado, `/api/agent` responde 404 y no se puede dar de alta ningún agente.
- **Dos administradores activos**, como para cualquier rotación de la 1.3.0, y su segundo factor
  por **aplicación autenticadora**: el alta del agente y la autorización piden un código TOTP.

Para comprobar que la ruta llega y el interruptor está encendido, desde el servidor:

```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://passwd.ejemplo.org/api/agent/saludo
```

Un `401` es lo esperado (falta la identidad del agente; deja un asiento `agente_acceso_rechazado`
en la bitácora). Un `404` significa que el interruptor está apagado o que esa ruta no llega al
backend.

**Para compilar** (en una máquina de construcción, no hace falta que sea el servidor):

- Go de la versión que fija `agente/go.mod` (1.27).
- Para el helper, que enlaza `libpam` con cgo: compilador de C y las cabeceras de PAM
  (`libpam0g-dev` en Debian/Ubuntu, `pam-devel` en RHEL y derivadas).

---

## 2. Compilar los binarios y sus sumas

Así lo hace la CI (`.github/workflows/ci.yml`, jobs `agente` y `agente-sistema`). Desde la raíz del
repositorio, en la etiqueta de la versión que va a instalar.

Tome la versión del backend, que es la que deben declarar los binarios:

```bash
version=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' app/__init__.py)
```

```bash
echo "$version"
```

Compile el **agente**, estático y sin cgo (cambie `amd64` por `arm64` para aarch64):

```bash
cd agente && mkdir -p dist
```

```bash
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -ldflags "-s -w -X main.version=$version" -o dist/passwd-agente ./cmd/passwd-agente
```

Compile el **helper**, con cgo y `libpam`:

```bash
CGO_ENABLED=1 go build -trimpath -ldflags "-s -w -X main.version=$version" -o dist/passwd-agente-helper ./cmd/passwd-agente-helper
```

> **El helper se compila en la arquitectura de destino y con una glibc igual o anterior a la del
> servidor.** Enlaza dinámicamente `libc` y `libpam`: compilado en una distribución más nueva que la
> del servidor, falla al arrancar por versiones de glibc que no existen allí. La CI solo compila el
> helper para amd64; para aarch64, compílelo en una máquina aarch64 (o con una cadena cruzada y la
> `libpam` de esa arquitectura). El agente, estático, se compila para cualquiera de las dos desde
> donde sea.

Compruebe que los dos declaran la versión (en otra arquitectura, el agente no se podrá ejecutar
aquí: compruébelo en el destino):

```bash
./dist/passwd-agente version
```

```bash
./dist/passwd-agente-helper --version
```

Sin `-ldflags "-X main.version=…"` declaran `dev`: el panel no podrá compararla con la versión
mínima y, si hay una fijada, ese agente no recibirá trabajos.

Genere las sumas. El instalador busca exactamente los nombres `passwd-agente` y
`passwd-agente-helper`:

```bash
(cd dist && sha256sum passwd-agente passwd-agente-helper > SHA256SUMS)
```

Publique `SHA256SUMS` por un canal distinto del de los binarios (las notas de la versión, el
gestor de cambios): si viajan juntos, la comprobación del instalador detecta un archivo dañado,
pero no uno sustituido junto con su suma. La firma de los binarios llega en la 2.3.0.

---

## 3. Dar de alta el agente en el panel

Requiere el permiso `agentes.gestionar` (solo administradores).

1. Abra la **ficha** del servidor físico, hipervisor o máquina virtual. Verá la tarjeta
   **«Agente de rotación»** con la insignia «Sin agente». Los dispositivos de red no admiten
   agente. Si en lugar del botón de alta lee «Los agentes de rotación están desactivados en esta
   instalación», encienda antes el interruptor en **Configuración**, grupo «Agentes de rotación».
2. Revise el **«Nombre del agente»**. Por omisión es `agente-<nombre del activo>`. Debe ser único
   en todo el sistema, **incluidos los agentes revocados**.
3. Pulse **«Dar de alta un agente»**. En el diálogo, escriba **«Su contraseña»** y el **«Código de
   su aplicación autenticadora»** (el código por correo no sirve) y pulse **«Dar de alta»**.
4. Aparece el **token de instalación**:
   - se muestra **una sola vez** (el servidor solo guarda su huella) y no se puede recuperar;
   - sirve para **un único** enrolamiento y **caduca en una hora**;
   - el botón de copiar lo lleva al portapapeles;
   - debajo aparece una orden de instalación sugerida con la URL del panel y las cuentas de las
     credenciales del activo. Revísela: la URL debe ser la del backend (§1) y las cuentas, las que
     de verdad quiere que el agente pueda rotar.
5. Pulse **«Ya lo he guardado»** cuando lo tenga a salvo.

La insignia pasa a **«Pendiente de instalar»**. Si el token caduca antes de usarlo, el panel lo
indica («El token de instalación caducó sin que el agente llegara a instalarse») y hay que emitir
otro con **«Reinstalar»** (§9.1).

---

## 4. Copiar los archivos al servidor

El instalador busca las unidades de systemd y el archivo PAM **en su propio directorio**, y los
binarios en el que indique `--binarios`. Lo más sencillo es un directorio con todo junto, que
puede preparar desde la raíz del repositorio:

| Archivo | Origen |
|---|---|
| `instalar.sh`, `passwd-agente.service`, `passwd-agente-helper.socket`, `passwd-agente-helper@.service`, `passwd-agente-helper.pam` | `agente/instalacion/` |
| `passwd-agente`, `passwd-agente-helper`, `SHA256SUMS` | `agente/dist/` (§2) |

```bash
mkdir -p paquete && cp agente/instalacion/* agente/dist/* paquete/
```

```bash
scp -r paquete usuario@servidor:/tmp/passwd-agente
```

---

## 5. Ejecutar `instalar.sh`

### 5.1 Opciones

| Opción | Obligatoria | Qué hace |
|---|---|---|
| `--backend URL` | Sí | URL base del backend, p. ej. `https://passwd.ejemplo.org`. Solo `https`, sin usuario ni contraseña en la URL; `http` solo hacia loopback (avisa: «solo para pruebas»). |
| `--cuentas c1,c2` | Sí | La **lista exacta** de cuentas que el agente podrá rotar, separadas por comas. Cada una debe cumplir `^[a-z_][a-z0-9_.-]{0,31}$` y existir. |
| `--binarios DIR` | No | Directorio con `passwd-agente` y `passwd-agente-helper`. Por omisión, el del instalador. |
| `--sumas ARCHIVO` | Sí | Archivo `SHA256SUMS`. Acepta líneas `<suma>  <nombre>` y `<suma> *<nombre>`. |
| `--token -` | Sí (o la variable) | Lee el token de instalación de la **entrada estándar**: si es una terminal, lo pide con un aviso y **sin eco**. También se admite `--token <token>` o la variable `PASSWD_AGENTE_TOKEN`, pero en la línea de órdenes lo ve cualquiera con `ps` y queda en el historial. Sea cual sea la forma, el instalador se lo pasa al agente **por una tubería** (`passwd-agente enrolar --token -`), nunca en la línea de órdenes del enrolamiento. |
| `--ca-file ARCHIVO` | No | CA adicional en PEM (p. ej. el `ca.crt` de `infrastructure/nginx/generar-ca-interna.sh`). Se copia a `/etc/passwd-agente/ca.pem` y se añade a las del sistema. |
| `--pin BASE64` | No | SHA-256 en base64 de la clave pública (SPKI) del certificado del servidor. Si se indica, cualquier otro certificado se rechaza aunque una CA lo avale (se comprueba **además** de la cadena). |
| `--simular` | No | Muestra cada paso sin ejecutarlo. |
| `-h`, `--help` | No | Muestra la ayuda. |

### 5.2 Qué comprueba antes de tocar nada

En este orden, y si algo falla sale con un mensaje `instalar.sh: …` sin haber instalado nada:

1. Que se ejecuta como root y que el sistema arranca con systemd (las dos se omiten con
   `--simular`).
2. Que es Linux y la arquitectura es `x86_64` o `aarch64`.
3. Que `--backend` está, usa `https` (o `http` hacia loopback) y no contiene comillas, barras
   invertidas ni espacios (va dentro de un JSON).
4. Que `--cuentas` está, y cada cuenta tiene un nombre admitido y **existe** (`getent passwd`).
5. Que están los dos binarios, que `--sumas` está y existe, que tiene una línea para cada binario y
   que el SHA-256 de cada uno coincide. Si todo cuadra, escribe «sumas SHA-256 correctas».
6. Que el archivo de `--ca-file`, si se indicó, existe, y que `--pin`, si se indicó, es un SHA-256
   en base64 (44 caracteres).
7. Que hay token (lo lee aquí si se indicó `--token -`).
8. Que el nombre del backend resuelve (`getent ahosts`); muestra las direcciones.

Lo que **no** se puede comprobar sin instalar —que el token sea válido, que el backend responda,
que el certificado o el pin cuadren— se descubre en el paso de enrolamiento (§5.4).

### 5.3 Instalación

En el servidor:

```bash
cd /tmp/passwd-agente
```

```bash
sudo ./instalar.sh --backend https://passwd.ejemplo.org --cuentas deploy,svc-backup --binarios . --sumas ./SHA256SUMS --token -
```

Tras «sumas SHA-256 correctas» el instalador pide «Token de instalación (no se mostrará)»: pegue
el token y pulse Intro. No se ve en la pantalla mientras lo pega.

Si prefiere no pegarlo, guárdelo en un archivo solo legible por usted y redirija la entrada (así lo
hace la CI), y bórrelo después:

```bash
sudo ./instalar.sh --backend https://passwd.ejemplo.org --cuentas deploy --binarios . --sumas ./SHA256SUMS --token - < token.txt
```

Con una CA interna, añada `--ca-file /ruta/ca.crt`. Para obtener el pin del certificado que sirve
el backend:

```bash
openssl s_client -connect passwd.ejemplo.org:443 -servername passwd.ejemplo.org </dev/null 2>/dev/null | openssl x509 -pubkey -noout | openssl pkey -pubin -outform der | openssl dgst -sha256 -binary | base64
```

> **Cuidado con el pin y la renovación de certificados.** El pin es de la clave pública del
> certificado del servidor, no del certificado: sobrevive a una renovación **solo si se conserva la
> clave**. Let's Encrypt genera una clave nueva en cada renovación salvo que se le pida lo
> contrario. Si fija un pin, planifique su cambio junto con la rotación de certificados
> ([`guia-nginx-tls.md`](guia-nginx-tls.md)): con un pin que ya no coincide, el agente deja de
> conectar.

Para ver qué haría sin hacerlo (cualquier token no vacío sirve: no se envía):

```bash
./instalar.sh --simular --backend https://passwd.ejemplo.org --cuentas deploy --binarios . --sumas ./SHA256SUMS --token prueba
```

`--simular` hace todas las comprobaciones salvo root y systemd, y muestra cada orden con `+`.

### 5.4 Qué hace, paso a paso

1. **Usuario sin privilegios** `passwd-agente`, si no existe (`useradd --system --user-group`, sin
   crear home, home `/var/lib/passwd-agente`, shell `/usr/sbin/nologin`).
2. **Binarios**: el agente en `/usr/local/bin`, el helper en `/usr/local/sbin`.
3. **Configuración**: directorios, `config.json`, `helper.json` (la lista de cuentas) y el servicio
   PAM.
4. **Unidades systemd** y el drop-in de red con las direcciones del backend y de los servidores DNS
   de `/etc/resolv.conf`; `daemon-reload` y `enable --now passwd-agente-helper.socket`.
5. **Enrolamiento**: `runuser -u passwd-agente -- passwd-agente enrolar … --forzar`. El agente
   genera su par de claves X25519, canjea el token y guarda su identidad. Muestra «Agente «…»
   enrolado. Identidad guardada en /var/lib/passwd-agente/identidad.json.». Durante los segundos
   que dura, el token aparece en la lista de procesos; es de un solo uso y queda anulado al
   canjearse.
6. **Arranque**: `enable --now passwd-agente.service`, espera 3 s y comprueba que el servicio y el
   socket quedaron activos. Termina con «Agente instalado. Estado: systemctl status
   passwd-agente.service».

Si el enrolamiento falla, el instalador se detiene con los archivos ya copiados pero sin el
servicio del agente arrancado. Corrija la causa (§10.2) y vuelva a ejecutarlo: es idempotente, y
con `--forzar` sustituye cualquier identidad anterior. Si el token llegó a canjearse o caducó,
emita otro con «Reinstalar».

---

## 6. Qué deja instalado

| Elemento | Ruta | Dueño y permisos |
|---|---|---|
| Usuario y grupo del agente | `passwd-agente` (de sistema, sin shell) | — |
| Agente | `/usr/local/bin/passwd-agente` | `root:root` 0755 |
| Helper | `/usr/local/sbin/passwd-agente-helper` | `root:root` 0700 |
| Directorio de configuración | `/etc/passwd-agente/` | `root:passwd-agente` 0750 |
| Configuración del agente | `/etc/passwd-agente/config.json` | `root:passwd-agente` 0640: el agente la lee, no la cambia |
| CA adicional (con `--ca-file`) | `/etc/passwd-agente/ca.pem` | `root:passwd-agente` 0640 |
| Lista de cuentas | `/etc/passwd-agente/helper.json` | `root:root` 0644. El helper se niega a atender peticiones si no es de root o si el grupo u otros pueden escribirla |
| Servicio PAM | `/etc/pam.d/passwd-agente-helper` | `root:root` 0644 |
| Estado del agente | `/var/lib/passwd-agente/` | `passwd-agente` 0700 |
| Identidad | `/var/lib/passwd-agente/identidad.json` | 0600 (token de vida corta y clave privada X25519) |
| Journal | `/var/lib/passwd-agente/journal.bin` | 0600, cifrado; se crea con el primer trabajo y guarda el trabajo en curso y la fecha de la última rotación de cada cuenta |
| Unidades | `/etc/systemd/system/passwd-agente.service`, `passwd-agente-helper.socket`, `passwd-agente-helper@.service` | `root:root` 0644 |
| Drop-in de red | `/etc/systemd/system/passwd-agente.service.d/red.conf` | `root:root` 0644 |
| Socket del helper | `/run/passwd-agente/helper.sock` (lo crea systemd) | `root:passwd-agente` 0660; directorio 0755 |

**`config.json`** (sin `--ca-file` ni `--pin`, esos campos quedan vacíos):

```json
{
  "backend": "https://passwd.ejemplo.org",
  "ca_file": "",
  "pin_sha256": "",
  "identidad": "/var/lib/passwd-agente/identidad.json",
  "journal": "/var/lib/passwd-agente/journal.bin",
  "helper": "/run/passwd-agente/helper.sock"
}
```

Admite además `anti_thrash_min` (intervalo mínimo local entre dos rotaciones de la misma cuenta,
60 min por omisión). Un campo desconocido impide arrancar: una errata no pasa en silencio.

**`helper.json`**:

```json
{
  "usuario_agente": "passwd-agente",
  "cuentas": ["deploy", "svc-backup"]
}
```

**Servicio PAM**: solo `pam_unix` con `nodelay`, a propósito sin `common-auth`: comprobar una
contraseña no cuenta como fallo para el bloqueo de la cuenta (`faillock`) ni pide otros factores.

**Endurecimiento de las unidades:**

| Unidad | Lo esencial |
|---|---|
| `passwd-agente.service` | `User=passwd-agente`; `NoNewPrivileges`, `CapabilityBoundingSet=` vacío, `RestrictSUIDSGID`; `ProtectSystem=strict` (solo escribe en su `StateDirectory`), `ProtectHome`, `PrivateTmp`, `PrivateDevices`, `ProtectProc=invisible` y el resto de `Protect*`; `RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX`, `IPAddressDeny=any`; `MemoryDenyWriteExecute`, `SystemCallFilter=@system-service ~@privileged`; `Restart=on-failure` cada 30 s. |
| `passwd-agente-helper.socket` | `ListenStream=/run/passwd-agente/helper.sock`, `SocketGroup=passwd-agente`, `SocketMode=0660`, `Accept=yes`, `MaxConnections=4`. |
| `passwd-agente-helper@.service` | Root, una instancia por conexión, `RuntimeMaxSec=60`; **sin red** (`PrivateNetwork`, `IPAddressDeny=any`); capacidades justas para `chpasswd` y PAM (`CAP_CHOWN CAP_FOWNER CAP_DAC_OVERRIDE CAP_DAC_READ_SEARCH CAP_AUDIT_WRITE`); `ProtectSystem=strict` con `ReadWritePaths=/etc`; `NoNewPrivileges`, `RestrictSUIDSGID`, `MemoryDenyWriteExecute`, `SystemCallFilter=@system-service`. |
| Drop-in `red.conf` | `IPAddressAllow=localhost <IPs del backend> <IPs DNS>`: lo único hacia donde puede salir el agente. Las direcciones se resuelven **al instalar**. |

---

## 7. Comprobar que funciona

```bash
systemctl status passwd-agente.service
```

```bash
systemctl status passwd-agente-helper.socket
```

```bash
journalctl -u passwd-agente.service -n 50
```

Al arrancar, el agente registra una línea como
`level=INFO msg="agente en marcha" agente=agente-web01 version=1.4.0 rotacion=true`. Con
`rotacion=true` pedirá trabajos; con `false` (sin `helper` en la configuración) solo late. Las
instancias del helper se ven con:

```bash
journalctl -u 'passwd-agente-helper@*' -n 50
```

Para ver la puntuación de exposición de systemd (la CI la muestra en cada ejecución):

```bash
systemd-analyze security passwd-agente.service
```

**En el panel**, en la ficha del activo, la insignia de la tarjeta «Agente de rotación» pasa a
**«Conectado»** y aparecen el host, la versión, el «Último latido» y la «Identidad válida hasta».
En **Agentes** (`/agentes`) se ve el parque entero, y en **Métricas** la tarjeta «Agentes de
rotación». El agente late al arrancar y después cada `agentes_telemetria_intervalo_min` (15 min por
omisión).

---

## 8. Activar la rotación por agente en una credencial

Instalar el agente no cambia ninguna credencial: cada una sigue en la vía **manual** hasta que se
decida.

1. Abra la credencial. En el bloque **«Rotación de la contraseña»**, junto a «Vía de rotación:
   Manual», pulse **«Rotar con el agente»** (requiere `agentes.gestionar`, que no haya una
   solicitud abierta y que el agente del activo esté enrolado).
2. La cuenta de la credencial (`usuario_acceso`) **debe estar en la lista** `--cuentas` del
   instalador. Si no lo está, el helper la rechazará al rotar.
3. Para rotar, pulse **«Rotar ahora»** con su motivo y tipo. El agente la aplicará en cuanto **otro
   administrador** la autorice («Autorizar», con su contraseña y código TOTP). Hasta entonces no se
   toca nada.
4. Mientras tanto, la credencial muestra «En manos del agente … · debe recogerla antes de las …» y,
   una vez recogida, «recogida, esperando su resultado». Con los valores por omisión, el agente la
   recoge en su siguiente latido (como mucho 15 min).
5. Al cerrarse, la línea de tiempo muestra «Ejecutada por el agente …» y la nota de **verificación
   local**: la contraseña nueva autentica la cuenta en el sistema operativo, pero no se ha
   comprobado contra el servicio declarado (SSH, RDP…).

Si la rotación se autorizó pero no se despachó (agente sin contacto, trabajo vencido sin recoger,
anti-thrash), la credencial lo dice y ofrece **«Enviar al agente»**, o cambiarla a mano y
registrarla. Para volver a la vía manual, **«Rotar a mano»**.

Una credencial rotada hace menos de 24 h (por cualquier vía) no se despacha a un agente salvo con
una solicitud de tipo **emergencia**, que queda registrada. El agente, además, no rota la misma
cuenta dos veces en menos de una hora, ni siquiera en emergencia.

---

## 9. Operaciones

### 9.1 Reinstalar (identidad caducada, servidor reinstalado, token de instalación caducado)

1. Compruebe en **Agentes** que el agente no tiene un **trabajo en curso**. Reinstalar anula la
   identidad al momento y el enrolamiento borra el journal: un trabajo entregado se quedaría sin
   resultado y acabaría «sin confirmar».
2. En la ficha del activo, **«Reinstalar»** → diálogo «Emitir un token de instalación nuevo» → su
   contraseña y código → **«Emitir token»**. La insignia vuelve a «Pendiente de instalar».
3. En el servidor, vuelva a ejecutar `instalar.sh` con el token nuevo. Es idempotente: sustituye
   binarios, configuración y unidades, y enrola con `--forzar`.

### 9.2 Cambiar la lista de cuentas

Edite `/etc/passwd-agente/helper.json` como root, manteniéndolo de root y sin escritura para el
grupo ni otros. El helper lo lee en cada petición: no hace falta reiniciar nada. Cada cuenta nueva
debe existir.

### 9.3 Cambió la dirección del backend

Las direcciones de `IPAddressAllow` se fijaron al instalar. Edite
`/etc/systemd/system/passwd-agente.service.d/red.conf` con las nuevas y reinicie:

```bash
sudo systemctl daemon-reload
```

```bash
sudo systemctl restart passwd-agente.service
```

### 9.4 Revocar

En la ficha del activo, **«Revocar»** y confirme (el botón del diálogo dice «Eliminar»). Efecto
inmediato:

- el agente pierde su identidad y no recibirá más trabajos;
- el activo vuelve a «Sin agente» y sus credenciales con vía agente vuelven a **manual**;
- un trabajo pendiente se cancela (la rotación vuelve a quedar autorizada); uno entregado queda
  **«sin confirmar»** y hay que resolverlo (§10.6);
- el agente se conserva como historia: un revocado no se puede reactivar. Para volver a usar un
  agente en ese activo, dé de alta otro **con otro nombre**.

El servicio sigue corriendo en el servidor, recibiendo 401, hasta que lo desinstale.

### 9.5 Desinstalar a mano

No hay desinstalador. Revoque primero el agente en el panel y después, en el servidor:

```bash
sudo systemctl disable --now passwd-agente.service passwd-agente-helper.socket
```

```bash
sudo rm -f /etc/systemd/system/passwd-agente.service /etc/systemd/system/passwd-agente-helper.socket /etc/systemd/system/passwd-agente-helper@.service
```

```bash
sudo rm -rf /etc/systemd/system/passwd-agente.service.d
```

```bash
sudo systemctl daemon-reload
```

```bash
sudo rm -f /usr/local/bin/passwd-agente /usr/local/sbin/passwd-agente-helper /etc/pam.d/passwd-agente-helper
```

```bash
sudo rm -rf /etc/passwd-agente /var/lib/passwd-agente
```

```bash
sudo userdel passwd-agente
```

Si el grupo `passwd-agente` sobrevive a `userdel`, bórrelo con `groupdel`.

### 9.6 Después de restaurar un respaldo

Un respaldo repone los agentes **revocados**, sin identidad, y las credenciales vuelven a la vía
manual. Dé de alta de nuevo cada agente (con otro nombre) y reinstálelo (§9.1, paso 3).

---

## 10. Solución de problemas

### 10.1 Insignias

| Insignia | Qué significa | Qué hacer |
|---|---|---|
| «Pendiente de instalar» | Dado de alta, nunca enrolado. Con «Token de instalación caducado: reinstálelo», el token pasó de su hora. | Instalar con el token; si caducó, «Reinstalar» y volver a instalar. |
| «Sin contacto» | Enrolado, pero sin latido desde hace más que el umbral (24 h por omisión). | Ver §10.3. |
| «Identidad caducada» | La identidad (24 h por omisión) venció sin renovarse: el agente estuvo parado o sin red. Con los valores por omisión es lo que se ve directamente tras un silencio, sin pasar por «Sin contacto». | Corregir la causa (§10.3), «Reinstalar» y volver a instalar: una identidad caducada no se recupera. |
| «Sin agente» | No hay agente vigente (o se revocó). | Dar de alta uno. |

El correo «[passwd] Agente … sin contacto» lo envía el mantenimiento periódico, con hasta 6 h de
retraso.

### 10.2 El instalador falla

| Mensaje | Causa y solución |
|---|---|
| `hay que ejecutarlo como root` | Use `sudo`. |
| `este sistema no arranca con systemd` | No soportado. |
| `arquitectura no soportada` | Solo `x86_64` y `aarch64`. |
| `el backend debe usar https (http solo hacia loopback, para pruebas)` | Corrija `--backend`. |
| `nombre de cuenta no admitido` | La cuenta no cumple `^[a-z_][a-z0-9_.-]{0,31}$`. |
| `la cuenta «x» no existe: el agente nunca crea cuentas` | Créela antes, o quítela de `--cuentas`. |
| `no está DIR/passwd-agente` | `--binarios` no apunta al directorio de los binarios, o tienen otro nombre (los de la CI se llaman `passwd-agente-linux-amd64`: renómbrelos y regenere las sumas). |
| `… no tiene la suma de …` / `el SHA-256 de … no coincide con el publicado` | El binario no es el publicado: copia incompleta, binario de otra compilación o manipulado. Vuelva a copiarlo o a compilarlo. **No edite `SHA256SUMS` para que cuadre.** |
| `falta el token de instalación` | Use `--token -` y pegue el token. |
| `no se pudo resolver …` | El servidor no resuelve el nombre del backend. |
| `passwd-agente: el backend rechazó el enrolamiento: el backend respondió 401: El token de enrolamiento caducó: emita otro desde el panel.` | Pasó más de una hora. «Reinstalar» y repetir. |
| `… respondió 401: Token de enrolamiento no válido o ya usado.` | Token mal copiado, o ya canjeado. Emita otro. |
| `… respondió 404: …` | Interruptor de agentes apagado, o `/api/agent` no llega al backend (§1). |
| `… respondió 429: …` | Más de 10 intentos de enrolamiento desde esa IP en 15 min. Espere. |
| Error de certificado (`x509: …`) | El servidor no confía en el certificado del backend: `--ca-file` con la CA interna. |
| `la clave pública del servidor no coincide con el pin configurado` | El pin está mal o el certificado cambió de clave. |
| `--pin debe ser el SHA-256 en base64 de la clave pública del servidor (44 caracteres)` | El valor de `--pin` no tiene el formato. Calcúlelo como se indica en §5.3. El instalador lo comprueba antes de tocar nada. |
| `el servicio no quedó activo: journalctl -u passwd-agente.service` | Mire el registro (§10.3). |

### 10.3 El agente no late («Sin contacto», «Identidad caducada»)

```bash
systemctl status passwd-agente.service
```

```bash
journalctl -u passwd-agente.service --since "1 hour ago"
```

| En el registro | Causa |
|---|---|
| `el backend no reconoce la identidad del agente: si caducó o se revocó, vuelva a enrolarlo desde el panel` | Identidad caducada, revocada o anulada por «Reinstalar». Reinstale (§9.1). |
| Errores de conexión o de tiempo de espera | Sin red hacia el backend. Si la dirección del backend cambió, actualice `red.conf` (§9.3). Compruebe el cortafuegos. |
| `respondió 404` en cada ciclo | Interruptor de agentes apagado en el backend. |
| `versión del agente por debajo de la mínima: no recibirá trabajos` | Late, pero no recibe trabajos. Actualice los binarios y reinstale. |
| `identidad: … (¿falta enrolar el agente?)` o `tiene permisos …: deben ser 0600` | Identidad ausente o con permisos abiertos. Reinstale. |

El agente reintenta cada minuto tras un error de red, y cada 15 min tras un 401.

### 10.4 La rotación vuelve a «autorizada» sin que el agente la recoja

El trabajo tiene una ventana (`rotacion_ventana_job_min`, 30 min) y el agente pregunta en cada
latido (`agentes_telemetria_intervalo_min`, 15 min). Si el agente estaba parado o sin red, el
trabajo expira, la rotación vuelve a quedar autorizada y la credencial ofrece **«Enviar al
agente»**. Si cambia alguno de los dos ajustes, mantenga la ventana claramente mayor que el
intervalo de latido.

### 10.5 Una rotación termina «fallada» o «revertida»

El correo «[passwd] Rotación fallado|revertido en …» y la línea de tiempo de la credencial dan el
detalle que informó el agente. La contraseña del inventario **no ha cambiado**.

- **«…se rotó hace muy poco: intervalo mínimo local del agente»**: el anti-thrash local (60 min).
  Solicite de nuevo más tarde.
- **«el trabajo llegó vencido…»**: el agente lo recogió fuera de su ventana. Si se repite,
  compruebe que el **reloj del servidor** está sincronizado (NTP): la ventana se compara con él.
- **«no se cambió nada: …»**: el helper rechazó el cambio antes de tocar la cuenta, que sigue
  como estaba. El resto del mensaje dice por qué:
  - `la cuenta no está en la lista de cuentas que este helper puede rotar` → añádala a
    `helper.json` (§9.2);
  - `la contraseña actual del inventario no autentica la cuenta: no se cambia nada` → alguien
    cambió la contraseña de la cuenta fuera del sistema. Averigüe cuál vale, póngala al día en el
    inventario con una rotación manual y vuelva a rotar por agente;
  - `la cuenta no existe en este sistema` → la cuenta se borró o se renombró.
- **«la contraseña nueva no se aplicó; la cuenta conserva la anterior»**: el cambio no llegó a
  aplicarse y la cuenta sigue con la contraseña del inventario.
- **«la contraseña nueva no verificó y se restauró la anterior»** (`revertido`): el cambio se
  aplicó a medias o no verificó, y el agente volvió a fijar la contraseña del inventario, que
  vuelve a valer.
- **«ni la contraseña nueva ni la anterior autentican la cuenta: requiere intervención manual»**:
  la cuenta quedó con una contraseña que el sistema no conoce. Restablézcala a mano en el servidor
  y regístrela con una rotación manual.

Si el helper **no contesta** (socket inactivo, falta `/etc/pam.d/passwd-agente-helper`,
`helper.json` con dueño o permisos incorrectos), el agente no informa nada: registra «no se puede
saber qué contraseña quedó; se reintentará» con la causa y lo reintenta cada minuto. Corrija la
causa y la rotación se cerrará sola; si tarda más que la ventana y su margen, pasará a «sin
confirmar» (§10.6). Para ver la causa:

```bash
journalctl -u passwd-agente.service -u 'passwd-agente-helper@*' --since "1 hour ago"
```

### 10.6 Rotación «sin confirmar»

El agente recogió la rotación y no informó (se cayó, perdió la red o se revocó). La credencial
muestra **«Sin confirmar»**, la página **Rotación** la lista en «Rotaciones sin confirmar» y llega
el correo «[passwd] Rotación sin confirmar en …». Mientras tanto, la credencial no admite otra
rotación.

1. Si el agente vuelve a estar en marcha, espere a su siguiente latido: entregará el resultado de su
   journal y la rotación se cerrará sola.
2. Si no, compruebe en el servidor qué contraseña tiene la cuenta. La forma más fiable es preguntar
   al propio helper con la contraseña **del inventario** (revélela en la credencial). Con `jq`:

   ```bash
   read -rs PW
   ```

   ```bash
   jq -Rc '{accion: "verificar", cuenta: "deploy", password: .}' <<<"$PW" | sudo /usr/local/sbin/passwd-agente-helper --config /etc/passwd-agente/helper.json
   ```

   ```bash
   unset PW
   ```

   La respuesta es `{"ok":true}` si esa contraseña autentica la cuenta y `{"ok":false}` si no. Usa
   el mismo PAM sin `faillock` que el agente: no cuenta como intento fallido. La contraseña no pasa
   por la línea de órdenes.
3. En la credencial, con el permiso `rotacion.autorizar`:
   - si la del inventario **ya no** vale, la que quedó es la nueva: **«Sí, quedó la nueva»**;
   - si la del inventario **sigue** valiendo: **«No, sigue la anterior»**.

   Las dos piden su contraseña y el código de su aplicación autenticadora. La rotación se cierra
   (verificación «ninguna»: lo comprobó una persona) y el trabajo purga sus secretos.

El sistema no puede mostrarle la contraseña nueva, así que la comprobación se hace con la del
inventario. Si sospecha que la cuenta quedó con una contraseña que nadie conoce, restablézcala a
mano en el servidor, resuelva como «No, sigue la anterior» y abra después una rotación manual
(solicitud, autorización y registro) con la contraseña que haya fijado.
