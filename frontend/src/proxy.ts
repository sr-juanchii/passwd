import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Guard de rutas en el borde (el "middleware" se llama `proxy` en esta versión
// de Next). Redirige a /login cuando NO hay cookie de sesión, evitando el
// destello de layout antes del guard client-side. Es una heurística por
// presencia de cookie: la validez real (sesión activa, etapa, permisos) la
// sigue imponiendo el backend en cada petición.
const COOKIE_SESION = "passwd_session";

// Prefijos públicos (no requieren sesión). El resto exige la cookie.
const PUBLICAS = ["/login", "/mfa", "/password"];

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const esPublica = PUBLICAS.some((p) => pathname === p || pathname.startsWith(`${p}/`));
  const tieneSesion = request.cookies.has(COOKIE_SESION);

  if (!tieneSesion && !esPublica) {
    const destino = new URL("/login", request.url);
    return NextResponse.redirect(destino);
  }
  return NextResponse.next();
}

export const config = {
  // Excluye API (proxied al backend), assets de Next, healthcheck y favicon.
  matcher: ["/((?!api/|_next/|healthz|favicon.ico).*)"],
};
