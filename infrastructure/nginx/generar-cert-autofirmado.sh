#!/usr/bin/env sh
# Genera un certificado AUTOFIRMADO para PRUEBAS locales (no usar en producción).
# Crea infrastructure/nginx/certs/{fullchain,privkey}.pem, que es exactamente
# donde nginx los espera.
#
# Uso:   ./generar-cert-autofirmado.sh [dominio]
#        (por defecto: localhost)

set -eu

DIR="$(cd "$(dirname "$0")" && pwd)/certs"
DOMINIO="${1:-localhost}"

mkdir -p "$DIR"
openssl req -x509 -nodes -newkey rsa:2048 -days 365 \
    -keyout "$DIR/privkey.pem" \
    -out "$DIR/fullchain.pem" \
    -subj "/CN=$DOMINIO" \
    -addext "subjectAltName=DNS:$DOMINIO,DNS:localhost,IP:127.0.0.1"

chmod 600 "$DIR/privkey.pem"
chmod 644 "$DIR/fullchain.pem"

echo "Certificado autofirmado creado en $DIR"
echo "  CN=$DOMINIO · validez 365 días"
echo "Los navegadores mostrarán una advertencia (esperado en autofirmados)."
