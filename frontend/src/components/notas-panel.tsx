"use client";

import { useRef, useState } from "react";
import { Eye, EyeOff, Loader2, NotebookPen, Save } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { TipoActivo } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Nota segura</CardTitle>
        <CardDescription>
          Texto cifrado en reposo. Su revelado queda auditado y se oculta automáticamente.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {editando ? (
          <>
            <Textarea
              rows={6}
              value={borrador}
              onChange={(e) => setBorrador(e.target.value)}
              placeholder="Información sensible asociada a este activo…"
            />
            <div className="flex gap-2">
              <Button onClick={guardar} disabled={cargando}>
                {cargando ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
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
              <pre className="whitespace-pre-wrap rounded-md bg-muted p-3 text-sm">{contenido}</pre>
            )}
            <div className="flex flex-wrap gap-2">
              {tieneNotas && (
                <Button variant="outline" onClick={ver} disabled={cargando}>
                  {cargando ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : contenido !== null ? (
                    <EyeOff className="h-4 w-4" />
                  ) : (
                    <Eye className="h-4 w-4" />
                  )}
                  {contenido !== null ? "Ocultar nota" : "Ver nota"}
                </Button>
              )}
              {puedeGestionar && (
                <Button variant="outline" onClick={abrirEdicion} disabled={cargando}>
                  <NotebookPen className="h-4 w-4" /> {tieneNotas ? "Editar nota" : "Añadir nota"}
                </Button>
              )}
              {!tieneNotas && !puedeGestionar && (
                <p className="text-sm text-muted-foreground">Sin nota registrada.</p>
              )}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
