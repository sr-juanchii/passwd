// Lógica de "señal de riesgo" del rediseño. El sistema es monocromo a propósito:
// el único color (rojo destructive) aparece SOLO donde una credencial necesita
// rotación. Estas funciones traducen el modelo real (Credencial, nodos de
// inventario) a un nivel de riesgo que consumen RiskDot y las pantallas.

import type { Credencial, HipervisorNodo, ServidorNodo, VmNodo } from "./types";

export type NivelRiesgo = "ok" | "proxima" | "vencida";

// Forma estructural mínima: cualquier nodo con credenciales y, opcionalmente,
// VMs anidadas que a su vez tengan credenciales (VmNodo o ActivoInv encajan).
type ConCredenciales = {
  credenciales: Credencial[];
  vms?: { credenciales: Credencial[] }[];
};

// Umbral (en días sin rotar) a partir del cual una credencial se considera
// "por vencer" aunque aún no esté vencida.
export const DIAS_PROXIMA = 60;

export function nivelCredencial(c: Credencial): NivelRiesgo {
  if (c.rotacion_vencida) return "vencida";
  if (c.dias_sin_rotar >= DIAS_PROXIMA) return "proxima";
  return "ok";
}

export function nivelActivo(a: ConCredenciales): NivelRiesgo {
  const creds = a.credenciales ?? [];
  const vms = a.vms ?? [];
  const vencida =
    creds.some((c) => c.rotacion_vencida) ||
    vms.some((v) => v.credenciales.some((c) => c.rotacion_vencida));
  if (vencida) return "vencida";
  const proxima =
    creds.some((c) => c.dias_sin_rotar >= DIAS_PROXIMA) ||
    vms.some((v) => v.credenciales.some((c) => c.dias_sin_rotar >= DIAS_PROXIMA));
  if (proxima) return "proxima";
  return "ok";
}

// Rango de urgencia para ordenar el inventario (más alto = más urgente).
export function rangoUrgencia(a: ConCredenciales): number {
  const n = nivelActivo(a);
  return n === "vencida" ? 100 : n === "proxima" ? 10 : 0;
}

// Número de credenciales vencidas (incluye las de las VMs anidadas).
export function alertas(a: ConCredenciales): number {
  let n = (a.credenciales ?? []).filter((c) => c.rotacion_vencida).length;
  for (const v of a.vms ?? []) n += v.credenciales.filter((c) => c.rotacion_vencida).length;
  return n;
}

export type NodoActivo = ServidorNodo | HipervisorNodo | VmNodo;
