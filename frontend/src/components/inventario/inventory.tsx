"use client";

import { useState } from "react";
import {
  ArrowRight,
  ChevronRight,
  Cpu,
  KeyRound,
  LayoutGrid,
  MonitorSmartphone,
  Rows3,
  Server,
  TableProperties,
  TriangleAlert,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Chip } from "@/components/ui/chip";
import { Eyebrow, Mono } from "@/components/ui/mono";
import { Segmented } from "@/components/ui/segmented";
import { RiskDot } from "@/components/risk-dot";
import { EstadoBadge } from "@/components/estado-badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { ActivoInv } from "@/lib/inventario";
import { alertas, nivelActivo, rangoUrgencia } from "@/lib/riesgo";
import { ETIQUETAS_TIPO_ACTIVO } from "@/lib/constants";
import { cn } from "@/lib/utils";

const ICONO = { fisico: Server, hipervisor: Cpu, vm: MonitorSmartphone } as const;

function tintRiesgo(a: ActivoInv): string {
  return nivelActivo(a) === "vencida" ? "bg-destructive/[0.05]" : "";
}

function CredCount({ a }: { a: ActivoInv }) {
  const al = alertas(a);
  return (
    <span className="inline-flex items-center gap-1.5 font-mono text-xs text-muted-foreground">
      <KeyRound className="size-3 text-muted-foreground" />
      {a.credenciales.length}
      {al > 0 && <span className="font-semibold text-destructive">· {al}!</span>}
    </span>
  );
}

function TreeRow({
  a,
  depth = 0,
  onOpen,
  expandable,
  expanded,
  onToggle,
}: {
  a: ActivoInv;
  depth?: number;
  onOpen: (a: ActivoInv) => void;
  expandable?: boolean;
  expanded?: boolean;
  onToggle?: () => void;
}) {
  const Icono = ICONO[a.tipo];
  return (
    <div
      onClick={() => onOpen(a)}
      className={cn(
        "group grid h-11 cursor-pointer grid-cols-[auto_1fr_auto] items-center gap-3 border-t px-3.5 transition-colors hover:bg-muted md:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_auto_auto_auto]",
        tintRiesgo(a),
      )}
      style={{ paddingLeft: 14 + depth * 24 }}
    >
      <div className="flex min-w-0 items-center gap-2.5">
        {expandable ? (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onToggle?.();
            }}
            className="flex shrink-0"
            aria-label={expanded ? "Contraer" : "Expandir"}
          >
            <ChevronRight
              className={cn(
                "size-[15px] text-muted-foreground transition-transform",
                expanded && "rotate-90",
              )}
            />
          </button>
        ) : (
          <span className="w-[15px] shrink-0" />
        )}
        <RiskDot nivel={nivelActivo(a)} />
        <Icono className="size-4 shrink-0 text-muted-foreground" />
        <Mono className="truncate text-[13.5px] font-medium">{a.nombre}</Mono>
      </div>
      <div className="hidden min-w-0 items-center gap-1.5 md:flex">
        <Chip tono="outline">{ETIQUETAS_TIPO_ACTIVO[a.tipo]}</Chip>
        {a.plataforma && <Chip>{a.plataforma}</Chip>}
        {a.so && <Chip>{a.so}</Chip>}
        {a.estado !== "activo" && <EstadoBadge estado={a.estado} />}
      </div>
      <div className="hidden md:block">
        {a.ip ? (
          <Mono className="text-[12.5px] text-muted-foreground">{a.ip}</Mono>
        ) : (
          <span className="text-muted-foreground">—</span>
        )}
      </div>
      <CredCount a={a} />
      <Button
        size="sm"
        variant="ghost"
        className="opacity-40 transition-opacity group-hover:opacity-100"
        onClick={(e) => {
          e.stopPropagation();
          onOpen(a);
        }}
      >
        Abrir <ArrowRight />
      </Button>
    </div>
  );
}

function AssetCard({ a, onOpen }: { a: ActivoInv; onOpen: (a: ActivoInv) => void }) {
  const Icono = ICONO[a.tipo];
  const al = alertas(a);
  return (
    <button
      type="button"
      onClick={() => onOpen(a)}
      className={cn(
        "flex flex-col gap-3 rounded-xl border bg-card p-4 text-left transition-colors hover:border-foreground/20 hover:bg-muted",
        tintRiesgo(a),
      )}
    >
      <div className="flex items-start gap-2.5">
        <div className="flex size-[34px] shrink-0 items-center justify-center rounded-[9px] bg-muted">
          <Icono className="size-[17px] text-foreground" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <RiskDot nivel={nivelActivo(a)} size={7} />
            <Mono className="truncate text-[13.5px] font-semibold">{a.nombre}</Mono>
          </div>
          <div className="mt-0.5 text-[11.5px] text-muted-foreground">
            {ETIQUETAS_TIPO_ACTIVO[a.tipo]}
            {a.plataforma ? ` · ${a.plataforma}` : a.so ? ` · ${a.so}` : ""}
          </div>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {a.estado !== "activo" && <EstadoBadge estado={a.estado} />}
        {a.ip && (
          <Chip mono tono="outline">
            {a.ip}
          </Chip>
        )}
        {a.vms && (
          <Chip tono="outline">{a.vms.length} VM(s)</Chip>
        )}
      </div>
      <div className="flex items-center justify-between border-t pt-2.5">
        <span className="inline-flex items-center gap-1.5 font-mono text-xs text-muted-foreground">
          <KeyRound className="size-3" /> {a.credenciales.length} credenciales
        </span>
        {al > 0 ? (
          <Badge variant="destructive" className="gap-1">
            <TriangleAlert /> {al}
          </Badge>
        ) : (
          <span className="text-[11.5px] text-muted-foreground">Al día</span>
        )}
      </div>
    </button>
  );
}

