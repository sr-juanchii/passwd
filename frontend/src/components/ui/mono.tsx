import { cn } from "@/lib/utils";

// Valor "machine-identifiable" (usuarios, IPs, puertos, secretos revelados).
// En este diseño la tipografía mono lleva peso semántico: todo lo que una
// máquina podría identificar se compone en Geist Mono.
export function Mono({ className, ...props }: React.ComponentProps<"span">) {
  return (
    <span
      className={cn("font-mono text-[0.92em] tracking-[0.01em]", className)}
      {...props}
    />
  );
}

// Antetítulo en versalitas mono — encabeza secciones y paneles.
export function Eyebrow({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      className={cn(
        "font-mono text-2xs font-medium tracking-[0.14em] text-muted-foreground uppercase",
        className,
      )}
      {...props}
    />
  );
}

// Pista de teclado (p. ej. ⌘K, esc).
export function Kbd({ className, ...props }: React.ComponentProps<"kbd">) {
  return (
    <kbd
      className={cn(
        "rounded-sm border bg-muted px-1.5 py-[3px] font-mono text-2xs leading-none font-medium text-muted-foreground",
        className,
      )}
      {...props}
    />
  );
}
