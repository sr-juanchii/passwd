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
  | "rotacion.ver"
  | "rotacion.solicitar"
  | "rotacion.autorizar"
  | "rotacion.revisar"
  | "agentes.ver"
  | "agentes.gestionar"
  | "accesos.gestionar"
  | "tokens.gestionar"
  | "configuracion.gestionar";

export interface Usuario {
  id: number;
  username: string;
  email: string;
  nombre_completo: string;
  rol: Rol;
  rol_label: string;
  mfa_habilitado: boolean;
  mfa_metodo?: MetodoMfa;
  activo: boolean;
  ultimo_acceso: string | null;
}

export interface SessionState {
  authenticated: boolean;
  stage: Etapa | null;
  csrf_token: string;
  usuario?: Usuario;
  permisos?: Record<Permiso, boolean>;
  /** Plazos de expiración (solo con sesión activa). */
  sesion?: import("./expiracion").PlazosSesion;
  /** Longitud mínima vigente de las contraseñas de usuario. */
  password_min_length?: number;
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
  // Restringido a administradores: los operadores no reciben este nodo (ni sus
  // VMs) del backend; admin y auditor sí, para distinguirlo en el listado.
  restringido?: boolean;
}

export interface ServidorNodo {
  id: number;
  nombre: string;
  estado: EstadoActivo;
  ip_gestion: string;
  etiquetas: string[];
  credenciales: Credencial[];
  restringido?: boolean;
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
  restringido?: boolean;
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
  // Marca "restringido a administradores". Solo la envían los administradores al
  // crear/editar; el backend la ignora para el resto de roles.
  restringido?: boolean;
}

export interface ServidorDetalle extends ServidorInput {
  id: number;
  lista_etiquetas: string[];
  credenciales: Credencial[];
  puede_gestionar: boolean;
  puede_gestionar_accesos: boolean;
  // true solo para administradores: habilita el control de restricción.
  puede_restringir?: boolean;
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
  restringido?: boolean;
}

export interface HipervisorDetalle extends HipervisorInput {
  id: number;
  lista_etiquetas: string[];
  credenciales: Credencial[];
  vms: { id: number; nombre: string; sistema_operativo: string; estado: EstadoActivo }[];
  puede_gestionar: boolean;
  puede_gestionar_accesos: boolean;
  puede_restringir?: boolean;
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
  restringido?: boolean;
}

export interface DispositivoDetalle extends DispositivoInput {
  id: number;
  tipo_dispositivo_label: string;
  lista_etiquetas: string[];
  credenciales: Credencial[];
  puede_gestionar: boolean;
  puede_gestionar_accesos: boolean;
  puede_restringir?: boolean;
  tiene_notas: boolean;
  accesos?: Concesion[];
  analistas?: AnalistaRef[];
}

export interface CredencialInput {
  usuario_acceso: string;
  /** Vacío al editar = conservar la actual. Cambiarla exige rotación autorizada. */
  password: string;
  servicio: string;
  puerto: number | null;
  descripcion: string;
  usada_por: string;
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
  /** Servicios y automatismos que consumen esta cuenta. */
  usada_por: string;
  via_rotacion: ViaRotacion;
  tipo_activo: TipoActivo;
  activo_id: number;
  activo_nombre: string;
  dias_sin_rotar?: number;
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
  gobernanza_rotacion?: {
    pendientes_de_autorizar: number;
    pendientes_de_ejecutar: number;
    revisiones_pendientes: number;
  };
  patrones_rotacion?: ResumenPatrones;
  /** Agentes de rotación (v1.4.0); null con los agentes apagados. */
  agentes?: MetricasAgentes | null;
}

export interface MetricasAgentes {
  por_cobertura: Record<"conectado" | "sin_contacto" | "caducado" | "pendiente", number>;
  atencion: {
    id: number;
    nombre: string;
    activo: string;
    tipo_activo: TipoActivoAgente;
    activo_id: number;
    cobertura: CoberturaAgente;
    ultimo_contacto_en: string | null;
  }[];
  sin_confirmar: number;
}

// --- Gobernanza de rotación (v1.3.0) -------------------------------------
//
// Una rotación no es un cambio de contraseña: es un expediente. Se solicita con
// un motivo, la autoriza OTRA persona y solo entonces se puede registrar la
// contraseña que quedó aplicada en el activo.

