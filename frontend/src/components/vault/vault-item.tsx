"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  Check,
  Clipboard,
  Eye,
  EyeOff,
  Link as LinkIcon,
  Loader2,
  LockOpen,
  Pencil,
  Trash2,
} from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { VaultEntrada } from "@/lib/types";
import { ETIQUETAS_CATEGORIA_VAULT } from "@/lib/constants";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Mono } from "@/components/ui/mono";
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

// Entrada del vault personal: misma UX segura que una credencial (revelar /
// copiar auditados y con auto-ocultado), más editar / eliminar. La contraseña
// solo llega bajo demanda a /vault/{id}/revelar|copiar.
export function VaultItem({ entrada, onCambio }: { entrada: VaultEntrada; onCambio: () => void }) {
  const [revelada, setRevelada] = useState<string | null>(null);
  const [usuarioRev, setUsuarioRev] = useState<string | null>(null);
  const [cargando, setCargando] = useState<"revelar" | "copiar" | null>(null);
  const [copiada, setCopiada] = useState(false);
  const [restante, setRestante] = useState<number | null>(null);
  const tRevelar = useRef<ReturnType<typeof setTimeout> | null>(null);
  const tCopiar = useRef<ReturnType<typeof setTimeout> | null>(null);
  const tTick = useRef<ReturnType<typeof setInterval> | null>(null);

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
      const r = await api.revelarVault(entrada.id);
      setRevelada(r.password);
      setUsuarioRev(r.usuario);
      tRevelar.current = setTimeout(ocultar, OCULTAR_MS);
      // Contador solo visual; la autoridad sigue siendo el timeout de arriba.
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
      const r = await api.copiarVault(entrada.id);
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
      await api.eliminarVault(entrada.id);
      toast.success("Entrada eliminada.");
      onCambio();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "No se pudo eliminar.");
    }
  }

  return (
    <div
      className={
        "overflow-hidden rounded-lg border bg-background " +
        (entrada.rotacion_vencida ? "bg-destructive/[0.06]" : "")
      }
    >
      <div className="flex items-center gap-2.5 px-3.5 py-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[13.5px] font-semibold">{entrada.titulo}</span>
            <Chip tono="outline">{ETIQUETAS_CATEGORIA_VAULT[entrada.categoria]}</Chip>
            {entrada.usuario_acceso && <Mono className="text-xs">{entrada.usuario_acceso}</Mono>}
          </div>
          {entrada.url && (
            <a
              href={entrada.url}
              target="_blank"
              rel="noreferrer noopener"
              className="mt-0.5 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
            >
              <LinkIcon className="size-3" /> {entrada.url}
            </a>
          )}
          {entrada.notas && <div className="mt-0.5 text-xs text-muted-foreground">{entrada.notas}</div>}
        </div>
        <div className="text-right">
          {entrada.rotacion_vencida ? (
            <span className="font-mono text-xs font-semibold text-destructive">
              {entrada.dias_sin_rotar}d · vencida
            </span>
          ) : (
            <span className="font-mono text-xs text-muted-foreground">
              hace {entrada.dias_sin_rotar}d
            </span>
          )}
        </div>
      </div>

      <div className="flex items-center gap-2 px-3.5 pb-3">
        <Button size="sm" variant="outline" onClick={copiar} disabled={cargando !== null}>
          {cargando === "copiar" ? <Loader2 className="animate-spin" /> : copiada ? <Check /> : <Clipboard />}
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
        <div className="ml-auto flex items-center gap-1">
          <Button size="icon-sm" variant="ghost" title="Editar" asChild>
            <Link href={`/vault/${entrada.id}/editar`}>
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
                <AlertDialogTitle>¿Eliminar esta entrada?</AlertDialogTitle>
                <AlertDialogDescription>
                  Se eliminará <strong>{entrada.titulo}</strong> de su vault. Esta acción no se puede deshacer.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Cancelar</AlertDialogCancel>
                <AlertDialogAction variant="destructive" onClick={eliminar}>
                  Eliminar
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>
      </div>

      {revelada !== null && (
        <div className="px-3.5 pb-3.5">
          <div className="flex items-center gap-2 rounded-lg border bg-muted px-3 py-2 font-mono text-[13px] break-all">
            <LockOpen className="size-3.5 shrink-0 text-muted-foreground" />
            <span className="min-w-0 flex-1">
              {usuarioRev ? `${usuarioRev}: ` : ""}
              {revelada}
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
