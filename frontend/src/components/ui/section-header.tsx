import { Chip } from "@/components/ui/chip";
import { Eyebrow } from "@/components/ui/mono";
import { cn } from "@/lib/utils";

// Encabezado único de sección (DESIGN.md §4): Eyebrow + icono opcional +
// contador Chip + acción a la derecha. Sustituye a los patrones ad-hoc
// («text-sm font-semibold», estilos propios de auditoría…).
export function SectionHeader({
  icono: Icono,
  titulo,
  contador,
  accion,
  className,
}: {
  icono?: React.ComponentType<{ className?: string }>;
  titulo: React.ReactNode;
  contador?: number | string;
  accion?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex items-center justify-between gap-3", className)}>
      <Eyebrow className="flex items-center gap-1.5">
        {Icono && <Icono className="size-3.5" />}
        {titulo}
        {contador !== undefined && (
          <Chip mono className="ml-1">
            {contador}
          </Chip>
        )}
      </Eyebrow>
      {accion && <div className="flex shrink-0 items-center gap-2">{accion}</div>}
    </div>
  );
}
