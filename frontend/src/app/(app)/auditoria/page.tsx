"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Check,
  ChevronLeft,
  ChevronRight,
  Download,
  Loader2,
  Lock,
  ScrollText,
  Search,
  TriangleAlert,
} from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { AuditoriaPagina, RegistroAuditoria } from "@/lib/types";
import { useSession } from "@/lib/session";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Mono } from "@/components/ui/mono";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";

const TODAS = "_todas";

function agrupar(registros: RegistroAuditoria[]): [string, RegistroAuditoria[]][] {
  const mapa = new Map<string, RegistroAuditoria[]>();
  for (const r of registros) {
    const fecha = new Date(r.fecha).toLocaleDateString(undefined, {
      weekday: "long",
      day: "numeric",
      month: "long",
    });
    if (!mapa.has(fecha)) mapa.set(fecha, []);
    mapa.get(fecha)!.push(r);
  }
  return [...mapa.entries()];
}

function FilaAuditoria({ r }: { r: RegistroAuditoria }) {
  const hora = new Date(r.fecha).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const danger = !r.exito;
  return (
    <div className="grid grid-cols-[64px_30px_1fr_auto] items-center gap-3.5 border-b px-4 py-3 last:border-b-0">
      <Mono className="text-[12.5px] text-muted-foreground">{hora}</Mono>
      <div
        className={`flex size-[30px] items-center justify-center rounded-lg ${
          danger ? "bg-destructive/10 text-destructive" : "bg-muted text-muted-foreground"
        }`}
      >
        {danger ? <TriangleAlert className="size-[15px]" /> : <ScrollText className="size-[15px]" />}
      </div>
      <div className="min-w-0">
        <div className="text-[13px]">
          <Mono className="font-semibold">{r.usuario || "—"}</Mono>{" "}
          <span className="font-normal text-muted-foreground">· {r.accion}</span>
        </div>
        {(r.objeto_tipo || r.detalle) && (
          <Mono className="block truncate text-xs text-muted-foreground" title={r.detalle}>
            {r.objeto_tipo
              ? `${r.objeto_tipo}${r.objeto_id ? ` #${r.objeto_id}` : ""}`
              : ""}
            {r.objeto_tipo && r.detalle ? " · " : ""}
            {r.detalle}
          </Mono>
        )}
      </div>
      <div className="flex items-center gap-3">
        <Mono className="hidden text-xs text-muted-foreground sm:inline">
          {r.direccion_ip || "—"}
        </Mono>
        {r.exito ? (
          <Check className="size-[15px] text-muted-foreground" />
        ) : (
          <Badge variant="destructive">fallo</Badge>
        )}
      </div>
    </div>
  );
}

export default function AuditoriaPage() {
  const { puede } = useSession();
  const [filtroUsuario, setFiltroUsuario] = useState("");
  const [filtroAccion, setFiltroAccion] = useState("");
  const [pagina, setPagina] = useState(1);
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
      <>
        <PageHeader titulo="Auditoría" />
        <p className="rounded-[14px] border border-dashed p-10 text-center text-sm text-muted-foreground">
          No tiene permiso para ver la bitácora.
        </p>
      </>
    );
  }

  const grupos = datos ? agrupar(datos.registros) : [];

  return (
    <>
      <PageHeader
        titulo="Auditoría"
        descripcion="Bitácora inmutable de cada acción sobre el sistema."
        acciones={
          <Button variant="outline" onClick={exportar}>
            <Download /> Exportar CSV
          </Button>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-2.5">
        <form onSubmit={aplicarUsuario} className="relative max-w-sm min-w-52 flex-1">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-[15px] -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Filtrar por usuario…"
            className="pl-8"
            value={textoUsuario}
            onChange={(e) => setTextoUsuario(e.target.value)}
          />
        </form>
        <Select value={filtroAccion || TODAS} onValueChange={cambiarAccion}>
          <SelectTrigger className="w-56">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={TODAS}>Todas las acciones</SelectItem>
            {datos?.acciones.map((a) => (
              <SelectItem key={a} value={a}>
                {a}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {cargando ? (
        <div className="flex items-center justify-center p-10">
          <Loader2 className="size-6 animate-spin text-muted-foreground" />
        </div>
      ) : !datos || datos.registros.length === 0 ? (
        <p className="rounded-[14px] border border-dashed p-10 text-center text-sm text-muted-foreground">
          No hay registros que coincidan con los filtros.
        </p>
      ) : (
        <>
          <div className="overflow-hidden rounded-[14px] border bg-card">
            {grupos.map(([fecha, items]) => (
              <div key={fecha}>
                <div className="border-b bg-muted px-4 py-2.5 text-[11px] font-semibold tracking-[0.08em] text-muted-foreground uppercase">
                  {fecha}
                </div>
                {items.map((r) => (
                  <FilaAuditoria key={r.id} r={r} />
                ))}
              </div>
            ))}
            <div className="flex items-center gap-2 px-4 py-3 text-[11.5px] text-muted-foreground">
              <Lock className="size-3.5" />
              La bitácora es de solo anexado: ningún registro puede modificarse ni eliminarse.
            </div>
          </div>

          <div className="mt-4 flex items-center justify-between">
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
                <ChevronLeft /> Anterior
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={datos.pagina >= datos.total_paginas}
                onClick={() => setPagina((p) => p + 1)}
              >
                Siguiente <ChevronRight />
              </Button>
            </div>
          </div>
        </>
      )}
    </>
  );
}