export type EstadoRotacion =
  | "solicitada"
  | "autorizada"
  | "despachada"
  | "cerrada"
  | "rechazada"
  | "cancelada"
  | "expirada";

export type TipoRotacion = "programada" | "manual" | "emergencia" | "masiva";
export type ViaRotacion = "manual" | "agente" | "conector";
export type VerificacionRotacion = "ninguna" | "local" | "remota";

export interface RotacionAsiento {
  id: number;
  credencial_id: number | null;
  activo_nombre: string;
  usuario_acceso: string;
  servicio: string;
  estado: EstadoRotacion;
  tipo: TipoRotacion;
  motivo: string;
  solicitado_por: string;
  solicitado_en: string;
  dias_al_solicitar: number | null;
  dias_al_autorizar: number | null;
  /** Muy por debajo de la vigencia: exige motivo reforzado. */
  temprana: boolean;
  autorizado_por: string;
  autorizado_en: string | null;
  reautenticado: boolean;
  /** Autorizada por su propio solicitante en la vía de emergencia. */
  emergencia_sin_segundo_par: boolean;
  revision_pendiente: boolean;
  revisada_en: string | null;
  nota_revision: string;
  motivo_rechazo: string;
  fecha_programada: string | null;
  confirmado_en: string | null;
  dias_al_rotar: number | null;
  /** Días de adelanto (negativo) o retraso respecto a la política. */
  desvio_dias: number | null;
  resultado: string;
  via: ViaRotacion;
  verificacion: VerificacionRotacion;
  detalle_error: string;
  /** Agente que la ejecutó (vacío si fue a mano). */
  agente_nombre: string;
}

export interface SenalPatron {
  regla: string;
  etiqueta: string;
  descripcion: string;
  casos: number;
  severidad: "informativo" | "aviso" | "grave";
}

export interface ResumenPatrones {
  /** Las reglas se evalúan y se ven, pero todavía no notifican. */
  modo_observacion: boolean;
  ventana_dias: number;
  senales: SenalPatron[];
}

export interface PoliticaRotacion {
  intervalo_dias: number;
  umbral_temprana_dias: number;
  motivo_min: number;
  motivo_reforzado_min: number;
}

export interface EstadoGobernanza {
  administradores_activos: number;
  minimo_administradores: number;
  /** Con un solo administrador la regla de dos pares no se puede aplicar. */
  dos_pares_posible: boolean;
}

export interface PanelRotacion {
  /** Trabajos que un agente recogió y nunca confirmó: alguien debe decir qué quedó. */
  sin_confirmar: TrabajoAgente[];
  gobernanza: EstadoGobernanza;
  pendientes_de_autorizar: RotacionAsiento[];
  pendientes_de_ejecutar: RotacionAsiento[];
  revisiones_pendientes: RotacionAsiento[];
  politica: PoliticaRotacion;
  patrones: ResumenPatrones;
}

export interface RotacionDeCredencial {
  credencial_id: number;
  activo_nombre: string;
  usuario_acceso: string;
  via_rotacion: ViaRotacion;
  usada_por: string;
  dias_sin_rotar: number;
  fecha_programada: string;
  temprana_si_se_rota_ahora: boolean;
  solicitud_abierta: RotacionAsiento | null;
  /** Si la solicitud abierta está en manos de un agente, su trabajo. */
  trabajo_en_curso: TrabajoAgente | null;
  historial: RotacionAsiento[];
}

// --- Agentes de rotación (v1.4.0) -----------------------------------------
//
// Un agente instalado en el servidor aplica las rotaciones YA autorizadas: la
// regla de dos personas no cambia. La cobertura se deriva de las fechas en el
// servidor; la interfaz solo la nombra.

export type CoberturaAgente = "sin_agente" | "pendiente" | "conectado" | "sin_contacto" | "caducado";
export type EstadoAgente = "pendiente" | "activo" | "revocado";
export type TipoActivoAgente = "fisico" | "hipervisor" | "vm";

export interface TrabajoAgente {
  id: number;
  rotacion_id: number;
  credencial_id: number;
  estado: "pendiente" | "entregado" | "aplicado" | "revertido" | "fallado" | "expirado" | "cancelado";
  agente: string;
  activo_nombre: string;
  usuario_acceso: string;
  ventana_expira_en: string;
  entregado_en: string | null;
  intentos: number;
  /** El agente lo recogió y no informó: la contraseña pudo cambiar o no. */
  sin_confirmar: boolean;
}

