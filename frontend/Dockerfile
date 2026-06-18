# Imagen del frontend Next.js (App Router) — build autocontenido (standalone).
# Multi-etapa: dependencias -> build -> runtime mínimo sin privilegios.

# ── Dependencias ─────────────────────────────────────────────────────────────
FROM node:22-slim AS deps
WORKDIR /app
# Corepack usa la versión de pnpm fijada en package.json (campo packageManager),
# sin prompt interactivo de descarga.
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0
COPY package.json pnpm-lock.yaml ./
RUN corepack enable && pnpm install --frozen-lockfile

# ── Build ────────────────────────────────────────────────────────────────────
FROM node:22-slim AS build
WORKDIR /app
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0
ENV NEXT_TELEMETRY_DISABLED=1
# La base de la API se hornea en los rewrites en tiempo de BUILD (Next escribe
# routes-manifest.json al compilar; la variable en runtime NO surte efecto). En
# el stack con nginx no es la ruta normal —nginx enruta /api directo al backend—
# pero deja el rewrite de respaldo del servidor Next apuntando al servicio
# correcto (`app:8000`). Sobreescribible con --build-arg PASSWD_API_BASE=...
ARG PASSWD_API_BASE=http://app:8000
ENV PASSWD_API_BASE=$PASSWD_API_BASE
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN corepack enable && pnpm build

# ── Runtime ──────────────────────────────────────────────────────────────────
FROM node:22-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

# Usuario sin privilegios (CIS 4.x).
RUN groupadd --gid 1001 nextjs && useradd --uid 1001 --gid 1001 --create-home nextjs

# Artefactos del build standalone: server.js + node_modules mínimos, estáticos y public.
COPY --from=build --chown=nextjs:nextjs /app/.next/standalone ./
COPY --from=build --chown=nextjs:nextjs /app/.next/static ./.next/static
COPY --from=build --chown=nextjs:nextjs /app/public ./public

USER nextjs
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:3000/login').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "server.js"]
