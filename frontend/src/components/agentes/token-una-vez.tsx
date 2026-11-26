"use client";

import { useState } from "react";
import { Check, Copy, KeyRound } from "lucide-react";
import type { TokenInstalacion } from "@/lib/types";
import { comandoInstalacion } from "@/lib/agentes";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";

/**
 * El token de instalación, visible una sola vez.
 *
 * El servidor solo guarda su hash: al cerrar este aviso ya no se puede volver a
 * ver, y si se pierde hay que emitir otro. Caduca en una hora y sirve para un
 * único enrolamiento.
 */
export function TokenUnaVez({ datos, cuentas, onCerrar }: {
  datos: TokenInstalacion;
  cuentas: string[];
  onCerrar: () => void;
}) {
  const [copiado, setCopiado] = useState(false);
  const orden = comandoInstalacion(window.location.origin, cuentas);

  async function copiar() {
    try {
      await navigator.clipboard.writeText(datos.token_enrolamiento);
      setCopiado(true);
      toast.success("Token copiado.");
    } catch {
      toast.error("No se pudo copiar: selecciónelo a mano.");
    }
  }

  return (
    <div className="space-y-3 rounded-lg border border-amber-500/50 bg-amber-500/5 p-4" role="status">
      <p className="flex items-center gap-2 text-sm font-medium">
        <KeyRound className="size-4" /> Token de instalación de «{datos.agente.nombre}»
      </p>
      <p className="text-xs text-muted-foreground">
        Se muestra <strong>una sola vez</strong>: el servidor solo guarda su huella. Sirve para un
        único enrolamiento y caduca {datos.token_expira_en
          ? `el ${new Date(datos.token_expira_en).toLocaleString()}`
          : "en una hora"}.
      </p>
      <div className="flex items-center gap-2">
        <code className="flex-1 break-all rounded bg-muted px-2 py-1.5 font-mono text-xs" data-testid="token-instalacion">
          {datos.token_enrolamiento}
        </code>
        <Button size="sm" variant="outline" onClick={copiar} aria-label="Copiar el token">
          {copiado ? <Check className="size-4" /> : <Copy className="size-4" />}
        </Button>
      </div>
      <div className="space-y-1">
        <p className="text-xs text-muted-foreground">
          En el servidor, desde el directorio con los binarios y su archivo de sumas, ejecute la
          orden y pegue el token cuando la pida (no va en la línea de órdenes, para que no quede
          en el historial):
        </p>
        <code className="block break-all rounded bg-muted px-2 py-1.5 font-mono text-xs">{orden}</code>
      </div>
      <Button size="sm" variant="secondary" onClick={onCerrar}>
        Ya lo he guardado
      </Button>
    </div>
  );
}
