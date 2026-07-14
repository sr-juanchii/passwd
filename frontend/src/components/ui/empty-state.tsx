import { cn } from "@/lib/utils";

// Patrón único de estado vacío (DESIGN.md §4): tile de icono + título +
// descripción + CTA opcional. `compacto` para vacíos dentro de tarjetas
// (credenciales, vault, drawer); el modo normal es para páginas.
export function EmptyState({
  icono: Icono,
  titulo,
  descripcion,
  accion,
  compacto = false,
  className,
}: {
  icono: React.ComponentType<{ className?: string }>;
  titulo: string;
  descripcion?: React.ReactNode;
  accion?: React.ReactNode;
  compacto?: boolean;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center rounded-xl border border-dashed text-center",
        compacto ? "gap-2 p-6" : "gap-3 p-10",
        className,
      )}
    >
      <div
        className={cn(
          "flex items-center justify-center rounded-xl bg-muted",
          compacto ? "size-9 rounded-lg" : "size-12",
        )}
      >
        <Icono className={cn("text-muted-foreground", compacto ? "size-4" : "size-5")} />
      </div>
      <div className="space-y-1">
        <p className={cn("font-medium", compacto ? "text-[13px]" : "text-sm")}>{titulo}</p>
        {descripcion && (
          <p className="mx-auto max-w-[360px] text-[13px] leading-relaxed text-muted-foreground">
            {descripcion}
          </p>
        )}
      </div>
      {accion && <div className="mt-1">{accion}</div>}
    </div>
  );
}
