"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import type { TipoActivo } from "@/lib/types";
import { rutaActivo } from "@/lib/constants";
import { PageHeader } from "@/components/page-header";
import { CredencialForm } from "@/components/forms/credencial-form";

function Contenido() {
  const params = useSearchParams();
  const activo = (params.get("activo") || "fisico") as TipoActivo;
  const activoId = Number(params.get("activo_id") || 0);
  const destino = rutaActivo(activo, activoId);

  return (
    <>
      <PageHeader
        titulo="Nueva credencial"
        migas={[{ label: "Inventario", href: "/" }, { label: "Activo", href: destino }, { label: "Nueva credencial" }]}
      />
      <CredencialForm
        destinoOk={destino}
        onGuardar={(v) => api.crearCredencial({ activo, activo_id: activoId, ...v })}
      />
    </>
  );
}

export default function NuevaCredencialPage() {
  return (
    <Suspense>
      <Contenido />
    </Suspense>
  );
}
