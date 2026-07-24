import { Lock } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

// Distintivo para activos restringidos a administradores. En las fichas de
// detalle se muestra con el texto completo; en listados (árbol, tabla, tarjetas,
// drawer) en su forma compacta. Sirve a admin y auditor para reconocer de un
// vistazo un activo que el operador no ve.
export function RestringidoBadge({
  compacto = false,
  className,
}: {
  compacto?: boolean;
  className?: string;
}) {
  return (
    <Badge
      variant="secondary"
      className={cn("gap-1", className)}
      title="Restringido a administradores"
    >
      <Lock />
      {compacto ? "Restringido" : "Restringido a administradores"}
    </Badge>
  );
}
