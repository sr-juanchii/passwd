"use client";

import { api } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { DispositivoForm } from "@/components/forms/dispositivo-form";

export default function NuevoDispositivoPage() {
  return (
    <>
      <PageHeader
        titulo="Nuevo dispositivo de red"
        migas={[
          { label: "Inventario", href: "/" },
          { label: "Dispositivos de red", href: "/dispositivos" },
          { label: "Nuevo dispositivo" },
        ]}
      />
      <DispositivoForm onGuardar={(v) => api.crearDispositivo(v)} />
    </>
  );
}
