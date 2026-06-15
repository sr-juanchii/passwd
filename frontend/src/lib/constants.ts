import type { EstadoActivo, NivelAcceso, Rol, TipoActivo, TipoServidor } from "./types";

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

export const ETIQUETAS_TIPO_SERVIDOR: Record<TipoServidor, string> = {
  funcion_unica: "Función única",
  host_virtualizacion: "Host de virtualización",
};

export const ETIQUETAS_NIVEL: Record<NivelAcceso, string> = {
  ver: "Ver (sin contraseñas)",
  ver_credenciales: "Ver y revelar credenciales",
};

export const ETIQUETAS_TIPO_ACTIVO: Record<TipoActivo, string> = {
  fisico: "Servidor físico",
  hipervisor: "Hipervisor",
  vm: "Máquina virtual",
};

export const SERVICIOS = ["SSH", "RDP", "iLO/IPMI", "Web", "VNC", "WinRM", "Telnet", "Otro"];

export const ESTADOS: EstadoActivo[] = ["activo", "mantenimiento", "retirado"];

export function rutaActivo(tipo: TipoActivo, id: number): string {
  if (tipo === "fisico") return `/servidores/${id}`;
  if (tipo === "hipervisor") return `/hipervisores/${id}`;
  return `/vms/${id}`;
}

export function variantePorEstado(estado: EstadoActivo): "default" | "secondary" | "outline" {
  if (estado === "activo") return "default";
  if (estado === "mantenimiento") return "secondary";
  return "outline";
}
