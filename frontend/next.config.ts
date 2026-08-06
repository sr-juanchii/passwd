import type { NextConfig } from "next";

// El backend FastAPI sirve la API JSON en /api/web. En desarrollo lo proxyamos
// para que el navegador vea un único origen (mismo sitio) y la cookie de sesión
// HttpOnly + SameSite=Strict viaje como cookie de primera parte. En producción
// nginx hace el mismo enrutado hacia el backend.
const API_BASE = process.env.PASSWD_API_BASE ?? "http://127.0.0.1:8000";

// CSP de las páginas HTML del frontend (las rutas /api las cubre el backend
// con su propia CSP estricta). Next inyecta scripts y estilos inline para la
// hidratación, por lo que sin nonces —que exigirían renderizado dinámico en
// todas las páginas— se necesita 'unsafe-inline'; la política sigue vetando
// orígenes externos, framing, plugins y cambios de base/form-action.
const CSP = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self'",
  "connect-src 'self'",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
].join("; ");

const nextConfig: NextConfig = {
  // Salida autocontenida para una imagen Docker mínima (server.js + estáticos).
  output: "standalone",

  // ── Reducción de superficie de información del cliente ─────────────────────
  // NO impide leer el bundle desde las herramientas de desarrollador: el
  // JavaScript que ejecuta el navegador es, por definición, legible por quien
  // controla ese navegador. Lo que sí se elimina es la información EXTRA que
  // no hace falta para ejecutar la aplicación (ver docs/proteccion-codigo-fuente.md).

  // Sin mapas de origen en el navegador: el bundle de producción queda
  // minificado y sin nombres originales de archivos, módulos ni variables.
  // Es el valor por omisión de Next; se fija de forma explícita para que un
  // cambio accidental a `true` se vea en la revisión de código.
  productionBrowserSourceMaps: false,

  // Sin `X-Powered-By: Next.js`: no se anuncia el framework (OWASP A05 —
  // configuración de seguridad incorrecta / fuga de huella tecnológica).
  poweredByHeader: false,
  async rewrites() {
    return [
      { source: "/api/web/:path*", destination: `${API_BASE}/api/web/:path*` },
      { source: "/api/v1/:path*", destination: `${API_BASE}/api/v1/:path*` },
      { source: "/healthz", destination: `${API_BASE}/healthz` },
    ];
  },
  async headers() {
    return [
      {
        // Todo lo servido por Next, EXCEPTO los rewrites hacia el backend
        // (/api/*, /healthz): esos ya responden con las cabeceras del propio
        // backend y duplicarlas aquí generaría cabeceras dobles.
        source: "/((?!api/|healthz).*)",
        headers: [
          { key: "Content-Security-Policy", value: CSP },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "no-referrer" },
          // Aplicación interna: no debe indexarse ni archivarse en buscadores
          // ni en cachés públicas (evita que rutas y marcado queden expuestos
          // en copias de terceros como el archivo de Google o archive.org).
          { key: "X-Robots-Tag", value: "noindex, nofollow, noarchive, nosnippet" },
        ],
      },
    ];
  },
};

export default nextConfig;
