"use client";

import { useRef, useState } from "react";
import { Eye, EyeOff, Loader2, Lock, NotebookPen, Save } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { TipoActivo } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { SectionHeader } from "@/components/ui/section-header";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";

const OCULTAR_MS = 30_000;

export function NotasPanel({
  tipo,
  activoId,
  tieneNotas,
  puedeGestionar,
}: {
  tipo: TipoActivo;
  activoId: number;
  tieneNotas: boolean;
  puedeGestionar: boolean;
}) {
  const [contenido, setContenido] = useState<string | null>(null);
  const [editando, setEditando] = useState(false);
  const [borrador, setBorrador] = useState("");
  const [cargando, setCargando] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  function ocultar() {
    if (timer.current) clearTimeout(timer.current);
    setContenido(null);
  }

  async function ver() {
    if (contenido !== null) {
      ocultar();
      return;
    }
    setCargando(true);
    try {
      const r = await api.revelarNotas(tipo, activoId);
      setContenido(r.notas || "(sin contenido)");
      timer.current = setTimeout(ocultar, OCULTAR_MS);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "No se pudo revelar la nota.");
    } finally {
      setCargando(false);
    }
  }

  async function abrirEdicion() {
    setCargando(true);
    try {
      const r = tieneNotas ? await api.revelarNotas(tipo, activoId) : { notas: "" };
      setBorrador(r.notas || "");
      setEditando(true);
      ocultar();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "No se pudo cargar la nota.");
    } finally {
      setCargando(false);
    }
  }

  async function guardar() {
    setCargando(true);
    try {
      await api.guardarNotas(tipo, activoId, borrador);
      toast.success("Nota segura guardada.");
      setEditando(false);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "No se pudo guardar la nota.");
    } finally {
      setCargando(false);
    }
  }

  return (
    <section className="overflow-hidden rounded-xl border bg-card">
      <div className="flex flex-col gap-1 border-b px-5 py-3.5">
        <SectionHeader icono={Lock} titulo="Nota segura" />
        <p className="text-[12px] text-muted-foreground">
          Texto cifrado en reposo. Su revelado queda auditado y se oculta automáticamente.
        </p>
      </div>
      <div className="flex flex-col gap-3 p-5">
        {editando ? (
          <>
            <Textarea
              rows={6}
              value={borrador}
              onChange={(e) => setBorrador(e.target.value)}
              placeholder="Información sensible asociada a este activo…"
              className="font-mono text-[13px]"
            />
            <div className="flex gap-2">
              <Button onClick={guardar} disabled={cargando}>
                {cargando ? <Loader2 className="animate-spin" /> : <Save />}
                Guardar
              </Button>
              <Button variant="ghost" onClick={() => setEditando(false)} disabled={cargando}>
                Cancelar
              </Button>
            </div>
          </>
        ) : (
          <>
            {contenido !== null && (
              <pre className="rounded-lg border bg-muted p-3 font-mono text-[13px] break-words whitespace-pre-wrap">
                {contenido}
              </pre>
            )}
            {tieneNotas || puedeGestionar ? (
              <div className="flex flex-wrap gap-2">
                {tieneNotas && (
                  <Button variant="outline" onClick={ver} disabled={cargando}>
                    {cargando ? (
                      <Loader2 className="animate-spin" />
                    ) : contenido !== null ? (
                      <EyeOff />
                    ) : (
                      <Eye />
                    )}
                    {contenido !== null ? "Ocultar nota" : "Ver nota"}
                  </Button>
                )}
                {puedeGestionar && (
                  <Button variant="outline" onClick={abrirEdicion} disabled={cargando}>
                    <NotebookPen /> {tieneNotas ? "Editar nota" : "Añadir nota"}
                  </Button>
                )}
              </div>
            ) : (
              <EmptyState
                compacto
                icono={Lock}
                titulo="Sin nota registrada"
                descripcion="Este activo no tiene una nota segura registrada."
              />
            )}
          </>
        )}
      </div>
    </section>
  );
}
