import Link from "next/link";
import { FileQuestion } from "lucide-react";
import { Button } from "@/components/ui/button";

export function ErrorRecurso({
  titulo = "No disponible",
  mensaje,
  volverHref = "/",
  volverLabel = "Volver al inventario",
}: {
  titulo?: string;
  mensaje: string;
  volverHref?: string;
  volverLabel?: string;
}) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-[14px] border border-dashed p-12 text-center">
      <div className="flex size-12 items-center justify-center rounded-xl bg-muted">
        <FileQuestion className="size-6 text-muted-foreground" />
      </div>
      <div>
        <p className="font-medium">{titulo}</p>
        <p className="text-sm text-muted-foreground">{mensaje}</p>
      </div>
      <Button asChild variant="outline">
        <Link href={volverHref}>{volverLabel}</Link>
      </Button>
    </div>
  );
}
