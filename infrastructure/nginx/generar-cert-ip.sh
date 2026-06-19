#!/usr/bin/env sh
# Certificado AUTOFIRMADO para una IP o un hostname interno (red interna SIN
# dominio público). A diferencia de generar-cert-autofirmado.sh, mete la IP en
# el SAN como `IP:` (lo correcto para certificados por dirección).
#
# Crea infrastructure/nginx/certs/{fullchain,privkey}.pem — justo donde nginx
# los espera (los monta en /etc/nginx/certs). El navegador mostrará una
# advertencia (esperado en autofirmados); para evitarla en toda la intranet usa
# generar-ca-interna.sh e instala la CA en los clientes.
#
# Uso:   ./generar-cert-ip.sh <IP-o-hostname> [dias]
#        ./generar-cert-ip.sh 192.168.1.50
#        ./generar-cert-ip.sh passwd.interno 825
#
# Recuerda fijar PASSWD_DOMAIN con el MISMO valor en tu .env.

set -eu

DIR="$(cd "$(dirname "$0")" && pwd)/certs"
HOST="${1:?Uso: ./generar-cert-ip.sh <IP-o-hostname> [dias]}"
DIAS="${2:-825}"

mkdir -p "$DIR"

# Si HOST contiene solo dígitos y puntos lo tratamos como IPv4; si no, como DNS.
case "$HOST" in
    *[!0-9.]*) SAN="DNS:$HOST,DNS:localhost,IP:127.0.0.1" ;;  # hostname
    *)         SAN="IP:$HOST,DNS:localhost,IP:127.0.0.1" ;;   # IPv4
esac

openssl req -x509 -nodes -newkey rsa:2048 -days "$DIAS" \
    -keyout "$DIR/privkey.pem" \
    -out "$DIR/fullchain.pem" \
    -subj "/CN=$HOST" \
    -addext "subjectAltName=$SAN"

chmod 600 "$DIR/privkey.pem"
chmod 644 "$DIR/fullchain.pem"

echo "Certificado autofirmado para '$HOST' creado en $DIR (válido $DIAS días)."
echo "SAN: $SAN"
echo "Pon PASSWD_DOMAIN=$HOST en tu .env. El navegador avisará (autofirmado)."
