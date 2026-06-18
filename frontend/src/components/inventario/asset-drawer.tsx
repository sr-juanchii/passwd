"use client";

import Link from "next/link";
import {
  ArrowUpRight,
  Cpu,
  MonitorSmartphone,
  Plus,
  ScrollText,
  Server,
  TriangleAlert,
} from "lucide-react";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Chip } from "@/components/ui/chip";
import { Eyebrow, Mono } from "@/components/ui/mono";
import { RiskDot } from "@/components/risk-dot";
import { EstadoBadge } from "@/components/estado-badge";
import { CredItem } from "@/components/inventario/cred-item";
import type { ActivoInv } from "@/lib/inventario";
import { alertas, nivelActivo } from "@/lib/riesgo";
import { ETIQUETAS_TIPO_ACTIVO, rutaActivo } from "@/lib/constants";

const ICONO = { fisico: Server, hipervisor: Cpu, vm: MonitorSmartphone } as const;

export function AssetDrawer({
  asset,
  puedeGestionar,
  onOpenChange,
  onOpenVm,
}: {
  asset: ActivoInv | null;
  puedeGestionar: boolean;
  onOpenChange: (open: boolean) => void;
  onOpenVm: (vm: ActivoInv) => void;
}) {
  if (!asset) return null;
  const Icono = ICONO[asset.tipo];
  const vencidas = alertas(asset);
  const props: [string, string][] = [];
  if (asset.ip) props.push(["IP de gestión", asset.ip]);
  if (asset.plataforma) props.push(["Plataforma", asset.plataforma]);
  if (asset.so) props.push(["Sistema operativo", asset.so]);

  return (
    <Sheet open={!!asset} onOpenChange={onOpenChange}>
      <SheetContent className="w-full gap-0 p-0 sm:max-w-[560px]">
        <SheetHeader className="gap-3 border-b p-5">
          <div className="flex items-start gap-3 pr-8">
            <div className="flex size-10 items-center justify-center rounded-[10px] bg-muted">
              <Icono className="size-[19px] text-foreground" />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <RiskDot nivel={nivelActivo(asset)} size={7} />
                <SheetTitle className="truncate font-mono text-lg font-semibold tracking-[0.01em]">
                  {asset.nombre}
                </SheetTitle>
              </div>
              <div className="mt-0.5 text-[12.5px] text-muted-foreground">
                {ETIQUETAS_TIPO_ACTIVO[asset.tipo]}
              </div>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <EstadoBadge estado={asset.estado} />
            {(asset.etiquetas ?? []).map((t) => (
              <Chip key={t} tono="outline">
                {t}
              </Chip>
            ))}
            {vencidas > 0 && (
              <Badge variant="destructive" className="gap-1">
                <TriangleAlert /> {vencidas} vencida(s)
              </Badge>
            )}
          </div>
        </SheetHeader>

        <div className="flex-1 overflow-y-auto p-5">
          {props.length > 0 && (
            <div className="mb-6 grid grid-cols-[120px_1fr] gap-x-4 gap-y-2 text-[13px]">
              {props.map(([k, v]) => (
                <div key={k} className="contents">
                  <div className="text-[12.5px] text-muted-foreground">{k}</div>
                  <div className="font-mono">{v}</div>
                </div>
              ))}
            </div>
          )}

          <div className="mb-3 flex items-center justify-between">
            <Eyebrow>Credenciales · {asset.credenciales.length}</Eyebrow>
            {puedeGestionar && (
              <Button size="sm" asChild>
                <Link href={`/credenciales/nueva?activo=${asset.tipo}&activo_id=${asset.id}`}>
                  <Plus /> Nueva credencial
                </Link>
              </Button>
            )}
          </div>

          {asset.credenciales.length === 0 ? (
            <p className="rounded-[10px] border border-dashed p-6 text-center text-[13px] text-muted-foreground">
              No hay credenciales registradas para este activo.
            </p>
          ) : (
            <div className="flex flex-col gap-2.5">
              {asset.credenciales.map((c) => (
                <CredItem key={c.id} cred={c} />
              ))}
            </div>
          )}

          {asset.vms && asset.vms.length > 0 && (
            <div className="mt-6">
              <Eyebrow className="mb-3">Máquinas virtuales · {asset.vms.length}</Eyebrow>
              <div className="flex flex-col gap-1.5">
                {asset.vms.map((v) => (
                  <button
                    key={v.id}
                    type="button"
                    onClick={() => onOpenVm(v)}
                    className="flex items-center gap-2.5 rounded-[9px] border bg-background px-3 py-2.5 text-left transition-colors hover:bg-muted"
                  >
                    <RiskDot nivel={nivelActivo(v)} size={7} />
                    <MonitorSmartphone className="size-[15px] text-muted-foreground" />
                    <Mono className="text-[13px] font-medium">{v.nombre}</Mono>
                    {v.so && <span className="text-[11.5px] text-muted-foreground">{v.so}</span>}
                    <span className="ml-auto font-mono text-[11.5px] text-muted-foreground">
                      {v.credenciales.length} cred.
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="mt-6 flex items-center justify-between gap-3 border-t pt-4">
            <p className="flex items-start gap-2 text-[11.5px] leading-snug text-muted-foreground">
              <ScrollText className="mt-px size-3.5 shrink-0" />
              Cada revelado y copiado queda registrado con usuario, IP y hora. El portapapeles se
              limpia a los 30 s.
            </p>
            <Button variant="outline" size="sm" asChild className="shrink-0">
              <Link href={rutaActivo(asset.tipo, asset.id)}>
                Ficha completa <ArrowUpRight />
              </Link>
            </Button>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
