// Fechas que llegan del backend.
//
// El backend guarda y serializa las fechas en UTC pero SIN zona
// («2026-11-26T10:00:00»), y JavaScript interpreta una cadena así como hora
// LOCAL: en Caracas (UTC−4) esa fecha se leería cuatro horas más tarde de lo que
// fue. Toda fecha del servidor debe pasar por `instante` antes de compararse o
// mostrarse.

const CON_ZONA = /(Z|[+-]\d{2}:?\d{2})$/i;

const SOLO_FECHA = /^(\d{4})-(\d{2})-(\d{2})$/;

/** El instante que el servidor quiso decir: sin zona, es UTC. */
export function instante(valor: string): Date {
  // Una fecha sola es un día del calendario, no un instante: medianoche local,
  // para que no se convierta en el día anterior al oeste de Greenwich.
  const dia = SOLO_FECHA.exec(valor);
  if (dia) return new Date(Number(dia[1]), Number(dia[2]) - 1, Number(dia[3]));
  return new Date(CON_ZONA.test(valor) ? valor : `${valor}Z`);
}

/** Solo la fecha local de una fecha del servidor. */
export function soloFecha(valor: string): string {
  return instante(valor).toLocaleDateString();
}

/** Fecha y hora locales de una fecha del servidor, o «—». */
export function fechaHora(valor: string | null | undefined): string {
  return valor ? instante(valor).toLocaleString() : "—";
}
