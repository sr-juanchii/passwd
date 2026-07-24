import type {
  CategoriaVault,
  EstadoActivo,
  NivelAcceso,
  Rol,
  TipoActivo,
  TipoDispositivo,
} from "./types";

export const ETIQUETAS_ROL: Record<Rol, string> = {
  admin: "Administrador",
  operador: "Operador",
  auditor: "Auditor",
  analista: "Analista",
};

export const ETIQUETAS_ESTADO: Record<EstadoActivo, string> = {
  activo: "Activo",
  mantenimiento: "Mantenimiento",
  retirado: "Retirado",
};

export const ETIQUETAS_NIVEL: Record<NivelAcceso, string> = {
  ver: "Ver (sin contraseñas)",
  ver_credenciales: "Ver y revelar credenciales",
};

export const ETIQUETAS_TIPO_ACTIVO: Record<TipoActivo, string> = {
  fisico: "Servidor físico",
  hipervisor: "Hipervisor",
  vm: "Máquina virtual",
  dispositivo: "Dispositivo de red",
};

export const ETIQUETAS_TIPO_DISPOSITIVO: Record<TipoDispositivo, string> = {
  switch: "Switch",
  router: "Router",
  firewall: "Firewall",
  access_point: "Punto de acceso",
  balanceador: "Balanceador",
  otro: "Otro",
};

export const TIPOS_DISPOSITIVO: TipoDispositivo[] = [
  "switch",
  "router",
  "firewall",
  "access_point",
  "balanceador",
  "otro",
];

export const SERVICIOS = ["SSH", "RDP", "iLO/IPMI", "Web", "VNC", "WinRM", "Telnet", "Otro"];

export const ETIQUETAS_CATEGORIA_VAULT: Record<CategoriaVault, string> = {
  servicio: "Servicio",
  aplicacion: "Aplicación",
  cuenta: "Cuenta propia",
  otro: "Otro",
};

export const CATEGORIAS_VAULT: CategoriaVault[] = ["servicio", "aplicacion", "cuenta", "otro"];

export const ETIQUETAS_TOKEN_ALCANCE: Record<import("./types").TokenAlcance, string> = {
  todo: "Auditoría e inventario",
  auditoria: "Solo auditoría",
  inventario: "Solo inventario",
};

export const TOKEN_ALCANCES: import("./types").TokenAlcance[] = ["todo", "auditoria", "inventario"];

export const ESTADOS: EstadoActivo[] = ["activo", "mantenimiento", "retirado"];

export function rutaActivo(tipo: TipoActivo, id: number): string {
  if (tipo === "fisico") return `/servidores/${id}`;
  if (tipo === "hipervisor") return `/hipervisores/${id}`;
  if (tipo === "dispositivo") return `/dispositivos/${id}`;
  return `/vms/${id}`;
}

export function variantePorEstado(estado: EstadoActivo): "default" | "secondary" | "outline" {
  if (estado === "activo") return "default";
  if (estado === "mantenimiento") return "secondary";
  return "outline";
}
