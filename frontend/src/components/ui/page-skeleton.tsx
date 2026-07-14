import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

function FilaTabla() {
  return (
    <div className="flex items-center gap-4 px-4 py-3">
      <Skeleton className="h-4 w-4 rounded-full" />
      <Skeleton className="h-4 w-[30%]" />
      <Skeleton className="h-4 w-[18%]" />
      <Skeleton className="ml-auto h-4 w-[12%]" />
    </div>
  );
}

function CardTabla({ filas = 6 }: { filas?: number }) {
  return (
    <div className="overflow-hidden rounded-xl border bg-card">
      <div className="flex items-center gap-4 border-b bg-muted px-4 py-3">
        <Skeleton className="h-3.5 w-24" />
        <Skeleton className="h-3.5 w-16" />
        <Skeleton className="ml-auto h-3.5 w-14" />
      </div>
      <div className="divide-y">
        {Array.from({ length: filas }).map((_, i) => (
          <FilaTabla key={i} />
        ))}
      </div>
    </div>
  );
}

// Esqueletos con la silueta real de cada forma de página (DESIGN.md §4).
// Las cargas de datos muestran esto, nunca un spinner centrado.
export function PageSkeleton({
  variante = "tabla",
  cabecera = true,
  className,
}: {
  variante?: "hero" | "tabla" | "ficha" | "formulario";
  /** false cuando el PageHeader real ya está pintado (carga dentro de página). */
  cabecera?: boolean;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-4", className)} aria-busy>
      {cabecera && (
        <div className="mb-2 space-y-2">
          <Skeleton className="h-7 w-52" />
          <Skeleton className="h-4 w-80 max-w-full" />
        </div>
      )}

      {variante === "hero" && (
        <>
          <section className="grid items-stretch gap-4 lg:grid-cols-[1.5fr_1fr]">
            <div className="flex flex-col gap-5 rounded-xl border bg-card p-5">
              <Skeleton className="h-3.5 w-40" />
              <div className="flex items-end gap-4">
                <Skeleton className="h-14 w-24" />
                <Skeleton className="h-4 w-44" />
              </div>
              <Skeleton className="h-[11px] w-full rounded-md" />
              <div className="mt-auto grid grid-cols-4 gap-px overflow-hidden rounded-lg border bg-border">
                {Array.from({ length: 4 }).map((_, i) => (
                  <div key={i} className="flex flex-col gap-2 bg-card px-3.5 py-3">
                    <Skeleton className="size-4" />
                    <Skeleton className="h-6 w-10" />
                    <Skeleton className="h-3 w-16" />
                  </div>
                ))}
              </div>
            </div>
            <div className="flex flex-col gap-3 rounded-xl border bg-card p-5">
              <Skeleton className="h-3.5 w-28" />
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-12 w-full rounded-lg" />
              ))}
            </div>
          </section>
          <CardTabla filas={4} />
        </>
      )}

      {variante === "tabla" && <CardTabla />}

      {variante === "ficha" && (
        <>
          <div className="overflow-hidden rounded-xl border bg-card">
            <div className="border-b px-5 py-3.5">
              <Skeleton className="h-3.5 w-32" />
            </div>
            <div className="grid gap-x-6 gap-y-4 p-5 sm:grid-cols-2">
              {Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="space-y-1.5">
                  <Skeleton className="h-3 w-20" />
                  <Skeleton className="h-4 w-36" />
                </div>
              ))}
            </div>
          </div>
          <CardTabla filas={3} />
        </>
      )}

      {variante === "formulario" && (
        <div className="overflow-hidden rounded-xl border bg-card">
          <div className="border-b px-5 py-3.5">
            <Skeleton className="h-3.5 w-32" />
          </div>
          <div className="grid gap-5 p-5">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="space-y-2">
                <Skeleton className="h-3.5 w-24" />
                <Skeleton className="h-8 w-full rounded-lg" />
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
