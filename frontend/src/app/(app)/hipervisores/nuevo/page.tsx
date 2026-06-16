"use client";

import { api } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { HipervisorForm } from "@/components/forms/hipervisor-form";

export default function NuevoHipervisorPage() {
  return (
    <>
      <PageHeader
        titulo="Nuevo hipervisor"
        descripcion="Máquina física que ejecuta un hipervisor y aloja máquinas virtuales."
        migas={[{ label: "Inventario", href: "/" }, { label: "Nuevo hipervisor" }]}
      />
      <HipervisorForm onGuardar={(v) => api.crearHipervisor(v)} />
    </>
  );
}