export interface Agente {
  id: number;
  nombre: string;
  estado: EstadoAgente;
  cobertura: CoberturaAgente;
  activo: { tipo: TipoActivoAgente; id: number; nombre: string };
  nombre_host: string;
  version_agente: string;
  version_admitida: boolean;
  version_en_gracia: boolean;
  ultimo_contacto_en: string | null;
  ip_ultimo_contacto: string;
  token_expira_en: string | null;
  enrolado_en: string | null;
  enrolamiento_expira_en: string | null;
  clave_huella: string;
  rotacion_habilitada: boolean;
  creado_en: string | null;
  revocado_en: string | null;
  trabajo_en_curso: {
    id: number;
    estado: string;
    rotacion_id: number;
    usuario_acceso: string;
    ventana_expira_en: string | null;
    sin_confirmar: boolean;
  } | null;
  telemetria: {
    fecha: string | null;
    cpu_pct: number | null;
    ram_pct: number | null;
    disco_pct: number | null;
    uptime_s: number | null;
    sistema_operativo: string;
    kernel: string;
    recortada: boolean;
  } | null;
}

export interface ListaAgentes {
  /** Interruptor general de los agentes (configuración). */
  habilitados: boolean;
  agentes: Agente[];
}

export interface CoberturaActivo {
  cobertura: CoberturaAgente;
  /** Los dispositivos de red no admiten agente. */
  admite_agente: boolean;
  agente: Agente | null;
}

export interface TokenInstalacion {
  agente: Agente;
  /** Se muestra UNA vez: el servidor solo guarda su hash. */
  token_enrolamiento: string;
  token_expira_en: string | null;
}

export interface ResultadoLote {
  autorizadas: RotacionAsiento[];
  rechazadas: { id: number; motivo: string }[];
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

// Configuración del sistema en tiempo de ejecución (solo administradores).
export type TipoAjuste = "entero" | "booleano" | "texto" | "secreto" | "opcion";
export type OrigenAjuste = "configurado" | "entorno" | "defecto";

export interface AjusteConfig {
  clave: string;
  etiqueta: string;
  ayuda: string;
  tipo: TipoAjuste;
  minimo: number | null;
  maximo: number | null;
  /** Unidad del valor (min, h, días…), para mostrarla junto al campo. */
  unidad: string;
  /** Valores admitidos por un ajuste de tipo «opcion». */
  opciones: { valor: string; etiqueta: string }[];
  /** Ajustes que deben estar activos para que este surta efecto. */
  depende_de: { clave: string; etiqueta: string }[];
  origen: OrigenAjuste;
  // Los ajustes NO secretos traen `valor` (number|boolean|string según `tipo`).
  valor?: number | boolean | string;
  // Los secretos NO traen `valor`; solo `configurado` indica si hay uno guardado.
  configurado?: boolean;
}

export interface GrupoConfig {
  grupo: string;
  descripcion: string;
  ajustes: AjusteConfig[];
}

/** Qué depende del correo y si está operativo (panel «Estado del correo»). */
export interface EstadoCorreo {
  operativo: boolean;
  motivo: string;
  avisos: string[];
  funciones: { nombre: string; activa: boolean; detalle: string }[];
}

export interface InfoSistemaItem {
  etiqueta: string;
  valor: string | number;
}

export interface ConfiguracionResp {
  grupos: GrupoConfig[];
  info_sistema: InfoSistemaItem[];
  correo: EstadoCorreo;
}

// --- Verificación en dos pasos ---
export type MetodoMfa = "totp" | "correo";

export interface MetodosAltaMfa {
  metodos: MetodoMfa[];
  correo: { disponible: boolean; destino: string; motivo: string };
  /** La cuenta se enroló por correo y ahora debe pasar a aplicación autenticadora. */
  obligado_totp: boolean;
}

export interface MetodosAccesoMfa {
  principal: MetodoMfa;
  totp: boolean;
  codigos_recuperacion: boolean;
  otp_correo: boolean;
  destino: string;
}

export interface EnvioCodigoCorreo {
  ok: boolean;
  destino: string;
  vigencia_minutos: number;
}

export interface SeguridadCuenta {
  metodo: MetodoMfa;
  codigos_restantes: number;
  destino: string;
  puede_cambiar_a_correo: boolean;
  motivo_correo: string;
  puede_cambiar_a_totp: boolean;
  correo_operativo: boolean;
}
