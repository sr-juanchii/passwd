import type { NextConfig } from "next";

// El backend FastAPI sirve la API JSON en /api/web. En desarrollo lo proxyamos
// para que el navegador vea un único origen (mismo sitio) y la cookie de sesión
// HttpOnly + SameSite=Strict viaje como cookie de primera parte. En producción
// nginx hace el mismo enrutado hacia el backend.
const API_BASE = process.env.PASSWD_API_BASE ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      { source: "/api/web/:path*", destination: `${API_BASE}/api/web/:path*` },
      { source: "/api/v1/:path*", destination: `${API_BASE}/api/v1/:path*` },
      { source: "/healthz", destination: `${API_BASE}/healthz` },
    ];
  },
};

export default nextConfig;
