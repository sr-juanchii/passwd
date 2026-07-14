"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { SearchX } from "lucide-react";
import { api } from "@/lib/api";
import type { VaultEntrada } from "@/lib/types";
import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/ui/empty-state";
import { PageSkeleton } from "@/components/ui/page-skeleton";
import { VaultForm } from "@/components/forms/vault-form";

export default function EditarEntradaVaultPage() {
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const [entrada, setEntrada] = useState<VaultEntrada | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.vaultEntrada(id).then(setEntrada).catch(() => setError("No se encontró la entrada."));
  }, [id]);

  if (error) {
    return (
      <div className="max-w-3xl">
        <PageHeader titulo="Entrada del vault" migas={[{ label: "Mi vault", href: "/vault" }]} />
        <EmptyState icono={SearchX} titulo="Entrada no disponible" descripcion={error} />
      </div>
    );
  }

  if (!entrada) {
    return (
      <div className="max-w-3xl">
        <PageSkeleton variante="formulario" />
      </div>
    );
  }

  return (
    <div className="max-w-3xl">
      <PageHeader
        titulo="Editar entrada"
        migas={[{ label: "Mi vault", href: "/vault" }, { label: entrada.titulo }]}
      />
      <VaultForm
        edicion
        inicial={{
          titulo: entrada.titulo,
          usuario_acceso: entrada.usuario_acceso,
          url: entrada.url,
          categoria: entrada.categoria,
          notas: entrada.notas,
        }}
        onGuardar={(v) => api.editarVault(id, v)}
      />
    </div>
  );
}
