import Link from "next/link";
import { ShieldQuestion } from "lucide-react";

export default function NotFound() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 p-6 text-center">
      <ShieldQuestion className="h-12 w-12 text-muted-foreground" />
      <div>
        <h1 className="text-2xl font-semibold">Página no encontrada</h1>
        <p className="text-sm text-muted-foreground">
          La dirección solicitada no existe o ya no está disponible.
        </p>
      </div>
      <Link href="/" className="text-sm font-medium text-primary underline-offset-4 hover:underline">
        Volver al inicio
      </Link>
    </div>
  );
}
