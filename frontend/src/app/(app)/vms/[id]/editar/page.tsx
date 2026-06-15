"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { Loader2 } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { VmDetalle } from "@/lib/types";
import { PageHeader } from "@/components/page-header";
import { VmForm } from "@/components/forms/vm-form";
import { toast } from "sonner";

export default function EditarVmPage() {
  const { id } = useParams<{ id: string }>();
  const vid = Number(id);
  const [data, setData] = useState<VmDetalle | null>(null);

  useEffect(() => {
    api.vm(vid).then(setData).catch((e) => {
      toast.error(e instanceof ApiError ? e.message : "No se pudo cargar la VM.");
    });
  }, [vid]);

  if (!data) {
    return (
      <div className="flex justify-center py-20">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <>
      <PageHeader
        titulo={`Editar ${data.nombre}`}
        migas={[
          { label: "Inventario", href: "/" },
          { label: data.hipervisor_nombre, href: `/hipervisores/${data.hipervisor_id}` },
          { label: data.nombre, href: `/vms/${vid}` },
          { label: "Editar" },
        ]}
      />
      <VmForm inicial={data} onGuardar={(v) => api.editarVm(vid, v)} />
    </>
  );
}
