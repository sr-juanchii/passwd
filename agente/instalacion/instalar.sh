#!/usr/bin/env bash
# Instalador del agente de rotación de passwd para Linux (v1.4.0).
#
#   sudo ./instalar.sh --backend https://passwd.ejemplo.org \
#                      --cuentas deploy,svc-backup \
#                      --binarios ./dist --sumas ./dist/SHA256SUMS \
#                      --token -            # el token de instalación, por la entrada estándar
#
# Falla, sin dejar nada a medias que no avise, si algo no se cumple: root,
# systemd, arquitectura, SHA-256 de los binarios contra el archivo publicado,
# backend https (http solo hacia loopback, para pruebas) y cuentas existentes.
# Con --simular muestra cada paso sin ejecutarlo.
#
# El token de instalación es de un solo uso y caduca en una hora. Mejor por la
# entrada estándar (--token -) o en PASSWD_AGENTE_TOKEN que en la línea de
# órdenes, donde lo ve cualquiera con `ps`.
#
# Diseño y garantías: docs/plan-rotacion-agentes.md §4.2 (hallazgo H15).
set -euo pipefail
umask 077

readonly USUARIO=passwd-agente
readonly DIR_CONFIG=/etc/passwd-agente
readonly DIR_ESTADO=/var/lib/passwd-agente
readonly BIN_AGENTE=/usr/local/bin/passwd-agente
readonly BIN_HELPER=/usr/local/sbin/passwd-agente-helper
readonly DIR_UNIDADES=/etc/systemd/system
readonly SOCKET=/run/passwd-agente/helper.sock
DIR_FUENTE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly DIR_FUENTE

BACKEND=""
CUENTAS=""
BINARIOS="$DIR_FUENTE"
SUMAS=""
TOKEN="${PASSWD_AGENTE_TOKEN:-}"
CA_FILE=""
PIN=""
SIMULAR=0

fallo() {
	echo "instalar.sh: $*" >&2
	exit 1
}

paso() { echo "==> $*"; }

# Ejecuta una orden, o la muestra si se simula.
hacer() {
	if [[ $SIMULAR -eq 1 ]]; then
		printf '    + %s\n' "$*"
	else
		"$@"
	fi
}

# Escribe un archivo con dueño y permisos, o lo muestra si se simula.
escribir() {
	local ruta=$1 dueno=$2 modo=$3 contenido=$4
	if [[ $SIMULAR -eq 1 ]]; then
		printf '    + escribir %s (%s, %s)\n' "$ruta" "$dueno" "$modo"
		return
	fi
	local tmp
	tmp=$(mktemp "$(dirname "$ruta")/.instalar.XXXXXX")
	printf '%s' "$contenido" >"$tmp"
	chown "$dueno" "$tmp"
	chmod "$modo" "$tmp"
	mv -f "$tmp" "$ruta"
}

uso() {
	sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
	exit 2
}

while [[ $# -gt 0 ]]; do
	case $1 in
	--backend) BACKEND=${2:-}; shift 2 ;;
	--cuentas) CUENTAS=${2:-}; shift 2 ;;
	--binarios) BINARIOS=${2:-}; shift 2 ;;
	--sumas) SUMAS=${2:-}; shift 2 ;;
	--token) TOKEN=${2:-}; shift 2 ;;
	--ca-file) CA_FILE=${2:-}; shift 2 ;;
	--pin) PIN=${2:-}; shift 2 ;;
	--simular) SIMULAR=1; shift ;;
	-h | --help) uso ;;
	*) fallo "opción desconocida: $1 (use --help)" ;;
	esac
done

# ---------------------------------------------------------------------------
# Comprobaciones: nada se toca hasta que todas pasan.
# ---------------------------------------------------------------------------
paso "Comprobaciones previas"

[[ $SIMULAR -eq 1 || $EUID -eq 0 ]] || fallo "hay que ejecutarlo como root"
[[ -d /run/systemd/system ]] || [[ $SIMULAR -eq 1 ]] || fallo "este sistema no arranca con systemd"
[[ $(uname -s) == Linux ]] || fallo "solo Linux"
case $(uname -m) in
x86_64 | aarch64) ;;
*) fallo "arquitectura no soportada: $(uname -m)" ;;
esac

