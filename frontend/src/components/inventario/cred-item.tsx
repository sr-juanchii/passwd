"use client";

import { useRef, useState } from "react";
import { Check, Clipboard, Eye, EyeOff, Loader2, LockOpen, RefreshCw } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { Credencial } from "@/lib/types";
import { nivelCredencial } from "@/lib/riesgo";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Mono } from "@/components/ui/mono";
import { RiskDot } from "@/components/risk-dot";
import { toast } from "sonner";

const OCULTAR_MS = 30_000;

// Credencial en el estilo del rediseño: tarjeta con punto de riesgo, valores en
// mono y acciones revelar / copiar. Reutiliza la misma API segura del producto
// (cada revelado/copiado queda registrado en la bitácora).
export function CredItem({ cred }: { cred: Credencial }) {
  const [revelada, setRevelada] = useState<string | null>(null);
  const [usuarioRev, setUsuarioRev] = useState<string | null>(null);
  const [cargando, setCargando] = useState<"revelar" | "copiar" | null>(null);
  const [copiada, setCopiada] = useState(false);
  const tRevelar = useRef<ReturnType<typeof setTimeout> | null>(null);
  const tCopiar = useRef<ReturnType<typeof setTimeout> | null>(null);

  const nivel = nivelCredencial(cred);

  function ocultar() {
    if (tRevelar.current) clearTimeout(tRevelar.current);
    setRevelada(null);
    setUsuarioRev(null);
  }

  async function revelar() {
    if (revelada !== null) return ocultar();
    setCargando("revelar");
    try {
      const r = await api.revelarCredencial(cred.id);
      setRevelada(r.password);
      setUsuarioRev(r.usuario);
      tRevelar.current = setTimeout(ocultar, OCULTAR_MS);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "No se pudo revelar.");
    } finally {
      setCargando(null);
    }
  }

  async function copiar() {
    setCargando("copiar");
    try {
      const r = await api.copiarCredencial(cred.id);
      await navigator.clipboard.writeText(r.password);
      setCopiada(true);
      toast.success("Contraseña copiada. Se limpiará del portapapeles en 30 s.");
      if (tCopiar.current) clearTimeout(tCopiar.current);
      tCopiar.current = setTimeout(async () => {
        try {
          await navigator.clipboard.writeText("");
        } catch {
          /* el navegador puede bloquear la escritura sin foco */
        }
        setCopiada(false);
      }, OCULTAR_MS);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "No se pudo copiar.");
    } finally {
      setCargando(null);
    }
  }

  return (
    <div
      className={cn(
        "overflow-hidden rounded-[11px] border bg-background",
        nivel === "vencida" && "bg-destructive/[0.06]",
      )}
    >
      <div className="flex items-center gap-2.5 px-3.5 py-3">
        <RiskDot nivel={nivel} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Mono className="text-[13.5px] font-semibold">{cred.usuario_acceso}</Mono>
            <Chip tono="outline">{cred.servicio}</Chip>
            {cred.puerto != null && <Chip mono>:{cred.puerto}</Chip>}
          </div>
          {cred.descripcion && (
            <div className="mt-0.5 text-xs text-muted-foreground">{cred.descripcion}</div>
          )}
        </div>
        <div className="text-right">
          {cred.rotacion_vencida ? (
            <span className="font-mono text-xs font-semibold text-destructive">
              {cred.dias_sin_rotar}d · vencida
            </span>
          ) : (
            <span className="font-mono text-xs text-muted-foreground">
              hace {cred.dias_sin_rotar}d
            </span>
          )}
        </div>
      </div>
      {cred.puede_revelar ? (
        <div className="flex items-center gap-2 px-3.5 pb-3">
          <Button size="sm" variant="outline" onClick={copiar} disabled={cargando !== null}>
            {cargando === "copiar" ? (
              <Loader2 className="animate-spin" />
            ) : copiada ? (
              <Check />
            ) : (
              <Clipboard />
            )}
            {copiada ? "Copiada · 30 s" : "Copiar"}
          </Button>
          <Button size="sm" variant="outline" onClick={revelar} disabled={cargando !== null}>
            {cargando === "revelar" ? (
              <Loader2 className="animate-spin" />
            ) : revelada !== null ? (
              <EyeOff />
            ) : (
              <Eye />
            )}
            {revelada !== null ? "Ocultar" : "Revelar"}
          </Button>
          {cred.rotacion_vencida && (
            <Button size="sm" variant="destructive" className="ml-auto" disabled>
              <RefreshCw /> Rotar
            </Button>
          )}
        </div>
      ) : (
        <div className="px-3.5 pb-3 text-xs text-muted-foreground">
          Oculta — no tiene permiso para revelarla.
        </div>
      )}
      {revelada !== null && (
        <div className="px-3.5 pb-3.5">
          <div className="flex items-center gap-2 rounded-lg border bg-muted px-3 py-2 font-mono text-[13px] break-all">
            <LockOpen className="size-3.5 shrink-0 text-muted-foreground" />
            {usuarioRev}: {revelada}
          </div>
        </div>
      )}
    </div>
  );
}
