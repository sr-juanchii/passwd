#!/usr/bin/env bash
# ── Verificación del build del frontend: qué se publica al navegador ─────────
#
# Comprueba que los artefactos que nginx sirve públicamente (.next/static y el
# directorio public/) no contengan material que reconstruya el código fuente ni
# secretos de servidor.
#
# Lo que este control SÍ garantiza:
#   · No se publican mapas de origen (*.map) → nada de TypeScript original,
#     nombres de variables ni comentarios.
#   · No se filtran secretos de servidor al bundle del cliente.
#   · No se publican rutas absolutas de la máquina de compilación.
#
# Lo que NO garantiza (ni puede):
#   · Que nadie lea el JavaScript minificado desde las herramientas de
#     desarrollador. Es código que el navegador debe ejecutar; quien controla el
#     navegador lo puede leer siempre. Ver docs/proteccion-codigo-fuente.md.
#
# Uso:  scripts/verificar-build-frontend.sh [directorio-frontend]
#       (requiere haber ejecutado `pnpm build` antes)

set -euo pipefail

FRONTEND="${1:-frontend}"
ESTATICOS="${FRONTEND}/.next/static"
PUBLICO="${FRONTEND}/public"
fallos=0

rojo()  { printf '\033[31m%s\033[0m\n' "$*"; }
verde() { printf '\033[32m%s\033[0m\n' "$*"; }
aviso() { printf '\033[33m%s\033[0m\n' "$*"; }

if [ ! -d "$ESTATICOS" ]; then
  rojo "ERROR: no existe ${ESTATICOS}. Ejecute 'pnpm build' en ${FRONTEND} antes de verificar."
  exit 1
fi

# ── 1. Mapas de origen en los artefactos servidos al navegador ───────────────
echo "== 1/3 Mapas de origen (*.map) en los estáticos públicos =="
mapas=$(find "$ESTATICOS" "$PUBLICO" -type f -name '*.map' 2>/dev/null || true)
if [ -n "$mapas" ]; then
  rojo "FALLO: hay mapas de origen publicados; reconstruyen el código fuente original:"
  printf '  %s\n' $mapas
  rojo "  Corrija 'productionBrowserSourceMaps' en next.config.ts (debe ser false)."
  fallos=$((fallos + 1))
else
  verde "OK: ningún archivo .map en los estáticos públicos."
fi

# ── 2. Secretos de servidor filtrados al bundle del cliente ──────────────────
# Todo lo que el navegador descarga es público de hecho. Estas variables son de
# servidor y nunca deben aparecer en el bundle (en Next solo cruzarían la
# frontera con el prefijo NEXT_PUBLIC_, que este proyecto no usa).
echo "== 2/3 Secretos de servidor en el bundle del cliente =="
PATRONES_SECRETOS='PASSWD_SECRET_KEY|PASSWD_ENCRYPTION_KEY|PASSWD_ADMIN_PASSWORD|PASSWD_DATABASE_URL|PASSWD_SMTP_PASSWORD|-----BEGIN [A-Z ]*PRIVATE KEY-----'
if coincidencias=$(grep -rIlE "$PATRONES_SECRETOS" "$ESTATICOS" "$PUBLICO" 2>/dev/null); then
  rojo "FALLO: posibles secretos de servidor en artefactos públicos:"
  printf '  %s\n' $coincidencias
  fallos=$((fallos + 1))
else
  verde "OK: ningún patrón de secreto de servidor en los estáticos públicos."
fi

# ── 3. Rutas absolutas de la máquina de compilación ──────────────────────────
# Revelan el árbol de directorios del build (y a veces nombres de usuario).
echo "== 3/3 Rutas absolutas de la máquina de compilación =="
if rutas=$(grep -rIloE '/(home|Users|builds|github/workspace)/[A-Za-z0-9._-]+/' "$ESTATICOS" 2>/dev/null | sort -u); then
  aviso "AVISO: hay rutas absolutas del entorno de compilación en el bundle:"
  printf '  %s\n' $rutas
  aviso "  No es explotable por sí solo, pero conviene eliminarlo del build."
else
  verde "OK: sin rutas absolutas del entorno de compilación."
fi

echo
if [ "$fallos" -gt 0 ]; then
  rojo "Verificación FALLIDA: ${fallos} control(es) en rojo."
  exit 1
fi
verde "Verificación superada: los artefactos públicos no exponen código fuente ni secretos."
