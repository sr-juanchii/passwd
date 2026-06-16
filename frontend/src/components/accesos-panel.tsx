"use client";

import { useState } from "react";
import { Loader2, ShieldPlus, Trash2 } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { AnalistaRef, Concesion, NivelAcceso, TipoActivo } from "@/lib/types";
import { ETIQUETAS_NIVEL } from "@/lib/constants";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Control de acceso por objeto</CardTitle>
        <CardDescription>
          Conceda acceso a analistas sobre este activo. El acceso no se hereda a sus hijos.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {accesos.length > 0 && (
          <div className="rounded-md border">
            <Table>
              <TableHeader>
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
                      {a.username}
                      <span className="block text-xs text-muted-foreground">{a.nombre_completo}</span>
                    </TableCell>
                    <TableCell>
                      <Badge variant={a.nivel === "ver_credenciales" ? "default" : "secondary"}>
                        {a.nivel_label}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      {a.expira_en ? (
                        <span className={a.expirada ? "text-destructive" : undefined}>
                          {new Date(a.expira_en).toLocaleDateString()}
                          {a.expirada && " (expirada)"}
                        </span>
                      ) : (
                        "Sin caducidad"
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button size="icon" variant="ghost" onClick={() => revocar(a.id)} title="Revocar">
                        <Trash2 className="h-4 w-4 text-destructive" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}

        <form onSubmit={conceder} className="grid gap-3 sm:grid-cols-[1fr_1fr_auto_auto] sm:items-end">
          <div className="space-y-1">
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
          <div className="space-y-1">
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
          <div className="space-y-1">
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
            {enviando ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldPlus className="h-4 w-4" />}
            Conceder
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
