import { cn } from "@/lib/utils";

type Tono = "default" | "outline" | "ink";

const TONOS: Record<Tono, string> = {
  default: "border-transparent bg-muted text-muted-foreground",
  outline: "border-border bg-transparent text-muted-foreground",
  ink: "border-border bg-transparent text-foreground",
};

// Etiqueta monocroma compacta (tipo, plataforma, SO, puerto…). Más pequeña y
// discreta que un Badge; usa `mono` para valores identificables por máquina.
export function Chip({
  tono = "default",
  mono = false,
  className,
  ...props
}: React.ComponentProps<"span"> & { tono?: Tono; mono?: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex h-5 items-center gap-1 whitespace-nowrap rounded-md border px-[7px] text-[11.5px] leading-none font-medium",
        mono ? "font-mono tracking-[0.02em]" : "font-sans",
        TONOS[tono],
        className,
      )}
      {...props}
    />
  );
}
