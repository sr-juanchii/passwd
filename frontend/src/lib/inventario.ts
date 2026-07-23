// Adaptadores y cálculo de "postura" para el rediseño del Inventario.
// El dashboard real (api.dashboard) devuelve servidores / hipervisores / VMs
// con formas ligeramente distintas; aquí los unificamos en `ActivoInv` para que
// el árbol, las tarjetas, la tabla y el panel lateral los traten igual.

import type {
  Credencial,
  DashboardAdmin,
  DispositivoNodo,
  EstadoActivo,
  HipervisorNodo,
  ServidorNodo,
  TipoActivo,
  VmNodo,
} from "./types";
import { DIAS_PROXIMA, nivelCredencial } from "./riesgo";

export interface ActivoInv {
  tipo: TipoActivo;
  id: number;
  nombre: string;
  estado: EstadoActivo;
  ip?: string;
  plataforma?: string;
  so?: string;
  tipoDispositivo?: string; // etiqueta del tipo de dispositivo de red (Switch, Router…)
  etiquetas?: string[];
  credenciales: Credencial[];
  vms?: ActivoInv[];
  parent?: string; // nombre del hipervisor (para la vista de tabla)
}

export function deServidor(s: ServidorNodo): ActivoInv {
  return {
    tipo: "fisico",
    id: s.id,
    nombre: s.nombre,
    estado: s.estado,
    ip: s.ip_gestion || undefined,
    etiquetas: s.etiquetas,
    credenciales: s.credenciales,
  };
}

export function deVm(v: VmNodo, parent?: string): ActivoInv {
  return {
    tipo: "vm",
    id: v.id,
    nombre: v.nombre,
    estado: v.estado,
    so: v.sistema_operativo || undefined,
    credenciales: v.credenciales,
    parent,
  };
}

export function deDispositivo(d: DispositivoNodo): ActivoInv {
  return {
    tipo: "dispositivo",
    id: d.id,
    nombre: d.nombre,
    estado: d.estado,
    ip: d.ip_gestion || undefined,
    tipoDispositivo: d.tipo_dispositivo_label || undefined,
    etiquetas: d.etiquetas,
    credenciales: d.credenciales,
  };
}

export function deHipervisor(h: HipervisorNodo): ActivoInv {
  return {
    tipo: "hipervisor",
    id: h.id,
    nombre: h.nombre,
    estado: h.estado,
    ip: h.ip_gestion || undefined,
    plataforma: h.plataforma || undefined,
    etiquetas: h.etiquetas,
    credenciales: h.credenciales,
    vms: h.vms.map((v) => deVm(v, h.nombre)),
  };
}

export interface ItemRiesgo {
  id: number;
  usuario: string;
  host: string;
  hostTipo: TipoActivo;
  servicio: string;
  dias: number;
  vencida: boolean;
  activo: ActivoInv;
}

export interface Postura {
  total: number;
  sanas: number;
  proximas: number;
  vencidas: number;
  servidores: number;
  hipervisores: number;
  vms: number;
  dispositivos: number;
  umbralDias: number;
}

export interface InventarioModelo {
  servidores: ActivoInv[];
  hipervisores: ActivoInv[];
  dispositivos: ActivoInv[];
  postura: Postura;
  colaRiesgo: ItemRiesgo[];
}

export function construirInventario(data: DashboardAdmin): InventarioModelo {
  const servidores = data.servidores.map(deServidor);
  const hipervisores = data.hipervisores.map(deHipervisor);
  const dispositivos = (data.dispositivos ?? []).map(deDispositivo);

  // Recorre todas las credenciales, junto al activo que las posee.
  const todos: ActivoInv[] = [
    ...servidores,
    ...hipervisores,
    ...hipervisores.flatMap((h) => h.vms ?? []),
    ...dispositivos,
  ];

  let sanas = 0;
  let proximas = 0;
  let vencidas = 0;
  const colaRiesgo: ItemRiesgo[] = [];

  for (const a of todos) {
    for (const c of a.credenciales) {
      const nivel = nivelCredencial(c);
      if (nivel === "vencida") vencidas++;
      else if (nivel === "proxima") proximas++;
      else sanas++;
      if (nivel !== "ok") {
        colaRiesgo.push({
          id: c.id,
          usuario: c.usuario_acceso,
          host: a.nombre,
          hostTipo: a.tipo,
          servicio: c.servicio,
          dias: c.dias_sin_rotar,
          vencida: c.rotacion_vencida,
          activo: a,
        });
      }
    }
  }

  // Más urgente primero: vencidas antes que próximas, luego por días.
  colaRiesgo.sort((a, b) => {
    if (a.vencida !== b.vencida) return a.vencida ? -1 : 1;
    return b.dias - a.dias;
  });

  const r = data.resumen;
  return {
    servidores,
    hipervisores,
    dispositivos,
    postura: {
      total: r.credenciales,
      sanas,
      proximas,
      vencidas,
      servidores: r.servidores,
      hipervisores: r.hipervisores,
      vms: r.vms,
      dispositivos: r.dispositivos ?? dispositivos.length,
      umbralDias: DIAS_PROXIMA,
    },
    colaRiesgo,
  };
}

export function iconoTipo(tipo: TipoActivo): "server" | "cpu" | "monitor-smartphone" | "network" {
  if (tipo === "fisico") return "server";
  if (tipo === "hipervisor") return "cpu";
  if (tipo === "dispositivo") return "network";
  return "monitor-smartphone";
}
