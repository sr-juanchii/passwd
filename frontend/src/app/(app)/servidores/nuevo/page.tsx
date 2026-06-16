"use client";

import { api } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { ServidorForm } from "@/components/forms/servidor-form";

export default function NuevoServidorPage() {
  return (
    <>
      <PageHeader
        titulo="Nuevo servidor físico"
        migas={[{ label: "Inventario", href: "/" }, { label: "Nuevo servidor" }]}
      />
      <ServidorForm onGuardar={(v) => api.crearServidor(v)} />
    </>
  );
}
