import type { CoberturaAgente } from "@/lib/types";
import { AYUDA_COBERTURA, COLOR_COBERTURA, ETIQUETA_COBERTURA } from "@/lib/agentes";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

/** Insignia de cobertura de un activo. El estado lo decide el servidor. */
export function CoberturaBadge({ cobertura }: { cobertura: CoberturaAgente }) {
  return (
    <Badge variant="outline" title={AYUDA_COBERTURA[cobertura]} data-cobertura={cobertura}>
      <span className={cn("size-2 rounded-full", COLOR_COBERTURA[cobertura])} aria-hidden />
      {ETIQUETA_COBERTURA[cobertura]}
    </Badge>
  );
}
