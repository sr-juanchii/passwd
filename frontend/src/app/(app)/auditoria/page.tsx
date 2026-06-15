"use client";

import { useCallback, useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, Download, Loader2 } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { AuditoriaPagina } from "@/lib/types";
import { useSession } from "@/lib/session";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
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

const TODAS = "_todas";

export default function AuditoriaPage() {
  const { puede } = useSession();

  // Filtros aplicados (los que disparan la consulta).
  const [filtroUsuario, setFiltroUsuario] = useState("");
  const [filtroAccion, setFiltroAccion] = useState("");
  const [pagina, setPagina] = useState(1);

  // Borrador del input de usuario (se aplica con el botón / Enter).
  const [textoUsuario, setTextoUsuario] = useState("");

  const [datos, setDatos] = useState<AuditoriaPagina | null>(null);
  const [cargando, setCargando] = useState(true);

  const cargar = useCallback(async () => {
    setCargando(true);
    try {
      const r = await api.auditoria({
        filtro_usuario: filtroUsuario || undefined,
        filtro_accion: filtroAccion || undefined,
        pagina,
      });
      setDatos(r);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "No se pudo cargar la bitácora.");
    } finally {
      setCargando(false);
    }
  }, [filtroUsuario, filtroAccion, pagina]);

  useEffect(() => {
    void cargar();
  }, [cargar]);

  function aplicarUsuario(e: React.FormEvent) {
    e.preventDefault();
    setPagina(1);
    setFiltroUsuario(textoUsuario.trim());
  }

  function cambiarAccion(valor: string) {
    setPagina(1);
    setFiltroAccion(valor === TODAS ? "" : valor);
  }

  function exportar() {
    window.open(
      api.auditoriaExportUrl({
        filtro_usuario: filtroUsuario || undefined,
        filtro_accion: filtroAccion || undefined,
      }),
    );
  }

  if (!puede("auditoria.ver")) {
    return (
      <div className="space-y-6">
        <PageHeader titulo="Bitácora de auditoría" />
        <p className="rounded-md border border-dashed p-10 text-center text-sm text-muted-foreground">
          No tiene permiso para ver la bitácora.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        titulo="Bitácora de auditoría"
        descripcion="Registro de acciones realizadas en el sistema."
        acciones={
          <Button variant="outline" onClick={exportar}>
            <Download className="h-4 w-4" /> Exportar CSV
          </Button>
        }
      />

      <div className="flex flex-wrap items-end gap-3">
        <form onSubmit={aplicarUsuario} className="flex items-end gap-2">
          <div className="space-y-2">
            <Label htmlFor="filtro-usuario">Usuario</Label>
            <Input
              id="filtro-usuario"
              placeholder="Filtrar por usuario…"
              value={textoUsuario}
              onChange={(e) => setTextoUsuario(e.target.value)}
            />
          </div>
          <Button type="submit" variant="outline">
            Filtrar
          </Button>
        </form>
        <div className="space-y-2">
          <Label htmlFor="filtro-accion">Acción</Label>
          <Select value={filtroAccion || TODAS} onValueChange={cambiarAccion}>
            <SelectTrigger id="filtro-accion" className="w-56">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={TODAS}>Todas</SelectItem>
              {datos?.acciones.map((a) => (
                <SelectItem key={a} value={a}>
                  {a}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {cargando ? (
        <div className="flex items-center justify-center p-10">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : !datos || datos.registros.length === 0 ? (
        <p className="rounded-md border border-dashed p-10 text-center text-sm text-muted-foreground">
          No hay registros que coincidan con los filtros.
        </p>
      ) : (
        <>
          <div className="rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Fecha</TableHead>
                  <TableHead>Usuario</TableHead>
                  <TableHead>Acción</TableHead>
                  <TableHead>Objeto</TableHead>
                  <TableHead>Detalle</TableHead>
                  <TableHead>IP</TableHead>
                  <TableHead>Resultado</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {datos.registros.map((r) => (
                  <TableRow key={r.id}>
                    <TableCell className="whitespace-nowrap">
                      {new Date(r.fecha).toLocaleString()}
                    </TableCell>
                    <TableCell className="font-mono">{r.usuario || "—"}</TableCell>
                    <TableCell>
                      <Badge variant="secondary">{r.accion}</Badge>
                    </TableCell>
                    <TableCell>
                      {r.objeto_tipo ? `${r.objeto_tipo}${r.objeto_id ? ` #${r.objeto_id}` : ""}` : "—"}
                    </TableCell>
                    <TableCell className="max-w-[20rem] truncate" title={r.detalle}>
                      {r.detalle || "—"}
                    </TableCell>
                    <TableCell className="font-mono">{r.direccion_ip || "—"}</TableCell>
                    <TableCell>
                      {r.exito ? (
                        <Badge className="bg-green-600 text-white hover:bg-green-600/90">Éxito</Badge>
                      ) : (
                        <Badge variant="destructive">Fallo</Badge>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          <div className="flex items-center justify-between">
            <span className="text-sm text-muted-foreground">
              Página {datos.pagina} de {datos.total_paginas}
            </span>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={datos.pagina <= 1}
                onClick={() => setPagina((p) => Math.max(1, p - 1))}
              >
                <ChevronLeft className="h-4 w-4" /> Anterior
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={datos.pagina >= datos.total_paginas}
                onClick={() => setPagina((p) => p + 1)}
              >
                Siguiente <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
