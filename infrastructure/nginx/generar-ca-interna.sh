#!/usr/bin/env sh
# CA interna propia + certificado de servidor firmado por ella, para una IP o
# hostname interno SIN dominio público y SIN advertencias del navegador (una vez
# que se instala la CA raíz en los equipos cliente).
#
# Genera:
#   infrastructure/nginx/certs/fullchain.pem  (servidor + CA)  -> lo usa nginx
#   infrastructure/nginx/certs/privkey.pem    (clave servidor) -> lo usa nginx
#   infrastructure/nginx/certs/ca.crt         (raíz a DISTRIBUIR e instalar)
# La clave privada de la CA se guarda en infrastructure/nginx/ca/ca.key (NO la
# sirve nginx y está en .gitignore). Custódiala: con ella se pueden emitir
# certificados de confianza para tu red.
#
# Uso:   ./generar-ca-interna.sh <IP-o-hostname> [dias]
#        ./generar-ca-interna.sh 192.168.1.50
#
# Después: instala certs/ca.crt como raíz de confianza en cada cliente y pon
# PASSWD_DOMAIN con el mismo <IP-o-hostname> en tu .env.

set -eu

BASE="$(cd "$(dirname "$0")" && pwd)"
DIR="$BASE/certs"
CA_DIR="$BASE/ca"
HOST="${1:?Uso: ./generar-ca-interna.sh <IP-o-hostname> [dias]}"
DIAS="${2:-825}"

mkdir -p "$DIR" "$CA_DIR"

case "$HOST" in
    *[!0-9.]*) SAN="DNS:$HOST,DNS:localhost,IP:127.0.0.1" ;;  # hostname
    *)         SAN="IP:$HOST,DNS:localhost,IP:127.0.0.1" ;;   # IPv4
esac

# 1) CA raíz (se crea una sola vez; se reutiliza en emisiones posteriores).
if [ ! -f "$CA_DIR/ca.key" ]; then
    echo "Creando CA interna nueva en $CA_DIR ..."
    openssl genrsa -out "$CA_DIR/ca.key" 4096
    openssl req -x509 -new -nodes -key "$CA_DIR/ca.key" -sha256 -days 3650 \
        -out "$CA_DIR/ca.crt" -subj "/CN=passwd CA Interna"
    chmod 600 "$CA_DIR/ca.key"
else
    echo "Reutilizando CA existente en $CA_DIR/ca.key"
fi

# 2) Certificado del servidor firmado por la CA.
openssl genrsa -out "$DIR/privkey.pem" 2048
openssl req -new -key "$DIR/privkey.pem" -out "$CA_DIR/server.csr" -subj "/CN=$HOST"
printf "subjectAltName=%s\n" "$SAN" > "$CA_DIR/san.ext"
openssl x509 -req -in "$CA_DIR/server.csr" \
    -CA "$CA_DIR/ca.crt" -CAkey "$CA_DIR/ca.key" -CAcreateserial \
    -out "$CA_DIR/server.crt" -days "$DIAS" -sha256 -extfile "$CA_DIR/san.ext"

# 3) fullchain = certificado del servidor + CA (para validar la cadena).
cat "$CA_DIR/server.crt" "$CA_DIR/ca.crt" > "$DIR/fullchain.pem"
cp "$CA_DIR/ca.crt" "$DIR/ca.crt"
chmod 600 "$DIR/privkey.pem"
chmod 644 "$DIR/fullchain.pem" "$DIR/ca.crt"
rm -f "$CA_DIR/server.csr" "$CA_DIR/san.ext"

echo ""
echo "Listo. nginx usará certs/fullchain.pem + certs/privkey.pem (válido $DIAS días)."
echo "SAN del servidor: $SAN"
echo ""
echo "Para eliminar el aviso del navegador en la intranet, distribuye"
echo "  $DIR/ca.crt  (NUNCA la ca.key)"
echo "e instálalo como entidad raíz de confianza en cada cliente:"
echo "  - Windows: certlm.msc -> Entidades de certificación raíz de confianza -> Importar"
echo "  - macOS:   Llavero -> Sistema -> importar ca.crt -> 'Confiar siempre'"
echo "  - Linux:   copiar a /usr/local/share/ca-certificates/ y 'sudo update-ca-certificates'"
echo "  - Firefox: Ajustes -> Certificados -> Importar (almacén propio)"
echo ""
echo "Pon PASSWD_DOMAIN=$HOST en tu .env."
