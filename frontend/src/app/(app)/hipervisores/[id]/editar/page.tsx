"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { Loader2 } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { HipervisorDetalle } from "@/lib/types";
import { PageHeader } from "@/components/page-header";
import { HipervisorForm } from "@/components/forms/hipervisor-form";
import { ErrorRecurso } from "@/components/error-recurso";

export default function EditarHipervisorPage() {
  const { id } = useParams<{ id: string }>();
  const hid = Number(id);
  const [data, setData] = useState<HipervisorDetalle | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.hipervisor(hid).then(setData).catch((e) => {
      setError(e instanceof ApiError ? e.message : "No se pudo cargar el hipervisor.");
    });
  }, [hid]);

  if (error) {
    return <ErrorRecurso titulo="Hipervisor no disponible" mensaje={error} />;
  }
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
          { label: data.nombre, href: `/hipervisores/${hid}` },
          { label: "Editar" },
        ]}
      />
      <HipervisorForm
        inicial={data}
        puedeRestringir={data.puede_restringir}
        onGuardar={(v) => api.editarHipervisor(hid, v)}
      />
    </>
  );
}
