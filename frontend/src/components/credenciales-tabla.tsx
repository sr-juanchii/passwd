"use client";

import Link from "next/link";
import { Plus } from "lucide-react";
import type { Credencial, TipoActivo } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Eyebrow } from "@/components/ui/mono";
import { CredItem } from "@/components/inventario/cred-item";

// Sección de credenciales de una ficha de activo. Conserva el nombre y la API
// del componente original, pero ahora presenta cada credencial como la tarjeta
// del rediseño (revelar / copiar / rotar / editar / eliminar) en lugar de una
// fila de tabla.
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
    <section className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <Eyebrow>Credenciales · {credenciales.length}</Eyebrow>
        {puedeGestionar && (
          <Button size="sm" asChild>
            <Link href={`/credenciales/nueva?activo=${tipo}&activo_id=${activoId}`}>
              <Plus /> Nueva credencial
            </Link>
          </Button>
        )}
      </div>
      {credenciales.length === 0 ? (
        <p className="rounded-[11px] border border-dashed p-6 text-center text-sm text-muted-foreground">
          No hay credenciales registradas para este activo.
        </p>
      ) : (
        <div className="flex flex-col gap-2.5">
          {credenciales.map((c) => (
            <CredItem key={c.id} cred={c} gestionable={puedeGestionar} onCambio={onCambio} />
          ))}
        </div>
      )}
    </section>
  );
}
