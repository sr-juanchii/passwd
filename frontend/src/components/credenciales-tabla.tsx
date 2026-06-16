"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { Clipboard, Eye, EyeOff, Loader2, Pencil, Plus, Trash2, TriangleAlert } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { Credencial, TipoActivo } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
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

function FilaCredencial({
  cred,
  puedeGestionar,
  onCambio,
}: {
  cred: Credencial;
  puedeGestionar: boolean;
  onCambio: () => void;
}) {
  const [revelada, setRevelada] = useState<string | null>(null);
  const [usuarioRevelado, setUsuarioRevelado] = useState<string | null>(null);
  const [cargando, setCargando] = useState<"revelar" | "copiar" | null>(null);
  const [copiada, setCopiada] = useState(false);
  const timerRevelar = useRef<ReturnType<typeof setTimeout> | null>(null);
  const timerCopiar = useRef<ReturnType<typeof setTimeout> | null>(null);

  function ocultar() {
    if (timerRevelar.current) clearTimeout(timerRevelar.current);
    setRevelada(null);
    setUsuarioRevelado(null);
  }

  async function revelar() {
    if (revelada !== null) {
      ocultar();
      return;
    }
    setCargando("revelar");
    try {
      const r = await api.revelarCredencial(cred.id);
      setRevelada(r.password);
      setUsuarioRevelado(r.usuario);
      timerRevelar.current = setTimeout(ocultar, OCULTAR_MS);
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
      if (timerCopiar.current) clearTimeout(timerCopiar.current);
      timerCopiar.current = setTimeout(async () => {
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
      onCambio();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "No se pudo eliminar.");
    }
  }

  return (
    <TableRow>
      <TableCell className="font-mono">{cred.usuario_acceso}</TableCell>
      <TableCell>{cred.servicio}</TableCell>
      <TableCell>{cred.puerto ?? "—"}</TableCell>
      <TableCell className="max-w-[16rem] truncate" title={cred.descripcion}>
        {cred.descripcion || "—"}
      </TableCell>
      <TableCell>
        {cred.rotacion_vencida ? (
          <Badge variant="destructive" className="gap-1">
            <TriangleAlert className="h-3 w-3" />
            {cred.dias_sin_rotar} días sin rotar
          </Badge>
        ) : (
          <span className="text-sm text-muted-foreground">hace {cred.dias_sin_rotar} día(s)</span>
        )}
      </TableCell>
      <TableCell>
        {cred.puede_revelar ? (
          <div className="flex flex-col gap-1">
            <div className="flex flex-wrap gap-1">
              <Button size="sm" variant="outline" onClick={copiar} disabled={cargando !== null}>
                {cargando === "copiar" ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Clipboard className="h-3.5 w-3.5" />
                )}
                {copiada ? "Copiada (30 s)" : "Copiar"}
              </Button>
              <Button size="sm" variant="outline" onClick={revelar} disabled={cargando !== null}>
                {cargando === "revelar" ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : revelada !== null ? (
                  <EyeOff className="h-3.5 w-3.5" />
                ) : (
                  <Eye className="h-3.5 w-3.5" />
                )}
                {revelada !== null ? "Ocultar" : "Revelar"}
              </Button>
            </div>
            {revelada !== null && (
              <code className="rounded bg-muted px-2 py-1 text-xs break-all">
                {usuarioRevelado}: {revelada}
              </code>
            )}
          </div>
        ) : (
          <span className="text-sm text-muted-foreground">Oculta (sin permiso)</span>
        )}
      </TableCell>
      {puedeGestionar && (
        <TableCell className="text-right">
          <div className="flex justify-end gap-1">
            <Button size="icon" variant="ghost" asChild title="Editar">
              <Link href={`/credenciales/${cred.id}/editar`}>
                <Pencil className="h-4 w-4" />
              </Link>
            </Button>
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button size="icon" variant="ghost" title="Eliminar">
                  <Trash2 className="h-4 w-4 text-destructive" />
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>¿Eliminar esta credencial?</AlertDialogTitle>
                  <AlertDialogDescription>
                    Se eliminará la credencial de <strong>{cred.usuario_acceso}</strong> ({cred.servicio})
                    y su historial. Esta acción no se puede deshacer.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Cancelar</AlertDialogCancel>
                  <AlertDialogAction onClick={eliminar}>Eliminar</AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </div>
        </TableCell>
      )}
    </TableRow>
  );
}

export function CredencialesTabla({
  credenciales,
  puedeGestionar,
  tipo,
  activoId,
  onCambio,
}: {
  credenciales: Credencial[];
  puedeGestionar: boolean;
  tipo: TipoActivo;
  activoId: number;
  onCambio: () => void;
}) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-medium">Credenciales</h2>
        {puedeGestionar && (
          <Button size="sm" asChild>
            <Link href={`/credenciales/nueva?activo=${tipo}&activo_id=${activoId}`}>
              <Plus className="h-4 w-4" /> Nueva credencial
            </Link>
          </Button>
        )}
      </div>
      {credenciales.length === 0 ? (
        <p className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">
          No hay credenciales registradas para este activo.
        </p>
      ) : (
        <div className="rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Usuario</TableHead>
                <TableHead>Servicio</TableHead>
                <TableHead>Puerto</TableHead>
                <TableHead>Descripción</TableHead>
                <TableHead>Rotación</TableHead>
                <TableHead>Contraseña</TableHead>
                {puedeGestionar && <TableHead className="text-right">Acciones</TableHead>}
              </TableRow>
            </TableHeader>
            <TableBody>
              {credenciales.map((c) => (
                <FilaCredencial key={c.id} cred={c} puedeGestionar={puedeGestionar} onCambio={onCambio} />
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
