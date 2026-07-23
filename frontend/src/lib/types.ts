// Tipos del dominio — espejo del contrato JSON (`/api/web`). Ver API_CONTRACT.md.

export type Rol = "admin" | "operador" | "auditor" | "analista";
export type EstadoActivo = "activo" | "mantenimiento" | "retirado";
export type TipoActivo = "fisico" | "hipervisor" | "vm" | "dispositivo";
export type TipoDispositivo =
  | "switch"
  | "router"
  | "firewall"
  | "access_point"
  | "balanceador"
  | "otro";
export type NivelAcceso = "ver" | "ver_credenciales";
export type Etapa = "cambio_password" | "mfa_enrolamiento" | "mfa_pendiente" | "activa";

export type Permiso =
  | "inventario.ver"
  | "inventario.gestionar"
  | "inventario.exportar"
  | "credenciales.ver_lista"
  | "credenciales.revelar"
  | "credenciales.gestionar"
  | "vault.usar"
  | "usuarios.gestionar"
  | "auditoria.ver"
  | "metricas.ver"
  | "accesos.gestionar"
  | "tokens.gestionar";

export interface Usuario {
  id: number;
  username: string;
  email: string;
  nombre_completo: string;
  rol: Rol;
  rol_label: string;
  mfa_habilitado: boolean;
  activo: boolean;
  ultimo_acceso: string | null;
}

export interface SessionState {
  authenticated: boolean;
  stage: Etapa | null;
  csrf_token: string;
  usuario?: Usuario;
  permisos?: Record<Permiso, boolean>;
}

export interface Credencial {
  id: number;
  usuario_acceso: string;
  servicio: string;
  puerto: number | null;
  descripcion: string;
  dias_sin_rotar: number;
  rotacion_vencida: boolean;
  puede_revelar: boolean;
  tipo_activo: TipoActivo;
  activo_id: number;
}

export interface VmNodo {
  id: number;
  nombre: string;
  sistema_operativo: string;
  estado: EstadoActivo;
  credenciales: Credencial[];
}

export interface HipervisorNodo {
  id: number;
  nombre: string;
  plataforma: string;
  estado: EstadoActivo;
  ip_gestion: string;
  etiquetas: string[];
  credenciales: Credencial[];
  vms: VmNodo[];
}

export interface ServidorNodo {
  id: number;
  nombre: string;
  estado: EstadoActivo;
  ip_gestion: string;
  etiquetas: string[];
  credenciales: Credencial[];
}

export interface DispositivoNodo {
  id: number;
  nombre: string;
  tipo_dispositivo: TipoDispositivo;
  tipo_dispositivo_label: string;
  estado: EstadoActivo;
  ip_gestion: string;
  etiquetas: string[];
  credenciales: Credencial[];
}

export interface Resumen {
  servidores: number;
  hipervisores: number;
  vms: number;
  dispositivos: number;
  credenciales: number;
  rotacion_vencida: number;
}

export interface Concesion {
  id: number;
  usuario_id: number;
  username: string;
  nombre_completo: string;
  nivel: NivelAcceso;
  nivel_label: string;
  expira_en: string | null;
  expirada: boolean;
  tipo: TipoActivo;
  activo_id: number;
  activo_nombre: string;
}

export interface DashboardAdmin {
  es_analista: false;
  resumen: Resumen;
  servidores: ServidorNodo[];
  hipervisores: HipervisorNodo[];
  dispositivos: DispositivoNodo[];
}
export interface DashboardAnalista {
  es_analista: true;
  concesiones: Concesion[];
}
export type Dashboard = DashboardAdmin | DashboardAnalista;

export interface AnalistaRef {
  id: number;
  username: string;
  nombre_completo: string;
}

export interface ServidorInput {
  nombre: string;
  descripcion: string;
  sistema_operativo: string;
  marca_modelo: string;
  ubicacion: string;
  ip_gestion: string;
  ram: string;
  cpu: string;
  almacenamiento: string;
  numero_serie: string;
  garantia_hasta: string;
  proveedor: string;
  estado: EstadoActivo;
  etiquetas: string;
}

export interface ServidorDetalle extends ServidorInput {
  id: number;
  lista_etiquetas: string[];
  credenciales: Credencial[];
  puede_gestionar: boolean;
  puede_gestionar_accesos: boolean;
  tiene_notas: boolean;
  accesos?: Concesion[];
  analistas?: AnalistaRef[];
}

export interface HipervisorInput {
  nombre: string;
  plataforma: string;
  version: string;
  ip_gestion: string;
  descripcion: string;
  marca_modelo: string;
  ubicacion: string;
  ram: string;
  cpu: string;
  almacenamiento: string;
  numero_serie: string;
  garantia_hasta: string;
  proveedor: string;
  estado: EstadoActivo;
  etiquetas: string;
}

