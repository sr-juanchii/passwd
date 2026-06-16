import { Badge } from "@/components/ui/badge";
import { ETIQUETAS_ESTADO, variantePorEstado } from "@/lib/constants";
import type { EstadoActivo } from "@/lib/types";

export function EstadoBadge({ estado }: { estado: EstadoActivo }) {
  return <Badge variant={variantePorEstado(estado)}>{ETIQUETAS_ESTADO[estado]}</Badge>;
}
