import { cn } from "@/lib/utils";
import type { NivelRiesgo } from "@/lib/riesgo";

// El punto de riesgo: el único lugar donde el color "se filtra" en la interfaz.
//   ok       → neutro tenue
//   proxima  → rojo mezclado con neutro (advertencia)
//   vencida  → rojo destructive, con halo suave
export function RiskDot({
  nivel,
  size = 8,
  className,
}: {
  nivel: NivelRiesgo;
  size?: number;
  className?: string;
}) {
  const fondo =
    nivel === "ok"
      ? "color-mix(in oklch, var(--muted-foreground) 45%, transparent)"
      : nivel === "vencida"
        ? "var(--destructive)"
        : "color-mix(in oklch, var(--destructive) 50%, var(--muted-foreground))";

  return (
    <span
      aria-hidden
      className={cn("shrink-0 rounded-full", className)}
      style={{
        width: size,
        height: size,
        background: fondo,
        boxShadow: nivel === "vencida" ? "0 0 0 3px var(--destructive-soft)" : undefined,
      }}
    />
  );
}
