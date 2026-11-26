#!/usr/bin/env bash
# Empaqueta el agente de rotación tal como se publica en cada Release:
#
#   ./empaquetar.sh 1.4.0 amd64 ./dist
#
# deja ./dist/passwd-agente-1.4.0-linux-amd64.tar.gz con un directorio
# passwd-agente-1.4.0-linux-amd64/ que contiene los dos binarios con su
# versión, su SHA256SUMS, instalar.sh, las unidades systemd y el servicio PAM.
# Desde ese directorio basta:
#
#   sudo ./instalar.sh --backend … --cuentas … --sumas ./SHA256SUMS --token -
#
# El agente es estático (sin cgo) y se podría compilar para cualquier
# arquitectura, pero el helper enlaza libpam (cgo): por eso todo el paquete se
# compila en una máquina de la arquitectura pedida, y si no lo es, falla.
#
# Lo usan los flujos de publicación (.github/workflows/binarios-agente.yml) y
# la prueba de sistema de la CI, que instala desde este mismo paquete.
set -euo pipefail

fallo() {
	echo "empaquetar.sh: $*" >&2
	exit 1
}

[[ $# -eq 3 ]] || fallo "uso: $0 VERSION ARQUITECTURA(amd64|arm64) DIRECTORIO_DE_SALIDA"
VERSION=$1
ARCH=$2
SALIDA=$3

[[ $VERSION =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]] || fallo "versión no admitida: «$VERSION»"
case $ARCH in
amd64) MAQUINA=x86_64 ;;
arm64) MAQUINA=aarch64 ;;
*) fallo "arquitectura no admitida: «$ARCH» (amd64 o arm64)" ;;
esac
[[ $(uname -m) == "$MAQUINA" ]] ||
	fallo "compile en una máquina $MAQUINA: el helper enlaza libpam (cgo) y no se compila cruzado"

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NOMBRE="passwd-agente-$VERSION-linux-$ARCH"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
DESTINO="$TMP/$NOMBRE"
mkdir -p "$DESTINO"

BANDERAS="-s -w -X main.version=$VERSION"
(cd "$DIR" && CGO_ENABLED=0 GOOS=linux GOARCH="$ARCH" go build -trimpath -ldflags "$BANDERAS" \
	-o "$DESTINO/passwd-agente" ./cmd/passwd-agente)
(cd "$DIR" && CGO_ENABLED=1 GOOS=linux GOARCH="$ARCH" go build -trimpath -ldflags "$BANDERAS" \
	-o "$DESTINO/passwd-agente-helper" ./cmd/passwd-agente-helper)

# Los dos binarios deben declarar la versión del paquete: es lo que el agente
# dice al backend, y lo que la prueba de sistema comprueba.
[[ $("$DESTINO/passwd-agente" version) == "$VERSION" ]] || fallo "el agente no declara la versión $VERSION"
[[ $("$DESTINO/passwd-agente-helper" --version) == "$VERSION" ]] || fallo "el helper no declara la versión $VERSION"

install -m 0755 "$DIR/instalacion/instalar.sh" "$DESTINO/instalar.sh"
for archivo in passwd-agente.service passwd-agente-helper.socket passwd-agente-helper@.service \
	passwd-agente-helper.pam; do
	install -m 0644 "$DIR/instalacion/$archivo" "$DESTINO/$archivo"
done
(cd "$DESTINO" && sha256sum passwd-agente passwd-agente-helper >SHA256SUMS)

mkdir -p "$SALIDA"
# Dueño root y orden fijo: el paquete no depende de quién ni en qué orden lo generó.
tar -C "$TMP" --owner=0 --group=0 --numeric-owner --sort=name -czf "$SALIDA/$NOMBRE.tar.gz" "$NOMBRE"
echo "$SALIDA/$NOMBRE.tar.gz"
