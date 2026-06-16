<#
.SYNOPSIS
  Genera un certificado AUTOFIRMADO para PRUEBAS locales en Windows (no usar en
  producción). Crea infrastructure\nginx\certs\{fullchain,privkey}.pem, que es
  exactamente donde nginx los espera.

.DESCRIPTION
  Equivalente en PowerShell de generar-cert-autofirmado.sh. Usa el OpenSSL del
  sistema si está disponible (p. ej. el que trae Git para Windows); si no, hace
  un respaldo ejecutando OpenSSL dentro de un contenedor Docker, de modo que no
  hace falta instalar nada (solo Docker Desktop, que ya se usa para desplegar).

.PARAMETER Dominio
  Nombre común (CN) del certificado. Por defecto: localhost.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\infrastructure\nginx\generar-cert-autofirmado.ps1 localhost
#>
[CmdletBinding()]
param([string]$Dominio = "localhost")

$ErrorActionPreference = "Stop"

$Dir = Join-Path $PSScriptRoot "certs"
New-Item -ItemType Directory -Force -Path $Dir | Out-Null

$subj = "/CN=$Dominio"
$san  = "subjectAltName=DNS:$Dominio,DNS:localhost,IP:127.0.0.1"
$key  = Join-Path $Dir "privkey.pem"
$crt  = Join-Path $Dir "fullchain.pem"

if (Get-Command openssl -ErrorAction SilentlyContinue) {
    Write-Host "Usando OpenSSL del sistema..."
    & openssl req -x509 -nodes -newkey rsa:2048 -days 365 `
        -keyout $key -out $crt -subj $subj -addext $san
}
elseif (Get-Command docker -ErrorAction SilentlyContinue) {
    Write-Host "OpenSSL no encontrado; usando OpenSSL dentro de Docker..."
    docker run --rm -v "${Dir}:/certs" alpine/openssl req -x509 -nodes -newkey rsa:2048 -days 365 `
        -keyout /certs/privkey.pem -out /certs/fullchain.pem -subj $subj -addext $san
}
else {
    throw "No se encontró ni OpenSSL ni Docker. Instale Git para Windows (incluye OpenSSL) o Docker Desktop."
}

if (-not (Test-Path $crt) -or -not (Test-Path $key)) {
    throw "No se generaron los certificados; revise la salida anterior."
}

Write-Host ""
Write-Host "Certificado autofirmado creado en $Dir"
Write-Host "  CN=$Dominio - validez 365 dias"
Write-Host "Los navegadores mostraran una advertencia (esperado en autofirmados)."
