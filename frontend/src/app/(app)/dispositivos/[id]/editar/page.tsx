"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { Loader2 } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { DispositivoDetalle } from "@/lib/types";
import { PageHeader } from "@/components/page-header";
import { DispositivoForm } from "@/components/forms/dispositivo-form";
import { ErrorRecurso } from "@/components/error-recurso";

export default function EditarDispositivoPage() {
  const { id } = useParams<{ id: string }>();
  const did = Number(id);
  const [data, setData] = useState<DispositivoDetalle | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.dispositivoDetalle(did).then(setData).catch((e) => {
      setError(e instanceof ApiError ? e.message : "No se pudo cargar el dispositivo.");
    });
  }, [did]);

  if (error) {
    return <ErrorRecurso titulo="Dispositivo no disponible" mensaje={error} />;
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
          { label: "Dispositivos de red", href: "/dispositivos" },
          { label: data.nombre, href: `/dispositivos/${did}` },
          { label: "Editar" },
        ]}
      />
      <DispositivoForm
        inicial={data}
        puedeRestringir={data.puede_restringir}
        onGuardar={(v) => api.editarDispositivo(did, v)}
      />
    </>
  );
}
