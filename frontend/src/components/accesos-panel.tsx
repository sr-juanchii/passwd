"use client";

import { useState } from "react";
import { Loader2, ShieldCheck, ShieldPlus, Trash2 } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { AnalistaRef, Concesion, NivelAcceso, TipoActivo } from "@/lib/types";
import { ETIQUETAS_NIVEL } from "@/lib/constants";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Mono } from "@/components/ui/mono";
import { SectionHeader } from "@/components/ui/section-header";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { toast } from "sonner";

export function AccesosPanel({
  tipo,
  activoId,
  accesos,
  analistas,
  onCambio,
}: {
  tipo: TipoActivo;
  activoId: number;
  accesos: Concesion[];
  analistas: AnalistaRef[];
  onCambio: () => void;
}) {
  const [usuarioId, setUsuarioId] = useState("");
  const [nivel, setNivel] = useState<NivelAcceso>("ver");
  const [expiraDias, setExpiraDias] = useState("");
  const [enviando, setEnviando] = useState(false);

  async function conceder(e: React.FormEvent) {
    e.preventDefault();
    if (!usuarioId) return;
    setEnviando(true);
    try {
      await api.conceder({
        usuario_id: Number(usuarioId),
        tipo,
        activo_id: activoId,
        nivel,
        expira_dias: expiraDias ? Number(expiraDias) : null,
      });
      toast.success("Acceso concedido.");
      setUsuarioId("");
      setExpiraDias("");
      onCambio();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "No se pudo conceder el acceso.");
    } finally {
      setEnviando(false);
    }
  }

  async function revocar(id: number) {
    try {
      await api.revocarAcceso(id);
      toast.success("Acceso revocado.");
      onCambio();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "No se pudo revocar.");
    }
  }

  return (
    <section className="overflow-hidden rounded-xl border bg-card">
      <div className="flex flex-col gap-1 border-b px-5 py-3.5">
        <SectionHeader
          icono={ShieldCheck}
          titulo="Control de acceso por objeto"
          contador={accesos.length}
        />
        <p className="text-[12px] text-muted-foreground">
          Conceda acceso a analistas sobre este activo. El acceso no se hereda a sus hijos.
        </p>
      </div>

      <div className="flex flex-col gap-4 p-5">
        {accesos.length === 0 ? (
          <EmptyState
            compacto
            icono={ShieldCheck}
            titulo="Sin accesos concedidos"
            descripcion="Ningún analista tiene acceso directo a este activo. Concédalo con el formulario inferior."
          />
        ) : (
          <div className="overflow-hidden rounded-xl border bg-card">
            <Table>
              <TableHeader className="bg-muted">
                <TableRow>
                  <TableHead>Analista</TableHead>
                  <TableHead>Nivel</TableHead>
                  <TableHead>Caduca</TableHead>
                  <TableHead className="text-right">Acción</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {accesos.map((a) => (
                  <TableRow key={a.id}>
                    <TableCell>
                      <Mono className="font-medium">{a.username}</Mono>
                      <span className="block text-xs text-muted-foreground">{a.nombre_completo}</span>
                    </TableCell>
                    <TableCell>
                      <Badge variant={a.nivel === "ver_credenciales" ? "default" : "secondary"}>
                        {a.nivel_label}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      {a.expira_en ? (
                        <span className={a.expirada ? "text-destructive" : "text-muted-foreground"}>
                          {new Date(a.expira_en).toLocaleDateString()}
                          {a.expirada && " · expirada"}
                        </span>
                      ) : (
                        <span className="text-muted-foreground">Sin caducidad</span>
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      <AlertDialog>
                        <AlertDialogTrigger asChild>
                          <Button size="icon-sm" variant="ghost" title="Revocar">
                            <Trash2 className="text-destructive" />
                          </Button>
                        </AlertDialogTrigger>
                        <AlertDialogContent>
                          <AlertDialogHeader>
                            <AlertDialogTitle>¿Revocar el acceso de {a.username}?</AlertDialogTitle>
                            <AlertDialogDescription>
                              <strong>{a.nombre_completo}</strong> perderá de inmediato su acceso «
                              {a.nivel_label}» sobre este activo. Podrá volver a concederlo cuando
                              lo necesite.
                            </AlertDialogDescription>
                          </AlertDialogHeader>
                          <AlertDialogFooter>
                            <AlertDialogCancel>Cancelar</AlertDialogCancel>
                            <AlertDialogAction variant="destructive" onClick={() => revocar(a.id)}>
                              Revocar acceso
                            </AlertDialogAction>
                          </AlertDialogFooter>
                        </AlertDialogContent>
                      </AlertDialog>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}

        <form onSubmit={conceder} className="grid gap-3 sm:grid-cols-[1fr_1fr_auto_auto] sm:items-end">
          <div className="space-y-1.5">
            <Label>Analista</Label>
            <Select value={usuarioId} onValueChange={setUsuarioId}>
              <SelectTrigger>
                <SelectValue placeholder="Seleccionar…" />
              </SelectTrigger>
              <SelectContent>
                {analistas.length === 0 ? (
                  <SelectItem value="_" disabled>
                    No hay analistas activos
                  </SelectItem>
                ) : (
                  analistas.map((a) => (
                    <SelectItem key={a.id} value={String(a.id)}>
                      {a.username} — {a.nombre_completo}
                    </SelectItem>
                  ))
                )}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label>Nivel</Label>
            <Select value={nivel} onValueChange={(v) => setNivel(v as NivelAcceso)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(Object.keys(ETIQUETAS_NIVEL) as NivelAcceso[]).map((n) => (
                  <SelectItem key={n} value={n}>
                    {ETIQUETAS_NIVEL[n]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label>Caduca (días)</Label>
            <Input
              type="number"
              min={1}
              placeholder="∞"
              className="w-24"
              value={expiraDias}
              onChange={(e) => setExpiraDias(e.target.value)}
            />
          </div>
          <Button type="submit" disabled={enviando || !usuarioId}>
            {enviando ? <Loader2 className="animate-spin" /> : <ShieldPlus />}
            Conceder
          </Button>
        </form>
      </div>
    </section>
  );
}
