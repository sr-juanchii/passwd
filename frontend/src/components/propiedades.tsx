import { cn } from "@/lib/utils";

export interface Propiedad {
  etiqueta: string;
  valor: React.ReactNode;
  /** Compone el valor en Geist Mono (IPs, números de serie, etc.). */
  mono?: boolean;
}

export function Propiedades({ titulo, items }: { titulo?: string; items: Propiedad[] }) {
  const visibles = items.filter((p) => p.valor !== "" && p.valor !== null && p.valor !== undefined);
  if (visibles.length === 0) return null;
  return (
    <section className="overflow-hidden rounded-[14px] border bg-card">
      {titulo && (
        <div className="border-b px-5 py-3.5">
          <span className="text-sm font-semibold">{titulo}</span>
        </div>
      )}
      <dl className="grid gap-x-8 gap-y-3.5 p-5 sm:grid-cols-2">
        {visibles.map((p) => (
          <div key={p.etiqueta} className="flex flex-col gap-1">
            <dt className="text-[12.5px] text-muted-foreground">{p.etiqueta}</dt>
            <dd className={cn("text-[13px]", p.mono && "font-mono")}>{p.valor}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
