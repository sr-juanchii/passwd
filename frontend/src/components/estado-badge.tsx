import { Chip } from "@/components/ui/chip";
import { ETIQUETAS_ESTADO } from "@/lib/constants";
import type { EstadoActivo } from "@/lib/types";

// Estado del activo, rebalanceado (DESIGN.md §1 — tinta y estado): lo normal
// no debe pesar, la excepción sí.
//   activo        → chip outline discreto (sin relleno)
//   mantenimiento → tinte --warning-soft + texto --warning
//   retirado      → muted
// Criterio de uso: en fichas y tablas se muestra siempre; en vistas densas
// (árbol del inventario, tarjetas) solo cuando el estado difiere de «activo».
export function EstadoBadge({ estado }: { estado: EstadoActivo }) {
  if (estado === "mantenimiento") {
    return (
      <Chip className="border-transparent bg-(--warning-soft) text-warning">
        {ETIQUETAS_ESTADO.mantenimiento}
      </Chip>
    );
  }
  return (
    <Chip tono={estado === "activo" ? "outline" : "default"}>{ETIQUETAS_ESTADO[estado]}</Chip>
  );
}
