"use client";

import Link from "next/link";
import { KeyRound, Plus } from "lucide-react";
import type { Credencial, TipoActivo } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { SectionHeader } from "@/components/ui/section-header";
import { CredItem } from "@/components/inventario/cred-item";

// Sección de credenciales de una ficha de activo. Conserva el nombre y la API
// del componente original, pero ahora presenta cada credencial como la tarjeta
// del rediseño (revelar / copiar / rotar / editar / eliminar) dentro de la
// misma tarjeta de sección que el resto de la ficha.
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
  const hrefNueva = `/credenciales/nueva?activo=${tipo}&activo_id=${activoId}`;
  const botonNueva = (
    <Button size="sm" asChild>
      <Link href={hrefNueva}>
        <Plus /> Nueva credencial
      </Link>
    </Button>
  );

  return (
    <section className="overflow-hidden rounded-xl border bg-card">
      <div className="border-b px-5 py-3.5">
        <SectionHeader
          icono={KeyRound}
          titulo="Credenciales"
          contador={credenciales.length}
          accion={puedeGestionar && credenciales.length > 0 ? botonNueva : undefined}
        />
      </div>
      <div className="p-5">
        {credenciales.length === 0 ? (
          <EmptyState
            compacto
            icono={KeyRound}
            titulo="Sin credenciales registradas"
            descripcion="Este activo aún no tiene credenciales cuya rotación vigilar."
            accion={puedeGestionar ? botonNueva : undefined}
          />
        ) : (
          <div className="flex flex-col gap-2.5">
            {credenciales.map((c) => (
              <CredItem key={c.id} cred={c} gestionable={puedeGestionar} onCambio={onCambio} />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
