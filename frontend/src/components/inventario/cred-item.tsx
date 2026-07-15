"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  Check,
  Clipboard,
  Eye,
  EyeOff,
  Loader2,
  LockOpen,
  Pencil,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { Credencial } from "@/lib/types";
import { nivelCredencial } from "@/lib/riesgo";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Mono } from "@/components/ui/mono";
import { RiskDot } from "@/components/risk-dot";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { toast } from "sonner";

const OCULTAR_MS = 30_000;

// Credencial en el estilo del rediseño: tarjeta con punto de riesgo, valores en
// mono y acciones revelar / copiar. Reutiliza la misma API segura del producto
// (cada revelado/copiado queda registrado en la bitácora). Cuando `gestionable`
// es true añade rotar / editar / eliminar — sirve igual en el drawer del
// inventario que en las fichas de detalle.
export function CredItem({
  cred,
  gestionable = false,
  onCambio,
}: {
  cred: Credencial;
  gestionable?: boolean;
  onCambio?: () => void;
}) {
  const [revelada, setRevelada] = useState<string | null>(null);
  const [usuarioRev, setUsuarioRev] = useState<string | null>(null);
  const [cargando, setCargando] = useState<"revelar" | "copiar" | null>(null);
  const [copiada, setCopiada] = useState(false);
  const [restante, setRestante] = useState<number | null>(null);
  const tRevelar = useRef<ReturnType<typeof setTimeout> | null>(null);
  const tCopiar = useRef<ReturnType<typeof setTimeout> | null>(null);
  const tTick = useRef<ReturnType<typeof setInterval> | null>(null);

  const nivel = nivelCredencial(cred);

  // Al desmontar se limpian los timers visuales del revelado. El timeout del
  // portapapeles (tCopiar) NO se toca: la limpieza a los 30 s debe ocurrir
  // aunque el componente ya no esté montado.
  useEffect(() => {
    return () => {
      if (tRevelar.current) clearTimeout(tRevelar.current);
      if (tTick.current) clearInterval(tTick.current);
    };
  }, []);

  function ocultar() {
    if (tRevelar.current) clearTimeout(tRevelar.current);
    if (tTick.current) clearInterval(tTick.current);
    setRevelada(null);
    setUsuarioRev(null);
    setRestante(null);
  }

  async function revelar() {
    if (revelada !== null) return ocultar();
    setCargando("revelar");
    try {
      const r = await api.revelarCredencial(cred.id);
      setRevelada(r.password);
      setUsuarioRev(r.usuario);
      tRevelar.current = setTimeout(ocultar, OCULTAR_MS);
      // Cuenta atrás visible de los 30 s. Solo pinta: el que manda sigue
      // siendo el timeout de seguridad de arriba.
      setRestante(Math.round(OCULTAR_MS / 1000));
      if (tTick.current) clearInterval(tTick.current);
      tTick.current = setInterval(() => {
        setRestante((s) => (s === null || s <= 1 ? s : s - 1));
      }, 1000);
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

  async function eliminar() {
    try {
      await api.eliminarCredencial(cred.id);
      toast.success("Credencial eliminada.");
      onCambio?.();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "No se pudo eliminar.");
    }
  }

  const mostrarBarra = cred.puede_revelar || gestionable;

  return (
    <div
      className={cn(
        "overflow-hidden rounded-lg border bg-background",
        nivel === "vencida" && "bg-destructive/[0.06]",
        nivel === "proxima" && "bg-warning/[0.06]",
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
          ) : nivel === "proxima" ? (
            <span className="font-mono text-xs font-semibold text-warning">
              {cred.dias_sin_rotar}d · por vencer
            </span>
          ) : (
            <span className="font-mono text-xs text-muted-foreground">
              hace {cred.dias_sin_rotar}d
            </span>
          )}
        </div>
      </div>

      {mostrarBarra && (
        <div className="flex items-center gap-2 px-3.5 pb-3">
          {cred.puede_revelar ? (
            <>
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
            </>
          ) : (
            <span className="text-xs text-muted-foreground">
              Oculta — no tiene permiso para revelarla.
            </span>
          )}

          {gestionable && (
            <div className="ml-auto flex items-center gap-1">
              {cred.rotacion_vencida && (
                <Button size="sm" variant="destructive" asChild>
                  <Link href={`/credenciales/${cred.id}/editar`}>
                    <RefreshCw /> Rotar
                  </Link>
                </Button>
              )}
              <Button size="icon-sm" variant="ghost" title="Editar" asChild>
                <Link href={`/credenciales/${cred.id}/editar`}>
                  <Pencil />
                </Link>
              </Button>
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button size="icon-sm" variant="ghost" title="Eliminar">
                    <Trash2 className="text-destructive" />
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>¿Eliminar esta credencial?</AlertDialogTitle>
                    <AlertDialogDescription>
                      Se eliminará la credencial de <strong>{cred.usuario_acceso}</strong> (
                      {cred.servicio}) y su historial. Esta acción no se puede deshacer.
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>Cancelar</AlertDialogCancel>
                    <AlertDialogAction onClick={eliminar}>Eliminar</AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            </div>
          )}
        </div>
      )}

      {revelada !== null && (
        <div className="px-3.5 pb-3.5">
          <div className="flex items-center gap-2 rounded-lg border bg-muted px-3 py-2 font-mono text-[13px] break-all">
            <LockOpen className="size-3.5 shrink-0 text-muted-foreground" />
            <span className="min-w-0 flex-1">
              {usuarioRev}: {revelada}
            </span>
            {restante !== null && (
              <span className="shrink-0 text-2xs text-muted-foreground tabular-nums">
                se oculta en {restante}s
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