export interface HipervisorDetalle extends HipervisorInput {
  id: number;
  lista_etiquetas: string[];
  credenciales: Credencial[];
  vms: { id: number; nombre: string; sistema_operativo: string; estado: EstadoActivo }[];
  puede_gestionar: boolean;
  puede_gestionar_accesos: boolean;
  tiene_notas: boolean;
  accesos?: Concesion[];
  analistas?: AnalistaRef[];
}

export interface VmInput {
  nombre: string;
  sistema_operativo: string;
  ip: string;
  descripcion: string;
  ram: string;
  cpu: string;
  almacenamiento: string;
  estado: EstadoActivo;
  etiquetas: string;
}

export interface VmDetalle extends VmInput {
  id: number;
  hipervisor_id: number;
  hipervisor_nombre: string;
  credenciales: Credencial[];
  puede_gestionar: boolean;
  puede_gestionar_accesos: boolean;
  tiene_notas: boolean;
  accesos?: Concesion[];
  analistas?: AnalistaRef[];
}

export interface DispositivoInput {
  nombre: string;
  tipo_dispositivo: TipoDispositivo;
  marca_modelo: string;
  version: string; // firmware / versión
  ip_gestion: string;
  ubicacion: string;
  puertos: string; // texto libre
  descripcion: string;
  numero_serie: string;
  garantia_hasta: string;
  proveedor: string;
  estado: EstadoActivo;
  etiquetas: string;
}

export interface DispositivoDetalle extends DispositivoInput {
  id: number;
  tipo_dispositivo_label: string;
  lista_etiquetas: string[];
  credenciales: Credencial[];
  puede_gestionar: boolean;
  puede_gestionar_accesos: boolean;
  tiene_notas: boolean;
  accesos?: Concesion[];
  analistas?: AnalistaRef[];
}

export interface CredencialInput {
  usuario_acceso: string;
  password: string;
  servicio: string;
  puerto: number | null;
  descripcion: string;
}

export interface HistorialEntrada {
  id: number;
  rotada_en: string;
  rotada_por: string;
}

export interface CredencialDetalle {
  id: number;
  usuario_acceso: string;
  servicio: string;
  puerto: number | null;
  descripcion: string;
  tipo_activo: TipoActivo;
  activo_id: number;
  activo_nombre: string;
  historial: HistorialEntrada[];
}

export interface ResultadoBusqueda {
  q: string;
  servidores: { id: number; nombre: string; ip_gestion: string; ubicacion: string; estado: EstadoActivo }[];
  hipervisores: { id: number; nombre: string; plataforma: string; ip_gestion: string; estado: EstadoActivo }[];
  vms: { id: number; nombre: string; ip: string; sistema_operativo: string; estado: EstadoActivo }[];
  dispositivos: {
    id: number;
    nombre: string;
    tipo_dispositivo: TipoDispositivo;
    tipo_dispositivo_label: string;
    ip_gestion: string;
    estado: EstadoActivo;
  }[];
  credenciales: Credencial[];
}

export type TokenAlcance = "todo" | "auditoria" | "inventario";

export interface TokenApi {
  id: number;
  nombre: string;
  alcance: TokenAlcance;
  creado_en: string;
  expira_en: string | null;
  caducado: boolean;
  ultimo_uso: string | null;
  activo: boolean;
  creado_por: string;
}

export interface RegistroAuditoria {
  id: number;
  fecha: string;
  usuario: string;
  accion: string;
  objeto_tipo: string;
  objeto_id: string;
  detalle: string;
  direccion_ip: string;
  agente_usuario: string;
  exito: boolean;
}

export interface AuditoriaPagina {
  registros: RegistroAuditoria[];
  pagina: number;
  total_paginas: number;
  acciones: string[];
  filtro_usuario: string;
  filtro_accion: string;
}

export interface Metricas {
  rotacion_vencida: { id: number; activo: string; tipo: TipoActivo; usuario_acceso: string; dias: number }[];
  logins_fallidos_24h: number;
  logins_fallidos_7d: number;
  bloqueados: { username: string; bloqueado_hasta: string }[];
  sin_mfa: { username: string; rol: string }[];
  top_accesos: { username: string; accesos: number }[];
  concesiones_por_caducar: Concesion[];
}

export interface ResultadoImportacion {
  creados: { servidor: number; hipervisor: number; vm: number; credencial: number };
  errores: string[];
  total: number;
}

// Vault personal (privado de cada usuario).
export type CategoriaVault = "servicio" | "aplicacion" | "cuenta" | "otro";

export interface VaultEntrada {
  id: number;
  titulo: string;
  usuario_acceso: string;
  url: string;
  categoria: CategoriaVault;
  notas: string;
  dias_sin_rotar: number;
  rotacion_vencida: boolean;
}

export interface VaultInput {
  titulo: string;
  usuario_acceso: string;
  password: string;
  url: string;
  categoria: CategoriaVault;
  notas: string;
}