export function Inventory({
  servidores,
  hipervisores,
  onOpen,
}: {
  servidores: ActivoInv[];
  hipervisores: ActivoInv[];
  onOpen: (a: ActivoInv) => void;
}) {
  const [filtro, setFiltro] = useState("todos");
  const [vista, setVista] = useState("arbol");
  const [exp, setExp] = useState<Record<number, boolean>>({});

  const show = (a: ActivoInv) =>
    filtro === "todos" ? true : filtro === "riesgo" ? nivelActivo(a) !== "ok" : a.tipo === filtro;

  const fisicos = servidores.filter(show).sort((a, b) => rangoUrgencia(b) - rangoUrgencia(a));
  const hyps =
    filtro === "fisico"
      ? []
      : hipervisores
          .filter((h) => filtro !== "riesgo" || rangoUrgencia(h) > 0)
          .sort((a, b) => rangoUrgencia(b) - rangoUrgencia(a));
  const vmVisible = (v: ActivoInv) => filtro !== "riesgo" || nivelActivo(v) !== "ok";
  const flat = [...fisicos, ...hyps.flatMap((h) => [h, ...(h.vms ?? []).filter(vmVisible)])];

  return (
    <section className="overflow-hidden rounded-[14px] border bg-card">
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
        <div className="flex items-center gap-3">
          <Eyebrow>Inventario</Eyebrow>
          <span className="hidden text-xs text-muted-foreground sm:inline">
            ordenado por urgencia
          </span>
        </div>
        <div className="flex items-center gap-2">
          <Segmented
            size="sm"
            value={filtro}
            onChange={setFiltro}
            options={[
              { valor: "todos", etiqueta: "Todo" },
              { valor: "riesgo", etiqueta: "En riesgo" },
              { valor: "fisico", etiqueta: "Servidores" },
              { valor: "hipervisor", etiqueta: "Hipervisores" },
            ]}
          />
          <Segmented
            size="sm"
            value={vista}
            onChange={setVista}
            options={[
              { valor: "arbol", icono: <Rows3 className="size-3.5" />, titulo: "Árbol" },
              { valor: "tabla", icono: <TableProperties className="size-3.5" />, titulo: "Tabla" },
              { valor: "tarjetas", icono: <LayoutGrid className="size-3.5" />, titulo: "Tarjetas" },
            ]}
          />
        </div>
      </div>

      {flat.length === 0 ? (
        <p className="border-t p-10 text-center text-sm text-muted-foreground">
          No hay activos que coincidan con el filtro.
        </p>
      ) : vista === "tabla" ? (
        <div className="border-t">
          <Table className="rounded-none shadow-none">
            <TableHeader>
              <TableRow>
                <TableHead>Activo</TableHead>
                <TableHead>Tipo</TableHead>
                <TableHead>IP gestión</TableHead>
                <TableHead>Estado</TableHead>
                <TableHead className="text-right">Credenciales</TableHead>
                <TableHead className="text-right">Alertas</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {flat.map((a) => {
                const al = alertas(a);
                return (
                  <TableRow
                    key={a.tipo + a.id}
                    onClick={() => onOpen(a)}
                    className={cn("cursor-pointer", tintRiesgo(a))}
                  >
                    <TableCell>
                      <span className="inline-flex items-center gap-2">
                        <RiskDot nivel={nivelActivo(a)} size={7} />
                        <Mono className="font-medium">
                          {a.parent && <span className="text-muted-foreground">{a.parent}/</span>}
                          {a.nombre}
                        </Mono>
                      </span>
                    </TableCell>
                    <TableCell>{ETIQUETAS_TIPO_ACTIVO[a.tipo]}</TableCell>
                    <TableCell>
                      <Mono className="text-muted-foreground">{a.ip || "—"}</Mono>
                    </TableCell>
                    <TableCell>
                      <EstadoBadge estado={a.estado} />
                    </TableCell>
                    <TableCell className="text-right font-mono">
                      {a.credenciales.length}
                    </TableCell>
                    <TableCell className="text-right">
                      {al > 0 ? (
                        <Badge variant="destructive">{al}</Badge>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      ) : vista === "tarjetas" ? (
        <div className="grid gap-3 border-t p-5 [grid-template-columns:repeat(auto-fill,minmax(248px,1fr))]">
          {flat.map((a) => (
            <AssetCard key={a.tipo + a.id} a={a} onOpen={onOpen} />
          ))}
        </div>
      ) : (
        <div>
          {fisicos.map((s) => (
            <TreeRow key={"f" + s.id} a={s} onOpen={onOpen} />
          ))}
          {hyps.map((h) => (
            <div key={"h" + h.id}>
              <TreeRow
                a={h}
                onOpen={onOpen}
                expandable
                expanded={!!exp[h.id]}
                onToggle={() => setExp((e) => ({ ...e, [h.id]: !e[h.id] }))}
              />
              {exp[h.id] &&
                (h.vms ?? [])
                  .filter(vmVisible)
                  .map((v) => <TreeRow key={"v" + v.id} a={v} depth={1} onOpen={onOpen} />)}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
