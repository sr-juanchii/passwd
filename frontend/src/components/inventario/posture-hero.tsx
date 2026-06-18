"use client";

import { Cpu, GitCommitHorizontal, KeyRound, MonitorSmartphone, Server } from "lucide-react";
import { Chip } from "@/components/ui/chip";
import { Eyebrow, Mono } from "@/components/ui/mono";
import { RiskDot } from "@/components/risk-dot";
import { ETIQUETAS_TIPO_ACTIVO } from "@/lib/constants";
import type { ActivoInv, ItemRiesgo, Postura } from "@/lib/inventario";

function BarraPostura({ p }: { p: Postura }) {
  const total = p.total || 1;
  const seg = [
    { v: p.sanas, color: "var(--chart-2)", label: "Al día" },
    { v: p.proximas, color: "var(--chart-4)", label: "Por vencer" },
    { v: p.vencidas, color: "var(--destructive)", label: "Vencidas" },
  ];
  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex h-[11px] overflow-hidden rounded-md bg-muted">
        {seg.map(
          (s, i) =>
            s.v > 0 && (
              <div
                key={i}
                title={`${s.label}: ${s.v}`}
                style={{ width: `${(s.v / total) * 100}%`, background: s.color }}
              />
            ),
        )}
      </div>
      <div className="flex flex-wrap gap-4">
        {seg.map((s, i) => (
          <div key={i} className="flex items-center gap-1.5 text-[12.5px] text-muted-foreground">
            <span className="size-2 rounded-full" style={{ background: s.color }} />
            {s.label} <Mono className="font-semibold text-foreground">{s.v}</Mono>
          </div>
        ))}
      </div>
    </div>
  );
}

export function PostureHero({
  postura,
  colaRiesgo,
  onOpen,
}: {
  postura: Postura;
  colaRiesgo: ItemRiesgo[];
  onOpen: (a: ActivoInv) => void;
}) {
  const acento = postura.vencidas > 0;
  const head = acento
    ? {
        n: postura.vencidas,
        t:
          postura.vencidas === 1
            ? "credencial requiere rotación"
            : "credenciales requieren rotación",
      }
    : { n: postura.proximas, t: "credenciales por vencer este mes" };

  const micro: [React.ReactNode, number, string][] = [
    [<Server key="s" className="size-4" />, postura.servidores, "Servidores"],
    [<Cpu key="h" className="size-4" />, postura.hipervisores, "Hipervisores"],
    [<MonitorSmartphone key="v" className="size-4" />, postura.vms, "VMs"],
    [<KeyRound key="c" className="size-4" />, postura.total, "Credenciales"],
  ];

  return (
    <section className="grid items-stretch gap-4 lg:grid-cols-[1.5fr_1fr]">
      {/* Postura */}
      <div className="flex flex-col gap-5 rounded-[14px] border bg-card p-5">
        <div className="flex items-center justify-between">
          <Eyebrow>Postura de seguridad</Eyebrow>
          <Chip tono="outline" mono>
            <GitCommitHorizontal className="size-3" /> umbral {postura.umbralDias} días
          </Chip>
        </div>
        <div className="flex items-baseline gap-4">
          <span
            className="text-[60px] leading-[0.85] font-semibold tracking-[-0.03em] tabular-nums"
            style={{ color: acento ? "var(--destructive)" : "var(--foreground)" }}
          >
            {String(head.n).padStart(2, "0")}
          </span>
          <span className="max-w-[220px] text-[15.5px] leading-snug text-muted-foreground">
            {head.t}
          </span>
        </div>
        <BarraPostura p={postura} />
        <div className="mt-auto grid grid-cols-4 gap-px overflow-hidden rounded-[10px] border bg-border">
          {micro.map(([icono, v, l]) => (
            <div key={l} className="flex flex-col gap-1.5 bg-card px-3.5 py-3">
              <span className="text-muted-foreground">{icono}</span>
              <span className="text-[21px] leading-none font-semibold tabular-nums">{v}</span>
              <span className="text-[11.5px] text-muted-foreground">{l}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Cola de riesgo */}
      <div className="flex min-h-0 flex-col rounded-[14px] border bg-card">
        <div className="flex items-center justify-between px-5 pt-5 pb-3">
          <Eyebrow>Cola de riesgo</Eyebrow>
          <Chip mono>{colaRiesgo.length}</Chip>
        </div>
        <div className="flex max-h-[340px] flex-1 flex-col gap-1.5 overflow-y-auto px-5 pb-5">
          {colaRiesgo.length === 0 ? (
            <p className="py-8 text-center text-[13px] text-muted-foreground">
              Sin credenciales en riesgo. Todo al día.
            </p>
          ) : (
            colaRiesgo.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => onOpen(c.activo)}
                className="grid w-full grid-cols-[auto_1fr_auto] items-center gap-3 rounded-[9px] border bg-background px-2.5 py-2.5 text-left transition-colors hover:border-foreground/20 hover:bg-muted"
              >
                <RiskDot nivel={c.vencida ? "vencida" : "proxima"} />
                <div className="min-w-0">
                  <div className="truncate text-[13px] font-medium">
                    <Mono>{c.usuario}</Mono>
                    <span className="text-muted-foreground"> @ </span>
                    <Mono>{c.host}</Mono>
                  </div>
                  <div className="mt-px text-[11.5px] text-muted-foreground">
                    {ETIQUETAS_TIPO_ACTIVO[c.hostTipo]} · {c.servicio}
                  </div>
                </div>
                <span
                  className="font-mono text-[12.5px] font-semibold whitespace-nowrap"
                  style={{ color: c.vencida ? "var(--destructive)" : "var(--muted-foreground)" }}
                >
                  {c.dias}d
                </span>
              </button>
            ))
          )}
        </div>
      </div>
    </section>
  );
}
