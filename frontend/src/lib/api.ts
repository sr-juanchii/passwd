// Cliente de la API JSON (`/api/web`). Maneja el token CSRF (cabecera
// X-CSRF-Token) y los errores uniformes `{detail}`. La cookie de sesión viaja
// sola (mismo origen vía proxy de Next).

import type {
  AuditoriaPagina,
  Concesion,
  ConfiguracionResp,
  CredencialDetalle,
  CredencialInput,
  Dashboard,
  DispositivoDetalle,
  DispositivoInput,
  EnvioCodigoCorreo,
  HipervisorDetalle,
  HipervisorInput,
  Metricas,
  MetodosAccesoMfa,
  MetodosAltaMfa,
  NivelAcceso,
  ResultadoBusqueda,
  ResultadoImportacion,
  SeguridadCuenta,
  ServidorDetalle,
  ServidorInput,
  SessionState,
  TipoActivo,
  TokenApi,
  Usuario,
  VaultEntrada,
  VaultInput,
  VmDetalle,
  VmInput,
} from "./types";
import type { PlazosSesion } from "./expiracion";

export class ApiError extends Error {
  status: number;
  code?: string;
  constructor(status: number, message: string, code?: string) {
    super(message);
    this.status = status;
    this.code = code;
    this.name = "ApiError";
  }
}

// --- Vigilancia de la sesión (la registra SessionProvider) ---
// `alExpirar`: la API respondió 401 a una petición de la aplicación → la sesión
// ya no existe en el servidor. `alHaberActividad`: una petición autenticada salió
// bien → la ventana de inactividad se renovó.
let alExpirar: (() => void) | null = null;
let alHaberActividad: (() => void) | null = null;
export function vigilarSesion(h: { alExpirar: () => void; alHaberActividad: () => void } | null) {
  alExpirar = h?.alExpirar ?? null;
  alHaberActividad = h?.alHaberActividad ?? null;
}

// Rutas del flujo de acceso: ahí un 401 es una respuesta normal (credenciales o
// código incorrectos), no una sesión vencida; y no cuentan como actividad.
const RUTAS_ACCESO = ["/login", "/csrf", "/session", "/mfa/", "/password/recuperar"];
function esRutaDeAcceso(path: string): boolean {
  return RUTAS_ACCESO.some((p) => path === p || path.startsWith(p));
}

/**
 * Tratamiento ÚNICO de las respuestas de la API. Ante un 401 de la aplicación
 * avisa al vigilante de sesión (que cierra la interfaz y lleva al login) y deja
 * la promesa pendiente: la pantalla se está desmontando y no debe pintar un
 * error «No autenticado» sobre una interfaz que parece abierta.
 */
async function comprobar(path: string, res: Response): Promise<void> {
  if (res.ok) {
    if (!esRutaDeAcceso(path)) alHaberActividad?.();
    return;
  }
  let detail = `Error ${res.status}`;
  let code: string | undefined;
  try {
    const data = await res.json();
    if (typeof data?.detail === "string") detail = data.detail;
    if (typeof data?.code === "string") code = data.code;
  } catch {
    /* sin cuerpo JSON */
  }
  if (res.status === 401 && !esRutaDeAcceso(path) && alExpirar) {
    alExpirar();
    await new Promise<never>(() => {});
  }
  throw new ApiError(res.status, detail, code);
}

// Token CSRF de la sesión actual, refrescado por cada lectura de /session.
let csrfToken = "";
export function setCsrf(token: string) {
  csrfToken = token;
}
export function getCsrf() {
  return csrfToken;
}

const BASE = "/api/web";

// Cuerpo de crear/editar de un activo restringible (servidor, hipervisor,
// dispositivo). `restringido` solo viaja cuando el caller (el formulario) lo
// definió — es decir, cuando el usuario es administrador. Para el resto de roles
// el formulario lo deja sin definir y el campo se omite del JSON (el backend lo
// ignoraría de todos modos).
function cuerpoActivo<T extends { restringido?: boolean }>(b: T): Record<string, unknown> {
  const cuerpo: Record<string, unknown> = { ...b };
  if (b.restringido === undefined) delete cuerpo.restringido;
  return cuerpo;
}

