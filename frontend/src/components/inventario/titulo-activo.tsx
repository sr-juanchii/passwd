import { Cpu, MonitorSmartphone, Network, Server } from "lucide-react";
import { Mono } from "@/components/ui/mono";
import { Chip } from "@/components/ui/chip";
import { RiskDot } from "@/components/risk-dot";
import { EstadoBadge } from "@/components/estado-badge";
import { ETIQUETAS_TIPO_ACTIVO } from "@/lib/constants";
import type { NivelRiesgo } from "@/lib/riesgo";
import type { EstadoActivo, TipoActivo } from "@/lib/types";

const ICONO = { fisico: Server, hipervisor: Cpu, vm: MonitorSmartphone, dispositivo: Network } as const;

// Título de ficha de activo: tile de icono + punto de riesgo + nombre en mono +
// chip de tipo + estado. Se usa como `titulo` del PageHeader en las páginas de
// detalle para que todas compartan la misma identidad visual.
export function TituloActivo({
  tipo,
  nombre,
  estado,
  nivel,
  extra,
}: {
  tipo: TipoActivo;
  nombre: string;
  estado: EstadoActivo;
  nivel?: NivelRiesgo;
  extra?: React.ReactNode;
}) {
  const Icono = ICONO[tipo];
  return (
    <span className="flex flex-wrap items-center gap-2.5">
      <span className="flex size-9 items-center justify-center rounded-lg bg-muted">
        <Icono className="size-[18px]" />
      </span>
      {nivel && <RiskDot nivel={nivel} size={8} />}
      <Mono className="text-2xl font-semibold tracking-[-0.01em]">{nombre}</Mono>
      <Chip tono="outline">{ETIQUETAS_TIPO_ACTIVO[tipo]}</Chip>
      <EstadoBadge estado={estado} />
      {extra}
    </span>
  );
}
