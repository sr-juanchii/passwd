"use client";

import { Copy } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";

// Códigos de recuperación recién emitidos: se muestran UNA sola vez.
export function CodigosRecuperacion({
  codigos,
  textoContinuar,
  onContinuar,
}: {
  codigos: string[];
  textoContinuar: string;
  onContinuar: () => void;
}) {
  return (
    <div>
      <p className="text-[13.5px] leading-normal text-muted-foreground">
        Guárdelos en un lugar seguro. Se muestran <strong>una sola vez</strong> y permiten entrar
        si no puede usar su método habitual. Cada código sirve una vez.
      </p>
      <div className="mt-5 grid grid-cols-2 gap-2 rounded-lg border bg-muted/40 p-4 font-mono text-sm">
        {codigos.map((c) => (
          <span key={c}>{c}</span>
        ))}
      </div>
      <Button
        variant="outline"
        className="mt-4 w-full"
        onClick={() => {
          void navigator.clipboard?.writeText(codigos.join("\n"));
          toast.success("Códigos copiados al portapapeles.");
        }}
      >
        <Copy /> Copiar códigos
      </Button>
      <Button className="mt-2 h-10 w-full" onClick={onContinuar}>
        {textoContinuar}
      </Button>
    </div>
  );
}
