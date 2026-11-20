#!/usr/bin/env node
/**
 * Levanta el frontend tal y como se despliega: el build `standalone` que el
 * contenedor arranca con `node server.js` (ver frontend/Dockerfile).
 *
 * Por qué no las dos formas evidentes:
 *
 *   - `next dev` no sirve. React en desarrollo necesita `eval()` y la CSP de
 *     next.config.ts no lo permite: la página no llega a hidratarse y los
 *     formularios se quedan deshabilitados para siempre.
 *   - `next start` tampoco. Next lo rechaza cuando `output: "standalone"`
 *     («does not work with "output: standalone"»), y sin él los rewrites
 *     hacia el backend no se aplican: el navegador recibe 404 en /api/web/*.
 *
 * Además, los rewrites se resuelven en el BUILD —quedan escritos en
 * routes-manifest.json—, así que PASSWD_API_BASE tiene que estar definida
 * cuando se compila, no solo cuando se arranca.
 */
import { spawn, spawnSync } from "node:child_process";
import { cpSync, existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const RAIZ = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const STANDALONE = path.join(RAIZ, ".next", "standalone");

function paso(orden, args) {
  const r = spawnSync(orden, args, { cwd: RAIZ, stdio: "inherit", shell: process.platform === "win32" });
  if (r.status !== 0) process.exit(r.status ?? 1);
}

// Reutilizable entre tandas locales: compilar cuesta ~40 s y el código del
// frontend no cambia entre pruebas. En CI siempre se compila.
const sinBuild = process.env.PASSWD_E2E_SIN_BUILD === "1" && existsSync(path.join(STANDALONE, "server.js"));
if (!sinBuild) {
  paso("pnpm", ["exec", "next", "build"]);
  // Lo mismo que copia el Dockerfile: el build standalone deja fuera los
  // estáticos y `public` a propósito, para servirlos desde una CDN si se
  // quiere. Aquí los sirve el propio Next.
  cpSync(path.join(RAIZ, ".next", "static"), path.join(STANDALONE, ".next", "static"), { recursive: true });
  if (existsSync(path.join(RAIZ, "public"))) {
    cpSync(path.join(RAIZ, "public"), path.join(STANDALONE, "public"), { recursive: true });
  }
}

const servidor = spawn(process.execPath, [path.join(STANDALONE, "server.js")], {
  cwd: STANDALONE,
  stdio: "inherit",
  env: { ...process.env, HOSTNAME: "127.0.0.1" },
});
for (const senal of ["SIGINT", "SIGTERM"]) process.on(senal, () => servidor.kill(senal));
servidor.on("exit", (codigo) => process.exit(codigo ?? 1));
