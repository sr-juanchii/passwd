// Etiquetas y utilidades de los agentes de rotación (v1.4.0).
//
// La cobertura la calcula el servidor a partir de las fechas (último latido,
// caducidad de la identidad): aquí solo se le pone nombre y color, para que una
// insignia nunca diga algo distinto de lo que dice el backend.

import type { CoberturaAgente, TipoActivoAgente } from "./types";

export const ETIQUETA_COBERTURA: Record<CoberturaAgente, string> = {
  sin_agente: "Sin agente",
  pendiente: "Pendiente de instalar",
  conectado: "Conectado",
  sin_contacto: "Sin contacto",
  caducado: "Identidad caducada",
};

export const AYUDA_COBERTURA: Record<CoberturaAgente, string> = {
  sin_agente: "Las contraseñas de este activo se rotan a mano.",
  pendiente: "El agente está dado de alta, pero todavía no se ha instalado con su token.",
  conectado: "El agente late con normalidad y puede ejecutar rotaciones autorizadas.",
  sin_contacto: "El agente lleva demasiado tiempo sin latir: compruebe el servicio en el servidor.",
  caducado: "El agente estuvo apagado más de lo que dura su identidad: hay que reinstalarlo con un token nuevo.",
};

/** Clase del punto de color de cada estado (mismo código que el resto del panel). */
export const COLOR_COBERTURA: Record<CoberturaAgente, string> = {
  sin_agente: "bg-muted-foreground/40",
  pendiente: "bg-orange-500",
  conectado: "bg-emerald-500",
  sin_contacto: "bg-amber-400",
  caducado: "bg-red-500",
};

const RUTA_ACTIVO: Record<TipoActivoAgente, string> = {
  fisico: "servidores",
  hipervisor: "hipervisores",
  vm: "vms",
};

export function rutaActivo(tipo: TipoActivoAgente, id: number): string {
  return `/${RUTA_ACTIVO[tipo]}/${id}`;
}

/** «hace 3 min», «hace 2 h», «hace 5 días»: lo que hace falta para leer un latido. */
export function haceCuanto(valor: string | null, ahora: Date = new Date()): string {
  if (!valor) return "nunca";
  const segundos = Math.max(0, Math.round((ahora.getTime() - new Date(valor).getTime()) / 1000));
  if (segundos < 60) return "hace un momento";
  const minutos = Math.round(segundos / 60);
  if (minutos < 60) return `hace ${minutos} min`;
  const horas = Math.round(minutos / 60);
  if (horas < 48) return `hace ${horas} h`;
  return `hace ${Math.round(horas / 24)} días`;
}

/**
 * Orden de instalación para el servidor. El token NO va en ella: se pega por la
 * entrada estándar (`--token -`), para que no quede en el historial del shell
 * ni a la vista de `ps`.
 */
export function comandoInstalacion(origen: string, cuentas: string[]): string {
  const lista = cuentas.length > 0 ? cuentas.join(",") : "CUENTA1,CUENTA2";
  return (
    `sudo ./instalar.sh --backend ${origen} --cuentas ${lista} ` +
    `--binarios . --sumas SHA256SUMS --token -`
  );
}
