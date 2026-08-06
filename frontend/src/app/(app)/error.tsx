"use client";

import { useEffect } from "react";
import { TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function ErrorBoundary({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Solo en desarrollo: en producción, volcar el objeto Error a la consola
    // expone la traza de pila (nombres de módulos y funciones internas) a
    // cualquiera con la consola abierta. El `digest` que Next muestra en la
    // interfaz basta para correlacionar el fallo con el log del servidor.
    if (process.env.NODE_ENV !== "production") {
      console.error(error);
    }
  }, [error]);

  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 text-center">
      <TriangleAlert className="h-10 w-10 text-destructive" />
      <div>
        <h1 className="text-xl font-semibold">Algo salió mal</h1>
        <p className="text-sm text-muted-foreground">
          Ocurrió un error inesperado al mostrar esta página.
          {error.digest ? ` (ref. ${error.digest})` : ""}
        </p>
      </div>
      <Button onClick={reset} variant="outline">
        Reintentar
      </Button>
    </div>
  );
}