[[ -n $BACKEND ]] || fallo "falta --backend"
if [[ $BACKEND =~ ^https://[^/@]+ ]]; then
	:
elif [[ $BACKEND =~ ^http://(127\.0\.0\.1|localhost|\[::1\])(:[0-9]+)?(/.*)?$ ]]; then
	echo "    aviso: backend por http hacia loopback: solo para pruebas"
else
	fallo "el backend debe usar https (http solo hacia loopback, para pruebas)"
fi
# Va dentro de un JSON: nada de comillas, barras invertidas ni espacios.
[[ $BACKEND =~ [\"\\[:space:]] ]] && fallo "el backend contiene caracteres no admitidos"

[[ -n $CUENTAS ]] || fallo "falta --cuentas: la lista exacta de cuentas que el agente podrá rotar"
IFS=',' read -r -a LISTA_CUENTAS <<<"$CUENTAS"
for cuenta in "${LISTA_CUENTAS[@]}"; do
	[[ $cuenta =~ ^[a-z_][a-z0-9_.-]{0,31}$ ]] || fallo "nombre de cuenta no admitido: «$cuenta»"
	getent passwd "$cuenta" >/dev/null || fallo "la cuenta «$cuenta» no existe: el agente nunca crea cuentas"
done

for binario in passwd-agente passwd-agente-helper; do
	[[ -f $BINARIOS/$binario ]] || fallo "no está $BINARIOS/$binario"
done
[[ -n $SUMAS ]] || fallo "falta --sumas: los binarios se comprueban contra el SHA-256 publicado"
[[ -f $SUMAS ]] || fallo "no existe el archivo de sumas $SUMAS"
for binario in passwd-agente passwd-agente-helper; do
	esperada=$(awk -v f="$binario" '$2 == f || $2 == "*"f {print $1}' "$SUMAS")
	[[ -n $esperada ]] || fallo "$SUMAS no tiene la suma de $binario"
	real=$(sha256sum "$BINARIOS/$binario" | awk '{print $1}')
	[[ $esperada == "$real" ]] || fallo "el SHA-256 de $binario no coincide con el publicado"
done
echo "    sumas SHA-256 correctas"

if [[ -n $CA_FILE ]]; then [[ -f $CA_FILE ]] || fallo "no existe --ca-file $CA_FILE"; fi
# El pin es el SHA-256 en base64 de la clave pública del servidor: 44 caracteres.
if [[ -n $PIN ]]; then
	[[ $PIN =~ ^[A-Za-z0-9+/]{43}=$ ]] || fallo "--pin debe ser el SHA-256 en base64 de la clave pública del servidor (44 caracteres)"
fi

if [[ $TOKEN == "-" ]]; then
	if [[ -t 0 ]]; then
		# Pegado a mano: sin eco, para que no quede en la pantalla.
		IFS= read -r -s -p "Token de instalación (no se mostrará): " TOKEN || true
		echo
	else
		IFS= read -r TOKEN || true
	fi
fi
[[ -n $TOKEN ]] || fallo "falta el token de instalación (--token - o PASSWD_AGENTE_TOKEN)"

# Direcciones a las que el agente podrá salir: el backend y los servidores DNS
# (sin DNS no resolvería el nombre del backend). Todo lo demás, denegado.
HOST_BACKEND=$(sed -E 's#^https?://(\[[^]]+\]|[^/:]+).*#\1#' <<<"$BACKEND" | tr -d '[]')
mapfile -t IPS_BACKEND < <(getent ahosts "$HOST_BACKEND" | awk '{print $1}' | sort -u)
[[ ${#IPS_BACKEND[@]} -gt 0 ]] || fallo "no se pudo resolver $HOST_BACKEND"
mapfile -t IPS_DNS < <(awk '$1 == "nameserver" {print $2}' /etc/resolv.conf 2>/dev/null | sort -u)
echo "    backend $HOST_BACKEND → ${IPS_BACKEND[*]}"

# ---------------------------------------------------------------------------
# Instalación
# ---------------------------------------------------------------------------
paso "Usuario sin privilegios «$USUARIO»"
if ! getent passwd "$USUARIO" >/dev/null; then
	hacer useradd --system --user-group --no-create-home --home-dir "$DIR_ESTADO" \
		--shell /usr/sbin/nologin "$USUARIO"
fi

paso "Binarios"
hacer install -o root -g root -m 0755 "$BINARIOS/passwd-agente" "$BIN_AGENTE"
hacer install -o root -g root -m 0700 "$BINARIOS/passwd-agente-helper" "$BIN_HELPER"

paso "Configuración"
hacer install -d -o root -g "$USUARIO" -m 0750 "$DIR_CONFIG"
hacer install -d -o "$USUARIO" -g "$USUARIO" -m 0700 "$DIR_ESTADO"
if [[ -n $CA_FILE ]]; then
	hacer install -o root -g "$USUARIO" -m 0640 "$CA_FILE" "$DIR_CONFIG/ca.pem"
fi

json_lista() {
	local primero=1 salida="["
	for elemento in "$@"; do
		[[ $primero -eq 1 ]] || salida+=", "
		salida+="\"$elemento\""
		primero=0
	done
	printf '%s]' "$salida"
}

config_agente=$(cat <<EOF
{
  "backend": "$BACKEND",
  "ca_file": "$([[ -n $CA_FILE ]] && echo "$DIR_CONFIG/ca.pem")",
  "pin_sha256": "$PIN",
  "identidad": "$DIR_ESTADO/identidad.json",
  "journal": "$DIR_ESTADO/journal.bin",
  "helper": "$SOCKET"
}
EOF
)
# El agente la lee pero no puede modificarla: nada se configura desde la red.
escribir "$DIR_CONFIG/config.json" "root:$USUARIO" 0640 "$config_agente"

# La lista de cuentas es de root: si el agente pudiera escribirla, se
# concedería a sí mismo cualquier cuenta.
config_helper=$(printf '{\n  "usuario_agente": "%s",\n  "cuentas": %s\n}\n' "$USUARIO" "$(json_lista "${LISTA_CUENTAS[@]}")")
escribir "$DIR_CONFIG/helper.json" root:root 0644 "$config_helper"

escribir /etc/pam.d/passwd-agente-helper root:root 0644 "$(cat "$DIR_FUENTE/passwd-agente-helper.pam")"

paso "Unidades systemd"
for unidad in passwd-agente.service passwd-agente-helper.socket passwd-agente-helper@.service; do
	hacer install -o root -g root -m 0644 "$DIR_FUENTE/$unidad" "$DIR_UNIDADES/$unidad"
done
hacer install -d -o root -g root -m 0755 "$DIR_UNIDADES/passwd-agente.service.d"
red="[Service]
# Escrito por instalar.sh: el agente solo puede salir hacia estas direcciones.
IPAddressAllow=localhost ${IPS_BACKEND[*]} ${IPS_DNS[*]}
"
escribir "$DIR_UNIDADES/passwd-agente.service.d/red.conf" root:root 0644 "$red"
hacer systemctl daemon-reload
hacer systemctl enable --now passwd-agente-helper.socket

paso "Enrolamiento"
if [[ $SIMULAR -eq 1 ]]; then
	echo "    + runuser -u $USUARIO -- $BIN_AGENTE enrolar --config $DIR_CONFIG/config.json --token - --forzar  (token por la entrada estándar)"
else
	# El token va por una tubería (printf es interno de bash): nunca aparece en
	# la línea de órdenes de ningún proceso, así que ps no lo ve.
	printf '%s\n' "$TOKEN" |
		runuser -u "$USUARIO" -- "$BIN_AGENTE" enrolar --config "$DIR_CONFIG/config.json" --token - --forzar
fi

paso "Arranque"
hacer systemctl enable passwd-agente.service
# restart y no «enable --now»: en una reinstalación el agente ya corre con la
# identidad anterior en memoria, y «--now» no reinicia un servicio activo. Se
# quedaría usando una identidad revocada mientras la nueva espera en disco.
hacer systemctl restart passwd-agente.service
if [[ $SIMULAR -eq 0 ]]; then
	sleep 3
	systemctl is-active --quiet passwd-agente.service ||
		fallo "el servicio no quedó activo: journalctl -u passwd-agente.service"
	systemctl is-active --quiet passwd-agente-helper.socket ||
		fallo "el socket del helper no quedó activo"
fi
paso "Agente instalado. Estado: systemctl status passwd-agente.service"
