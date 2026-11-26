// Etiquetas y formato de la gobernanza de rotación.
//
// Una rotación es un expediente, no un campo editable: se solicita con motivo,
// la autoriza otra persona y solo entonces se registra la contraseña que quedó
// aplicada en el activo. Estas utilidades ponen nombre a cada estado para que
// la interfaz no hable en jerga de base de datos.

import type { EstadoRotacion, RotacionAsiento, TipoRotacion, VerificacionRotacion } from "./types";
import { fechaHora } from "./fechas";

export const ETIQUETA_ESTADO: Record<EstadoRotacion, string> = {
  solicitada: "Esperando autorización",
  autorizada: "Autorizada, pendiente de aplicar",
  despachada: "En ejecución",
  cerrada: "Cerrada",
  rechazada: "Rechazada",
  cancelada: "Cancelada",
  expirada: "Expirada",
};

export const ETIQUETA_TIPO: Record<TipoRotacion, string> = {
  programada: "Programada",
  manual: "Manual",
  emergencia: "Emergencia",
  masiva: "Masiva",
};

export const ETIQUETA_VERIFICACION: Record<VerificacionRotacion, string> = {
  ninguna: "Sin comprobación automática",
  local: "Comprobada en el sistema operativo",
  remota: "Comprobada contra el servicio declarado",
};

/** Texto de la desviación: lo que importa es si se adelantó o se retrasó. */
export function textoDesvio(asiento: RotacionAsiento): string {
  if (asiento.dias_al_rotar === null || asiento.desvio_dias === null) return "";
  const dias = asiento.dias_al_rotar;
  const desvio = asiento.desvio_dias;
  if (desvio === 0) return `Rotada a los ${dias} días, justo en la fecha de política.`;
  if (desvio < 0) return `Rotada a los ${dias} días, ${Math.abs(desvio)} antes de lo previsto.`;
  return `Rotada a los ${dias} días, ${desvio} después de lo previsto.`;
}

export function fecha(valor: string | null): string {
  return fechaHora(valor);
}
