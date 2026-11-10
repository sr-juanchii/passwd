// Lógica pura del aviso de expiración de sesión (sin React ni DOM, para poder
// probarla con vitest). La sesión tiene dos plazos que impone el servidor:
// inactividad (se renueva con el uso o con «Extender sesión») y vida máxima
// absoluta (no se puede prolongar).

/** Plazos que devuelve el backend en `/session` (en segundos). */
export interface PlazosSesion {
  idle_expires_in: number;
  absolute_expires_in: number;
  /** Ventana de inactividad completa. */
  idle_timeout: number;
  /** Imprecisión de la marca de actividad del servidor (amortiguación). */
  margin: number;
}

/** Los mismos plazos convertidos a instantes del reloj local (epoch ms). */
export interface Vencimientos {
  inactividadEn: number;
  absolutaEn: number;
  idleTimeoutMs: number;
  margenMs: number;
}

export type MotivoVencimiento = "inactividad" | "vida_maxima";

export interface EstadoExpiracion {
  fase: "ok" | "aviso" | "vencida";
  /** Milisegundos hasta el cierre (0 si ya venció). */
  restanteMs: number;
  /** Qué plazo vence primero. */
  motivo: MotivoVencimiento;
  /** `false` si lo que vence es la vida máxima: extender no serviría. */
  extensible: boolean;
}

const AVISO_MAXIMO_S = 120;

export function aVencimientos(p: PlazosSesion, ahora: number): Vencimientos {
  return {
    inactividadEn: ahora + p.idle_expires_in * 1000,
    absolutaEn: ahora + p.absolute_expires_in * 1000,
    idleTimeoutMs: p.idle_timeout * 1000,
    margenMs: p.margin * 1000,
  };
}

/**
 * Tras una petición correcta a la API la ventana de inactividad se renueva. El
 * servidor solo anota la actividad cada `margen`, así que se descuenta ese
 * margen: la estimación local nunca es más optimista que la real.
 */
export function trasActividad(v: Vencimientos, ahora: number): Vencimientos {
  const estimada = ahora + v.idleTimeoutMs - v.margenMs;
  return { ...v, inactividadEn: Math.max(v.inactividadEn, estimada) };
}

/** Antelación del aviso: 2 minutos, o la mitad de la ventana si es más corta. */
export function antelacionAvisoMs(v: Vencimientos): number {
  return Math.min(AVISO_MAXIMO_S * 1000, Math.floor(v.idleTimeoutMs / 2));
}

export function estadoExpiracion(v: Vencimientos, ahora: number): EstadoExpiracion {
  const porInactividad = v.inactividadEn <= v.absolutaEn;
  const venceEn = porInactividad ? v.inactividadEn : v.absolutaEn;
  const restanteMs = Math.max(0, venceEn - ahora);
  const motivo: MotivoVencimiento = porInactividad ? "inactividad" : "vida_maxima";
  const fase = restanteMs === 0 ? "vencida" : restanteMs <= antelacionAvisoMs(v) ? "aviso" : "ok";
  return { fase, restanteMs, motivo, extensible: porInactividad };
}

/** `95000` → `"1:35"`. */
export function formatoCuentaAtras(ms: number): string {
  const total = Math.ceil(ms / 1000);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

// --- Regreso a la página en la que estaba el usuario tras volver a entrar ---

const PREFIJOS_AUTH = ["/login", "/mfa", "/password", "/recuperar"];

/**
 * Solo se acepta una ruta interna de la aplicación: empieza por una única `/`,
 * sin esquema ni host (`//otro.sitio`, `/\otro`), y no es una pantalla de acceso.
 */
export function rutaRetornoSegura(valor: string | null | undefined): string | null {
  if (!valor || !valor.startsWith("/") || valor.startsWith("//") || valor.includes("\\")) return null;
  if (/[\u0000-\u001f]/.test(valor)) return null;
  const ruta = valor.split(/[?#]/)[0];
  if (PREFIJOS_AUTH.some((p) => ruta === p || ruta.startsWith(`${p}/`))) return null;
  return valor;
}

export type MotivoSalida = "expirada" | "cerrada";

/** Mensajes FIJOS del login según el motivo (nunca texto libre de la URL). */
export const MENSAJES_LOGIN: Record<string, string> = {
  expirada: "Por seguridad, su sesión se cerró automáticamente. Inicie sesión de nuevo para continuar.",
  cerrada: "Ha cerrado la sesión correctamente.",
  bloqueada: "Cuenta bloqueada temporalmente. Vuelva a intentarlo más tarde.",
  restablecida: "Contraseña restablecida. Inicie sesión.",
};

export function rutaLogin(motivo: MotivoSalida | null, rutaActual?: string): string {
  if (!motivo) return "/login";
  const params = new URLSearchParams({ motivo });
  const retorno = motivo === "expirada" ? rutaRetornoSegura(rutaActual) : null;
  if (retorno && retorno !== "/") params.set("next", retorno);
  return `/login?${params.toString()}`;
}

// El destino se guarda durante el reingreso (login → MFA) en sessionStorage:
// vive solo en esa pestaña y no viaja en más URLs.
const CLAVE_RETORNO = "passwd_retorno";

export function guardarRetorno(valor: string | null): void {
  const ruta = rutaRetornoSegura(valor);
  try {
    if (ruta) sessionStorage.setItem(CLAVE_RETORNO, ruta);
    else sessionStorage.removeItem(CLAVE_RETORNO);
  } catch {
    /* almacenamiento no disponible */
  }
}

/** Devuelve (y olvida) el destino guardado; `/` si no hay ninguno válido. */
export function consumirRetorno(): string {
  try {
    const ruta = rutaRetornoSegura(sessionStorage.getItem(CLAVE_RETORNO));
    sessionStorage.removeItem(CLAVE_RETORNO);
    return ruta ?? "/";
  } catch {
    return "/";
  }
}