type Opts = {
  method?: string;
  body?: unknown;
  csrf?: boolean; // adjunta X-CSRF-Token con el token de sesión
  csrfValor?: string; // adjunta X-CSRF-Token con un token explícito (p. ej. el del desafío de recuperación)
  raw?: boolean; // devuelve el Response sin parsear
};

async function request<T>(path: string, opts: Opts = {}): Promise<T> {
  const { method = "GET", body, csrf = false, csrfValor, raw = false } = opts;
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (csrf) headers["X-CSRF-Token"] = csrfToken;
  if (csrfValor !== undefined) headers["X-CSRF-Token"] = csrfValor;

  const res = await fetch(`${BASE}${path}`, {
    method,
    headers,
    credentials: "include",
    cache: "no-store",
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (raw) return res as unknown as T;

  await comprobar(path, res);
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

// --- Sesión / autenticación ---
export const api = {
  csrfLogin: () => request<{ csrf_login: string }>("/csrf"),
  login: (username: string, password: string, csrf_login: string) =>
    request<{ stage: string; next: string }>("/login", {
      method: "POST",
      body: { username, password, csrf_login },
    }),
  session: () => request<SessionState>("/session"),
  extenderSesion: () =>
    request<{ ok: boolean; sesion: PlazosSesion }>("/session/extender", { method: "POST", csrf: true }),
  // --- Auto-recuperación de contraseña (3 pasos, CSRF del desafío) ---
  recuperarIniciar: (username: string, email: string, csrf_login: string) =>
    request<{ ok: boolean; csrf: string }>("/password/recuperar/iniciar", {
      method: "POST",
      body: { username, email, csrf_login },
    }),
  recuperarVerificar: (codigo: string, csrfDesafio: string) =>
    request<{ ok: boolean }>("/password/recuperar/verificar", {
      method: "POST",
      body: { codigo },
      csrfValor: csrfDesafio,
    }),
  recuperarCambiar: (password_nueva: string, password_confirmacion: string, csrfDesafio: string) =>
    request<{ ok: boolean; next: string }>("/password/recuperar/cambiar", {
      method: "POST",
      body: { password_nueva, password_confirmacion },
      csrfValor: csrfDesafio,
    }),
  cambiarPassword: (b: {
    password_actual: string;
    password_nueva: string;
    password_confirmacion: string;
  }) => request<{ stage?: string; next?: string; ok?: boolean }>("/password/cambiar", {
    method: "POST",
    body: b,
    csrf: true,
  }),
  // --- Verificación en dos pasos: alta (elección de método) y acceso ---
  mfaMetodosAlta: () => request<MetodosAltaMfa>("/mfa/configurar/metodos"),
  mfaConfigurar: () => request<{ qr_data_uri: string; secreto: string }>("/mfa/configurar"),
  mfaConfirmar: (codigo: string) =>
    request<{ codigos_recuperacion: string[] }>("/mfa/configurar", {
      method: "POST",
      body: { codigo },
      csrf: true,
    }),
  mfaAltaCorreoEnviar: () =>
    request<EnvioCodigoCorreo>("/mfa/configurar/correo/enviar", { method: "POST", csrf: true }),
  mfaAltaCorreoConfirmar: (codigo: string) =>
    request<{ codigos_recuperacion: string[] }>("/mfa/configurar/correo", {
      method: "POST",
      body: { codigo },
      csrf: true,
    }),
  mfaMetodos: () => request<MetodosAccesoMfa>("/mfa/metodos"),
  mfaPedirCodigoCorreo: () =>
    request<EnvioCodigoCorreo>("/mfa/otp-correo", { method: "POST", csrf: true }),
  mfaVerificar: (codigo: string) =>
    request<{ ok: boolean; aviso?: string; stage?: string; next?: string }>("/mfa/verificar", {
      method: "POST",
      body: { codigo },
      csrf: true,
    }),

  // --- Mi seguridad (gestión del segundo factor por el propio usuario) ---
  seguridad: () => request<SeguridadCuenta>("/cuenta/seguridad"),
  seguridadEnviarCodigo: () =>
    request<EnvioCodigoCorreo>("/cuenta/mfa/correo/enviar", { method: "POST", csrf: true }),
  seguridadActivarCorreo: (password: string, codigo: string) =>
    request<SeguridadCuenta>("/cuenta/mfa/correo/activar", {
      method: "POST",
      body: { password, codigo },
      csrf: true,
    }),
  seguridadIniciarTotp: (password: string) =>
    request<{ qr_data_uri: string; secreto: string }>("/cuenta/mfa/totp/iniciar", {
      method: "POST",
      body: { password },
      csrf: true,
    }),
  seguridadActivarTotp: (codigo: string) =>
    request<SeguridadCuenta>("/cuenta/mfa/totp/activar", {
      method: "POST",
      body: { codigo },
      csrf: true,
    }),
  seguridadRegenerarCodigos: (password: string, codigo: string) =>
    request<{ codigos_recuperacion: string[] }>("/cuenta/mfa/codigos", {
      method: "POST",
      body: { password, codigo },
      csrf: true,
    }),
  logout: () => request<{ ok: boolean }>("/logout", { method: "POST", csrf: true }),

  // --- Inventario ---
  dashboard: () => request<Dashboard>("/dashboard"),
  servidor: (id: number) => request<ServidorDetalle>(`/servidores/${id}`),
  crearServidor: (b: ServidorInput) =>
    request<{ id: number }>("/servidores", { method: "POST", body: cuerpoActivo(b), csrf: true }),
  editarServidor: (id: number, b: ServidorInput) =>
    request<{ id: number }>(`/servidores/${id}`, { method: "PUT", body: cuerpoActivo(b), csrf: true }),
  eliminarServidor: (id: number) =>
    request<{ ok: boolean }>(`/servidores/${id}`, { method: "DELETE", csrf: true }),

  hipervisor: (id: number) => request<HipervisorDetalle>(`/hipervisores/${id}`),
  crearHipervisor: (b: HipervisorInput) =>
    request<{ id: number }>("/hipervisores", { method: "POST", body: cuerpoActivo(b), csrf: true }),
  editarHipervisor: (id: number, b: HipervisorInput) =>
    request<{ id: number }>(`/hipervisores/${id}`, { method: "PUT", body: cuerpoActivo(b), csrf: true }),
  eliminarHipervisor: (id: number) =>
    request<{ ok: boolean }>(`/hipervisores/${id}`, { method: "DELETE", csrf: true }),

  dispositivoDetalle: (id: number) => request<DispositivoDetalle>(`/dispositivos/${id}`),
  crearDispositivo: (b: DispositivoInput) =>
    request<{ id: number }>("/dispositivos", { method: "POST", body: cuerpoActivo(b), csrf: true }),
  editarDispositivo: (id: number, b: DispositivoInput) =>
    request<{ id: number }>(`/dispositivos/${id}`, { method: "PUT", body: cuerpoActivo(b), csrf: true }),
  eliminarDispositivo: (id: number) =>
    request<{ ok: boolean }>(`/dispositivos/${id}`, { method: "DELETE", csrf: true }),

  vm: (id: number) => request<VmDetalle>(`/vms/${id}`),
  crearVm: (hipervisorId: number, b: VmInput) =>
    request<{ id: number }>(`/hipervisores/${hipervisorId}/vms`, {
      method: "POST",
      body: b,
      csrf: true,
    }),
  editarVm: (id: number, b: VmInput) =>
    request<{ id: number }>(`/vms/${id}`, { method: "PUT", body: b, csrf: true }),
  eliminarVm: (id: number) =>
    request<{ ok: boolean; hipervisor_id: number }>(`/vms/${id}`, { method: "DELETE", csrf: true }),

  // --- Credenciales ---
  credencial: (id: number) => request<CredencialDetalle>(`/credenciales/${id}`),
  crearCredencial: (b: { activo: TipoActivo; activo_id: number } & CredencialInput) =>
    request<{ id: number }>("/credenciales", { method: "POST", body: b, csrf: true }),
  editarCredencial: (id: number, b: CredencialInput) =>
    request<{ id: number }>(`/credenciales/${id}`, { method: "PUT", body: b, csrf: true }),
  eliminarCredencial: (id: number) =>
    request<{ ok: boolean }>(`/credenciales/${id}`, { method: "DELETE", csrf: true }),
  revelarCredencial: (id: number) =>
    request<{ usuario: string; password: string }>(`/credenciales/${id}/revelar`, {
      method: "POST",
      csrf: true,
    }),
  copiarCredencial: (id: number) =>
    request<{ usuario: string; password: string }>(`/credenciales/${id}/copiar`, {
      method: "POST",
      csrf: true,
    }),
  revelarHistorial: (id: number, hid: number) =>
    request<{ password: string }>(`/credenciales/${id}/historial/${hid}/revelar`, {
      method: "POST",
      csrf: true,
    }),

  // --- Vault personal (privado del usuario) ---
  vault: () => request<{ entradas: VaultEntrada[] }>("/vault"),
  vaultEntrada: (id: number) => request<VaultEntrada>(`/vault/${id}`),
  crearVault: (b: VaultInput) =>
    request<{ id: number }>("/vault", { method: "POST", body: b, csrf: true }),
  editarVault: (id: number, b: VaultInput) =>
    request<{ id: number }>(`/vault/${id}`, { method: "PUT", body: b, csrf: true }),
  eliminarVault: (id: number) =>
    request<{ ok: boolean }>(`/vault/${id}`, { method: "DELETE", csrf: true }),
  revelarVault: (id: number) =>
    request<{ usuario: string; password: string }>(`/vault/${id}/revelar`, { method: "POST", csrf: true }),
  copiarVault: (id: number) =>
    request<{ usuario: string; password: string }>(`/vault/${id}/copiar`, { method: "POST", csrf: true }),

  // --- Migración: export en claro (descarga blob) y plantilla ---
  exportarInventario: async (): Promise<Blob> => {
    const res = await fetch(`${BASE}/exportar`, {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken },
      credentials: "include",
      cache: "no-store",
    });
    await comprobar("/exportar", res);
    return res.blob();
  },
  plantillaUrl: () => `${BASE}/plantilla.csv`,

  // --- Búsqueda ---
  buscar: (q: string) => request<ResultadoBusqueda>(`/buscar?q=${encodeURIComponent(q)}`),

  // --- Accesos ---
  conceder: (b: { usuario_id: number; tipo: TipoActivo; activo_id: number; nivel: NivelAcceso; expira_dias?: number | null }) =>
    request<{ ok: boolean }>("/accesos/conceder", { method: "POST", body: b, csrf: true }),
  revocarAcceso: (id: number) =>
    request<{ ok: boolean }>(`/accesos/${id}/revocar`, { method: "POST", csrf: true }),

  // --- Notas ---
  notasEstado: (tipo: TipoActivo, id: number) =>
    request<{ tiene_notas: boolean }>(`/activos/${tipo}/${id}/notas`),
  guardarNotas: (tipo: TipoActivo, id: number, contenido: string) =>
    request<{ ok: boolean }>(`/activos/${tipo}/${id}/notas`, { method: "PUT", body: { contenido }, csrf: true }),
  revelarNotas: (tipo: TipoActivo, id: number) =>
    request<{ notas: string }>(`/activos/${tipo}/${id}/notas/revelar`, { method: "POST", csrf: true }),

  // --- Usuarios ---
  usuarios: () => request<{ usuarios: Usuario[] }>("/usuarios"),
  crearUsuario: (b: { username: string; email: string; nombre_completo: string; rol: string }) =>
    request<{ username: string; password_temporal: string }>("/usuarios", { method: "POST", body: b, csrf: true }),
  desactivarUsuario: (id: number) =>
    request<{ ok: boolean }>(`/usuarios/${id}/desactivar`, { method: "POST", csrf: true }),
  reactivarUsuario: (id: number) =>
    request<{ ok: boolean }>(`/usuarios/${id}/reactivar`, { method: "POST", csrf: true }),
  resetPassword: (id: number) =>
    request<{
      username: string;
      /** `true`: la contraseña temporal viajó al correo del usuario y NO se devuelve. */
      correo_enviado: boolean;
      destino: string | null;
      /** Solo si el correo no salió (contingencia). */
      password_temporal?: string;
      aviso?: string;
    }>(`/usuarios/${id}/reset-password`, {
      method: "POST",
      csrf: true,
    }),
  resetMfa: (id: number) => request<{ ok: boolean }>(`/usuarios/${id}/reset-mfa`, { method: "POST", csrf: true }),
  cambiarRol: (id: number, rol: string) =>
    request<{ ok: boolean }>(`/usuarios/${id}/rol`, { method: "POST", body: { rol }, csrf: true }),

  // --- Tokens API ---
  tokens: () => request<{ tokens: TokenApi[] }>("/tokens"),
  crearToken: (b: { nombre: string; alcance: string; dias_validez: number }) =>
    request<{ token: string }>("/tokens", { method: "POST", body: b, csrf: true }),
  revocarToken: (id: number) => request<{ ok: boolean }>(`/tokens/${id}/revocar`, { method: "POST", csrf: true }),

  // --- Auditoría ---
  auditoria: (p: { filtro_usuario?: string; filtro_accion?: string; pagina?: number }) => {
    const qs = new URLSearchParams();
    if (p.filtro_usuario) qs.set("filtro_usuario", p.filtro_usuario);
    if (p.filtro_accion) qs.set("filtro_accion", p.filtro_accion);
    if (p.pagina) qs.set("pagina", String(p.pagina));
    return request<AuditoriaPagina>(`/auditoria?${qs.toString()}`);
  },
  auditoriaExportUrl: (p: { filtro_usuario?: string; filtro_accion?: string }) => {
    const qs = new URLSearchParams();
    if (p.filtro_usuario) qs.set("filtro_usuario", p.filtro_usuario);
    if (p.filtro_accion) qs.set("filtro_accion", p.filtro_accion);
    return `${BASE}/auditoria/export.csv?${qs.toString()}`;
  },

  // --- Métricas ---
  metricas: () => request<Metricas>("/metricas"),

  // --- Configuración del sistema (solo administradores) ---
  configuracion: () => request<ConfiguracionResp>("/configuracion"),
  // Envía valores nativos: number (entero), boolean (booleano), string
  // (texto/secreto). Un secreto solo debe incluirse si el usuario escribió uno
  // nuevo (ausencia/vacío = «no cambiar»).
  guardarConfiguracion: (cambios: Record<string, unknown>) =>
    request<{ modificadas: string[] }>("/configuracion", {
      method: "PUT",
      body: { cambios },
      csrf: true,
    }),
  restablecerAjuste: (clave: string) =>
    request<{ restablecido: boolean }>("/configuracion/restablecer", {
      method: "POST",
      body: { clave },
      csrf: true,
    }),
  // `destinatario` opcional: si va vacío, el backend usa la lista configurada.
  probarCorreo: (destinatario: string) =>
    request<{ ok: boolean; destinatarios: number; aviso?: string }>("/configuracion/probar-correo", {
      method: "POST",
      body: { destinatario },
      csrf: true,
    }),
  // Comprueba conexión y autenticación con los valores del formulario, SIN
  // guardarlos ni enviar ningún mensaje.
  probarConexionSmtp: (valores: Record<string, unknown>) =>
    request<{ ok: boolean; detalle: string }>("/configuracion/probar-conexion", {
      method: "POST",
      body: { valores },
      csrf: true,
    }),

  // --- Importación ---
  importar: async (archivo: File): Promise<ResultadoImportacion> => {
    const fd = new FormData();
    fd.append("archivo", archivo);
    const res = await fetch(`${BASE}/importar`, {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken },
      credentials: "include",
      cache: "no-store",
      body: fd,
    });
    await comprobar("/importar", res);
    return res.json();
  },
};

export type { Concesion };
