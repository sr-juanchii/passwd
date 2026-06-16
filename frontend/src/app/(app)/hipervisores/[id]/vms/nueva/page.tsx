"use client";

import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { VmForm } from "@/components/forms/vm-form";

export default function NuevaVmPage() {
  const { id } = useParams<{ id: string }>();
  const hid = Number(id);
  return (
    <>
      <PageHeader
        titulo="Nueva máquina virtual"
        migas={[
          { label: "Inventario", href: "/" },
          { label: "Hipervisor", href: `/hipervisores/${hid}` },
          { label: "Nueva VM" },
        ]}
      />
      <VmForm onGuardar={(v) => api.crearVm(hid, v)} />
    </>
  );
}
