"use client";

import { cn } from "@/lib/utils";

export interface OpcionSegmento {
  valor: string;
  etiqueta?: string;
  icono?: React.ReactNode;
  titulo?: string;
}

// Control segmentado (filtros, densidad, vista de inventario). La pastilla
// activa se eleva sobre el riel con la "hairline ring" del sistema.
export function Segmented({
  value,
  onChange,
  options,
  size = "md",
  className,
}: {
  value: string;
  onChange: (v: string) => void;
  options: OpcionSegmento[];
  size?: "sm" | "md";
  className?: string;
}) {
  const h = size === "sm" ? "h-7" : "h-8";
  return (
    <div
      className={cn("inline-flex gap-[3px] rounded-[9px] bg-muted p-[3px]", className)}
      role="tablist"
    >
      {options.map((o) => {
        const activo = value === o.valor;
        return (
          <button
            key={o.valor}
            type="button"
            role="tab"
            aria-selected={activo}
            title={o.titulo ?? o.etiqueta}
            onClick={() => onChange(o.valor)}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md px-2.5 text-[12.5px] font-medium transition-colors",
              h,
              o.icono && !o.etiqueta ? "px-2" : "",
              activo
                ? "bg-card text-foreground shadow-[var(--ring-hairline)]"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {o.icono}
            {o.etiqueta}
          </button>
        );
      })}
    </div>
  );
}
