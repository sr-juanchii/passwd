import Link from "next/link";
import { FileQuestion } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

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
    <Card>
      <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
        <FileQuestion className="h-10 w-10 text-muted-foreground" />
        <div>
          <p className="font-medium">{titulo}</p>
          <p className="text-sm text-muted-foreground">{mensaje}</p>
        </div>
        <Button asChild variant="outline">
          <Link href={volverHref}>{volverLabel}</Link>
        </Button>
      </CardContent>
    </Card>
  );
}
