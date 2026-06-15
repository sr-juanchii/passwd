"use client";

import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { HipervisorForm } from "@/components/forms/hipervisor-form";

export default function NuevoHipervisorPage() {
  const { id } = useParams<{ id: string }>();
  const sid = Number(id);
  return (
    <>
      <PageHeader
        titulo="Nuevo hipervisor"
        migas={[
          { label: "Inventario", href: "/" },
          { label: "Servidor", href: `/servidores/${sid}` },
          { label: "Nuevo hipervisor" },
        ]}
      />
      <HipervisorForm onGuardar={(v) => api.crearHipervisor(sid, v)} />
    </>
  );
}
