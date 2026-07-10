"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import type { VaultEntrada } from "@/lib/types";
import { PageHeader } from "@/components/page-header";
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
        <p className="rounded-[14px] border border-dashed p-10 text-center text-sm text-muted-foreground">
          {error}
        </p>
      </div>
    );
  }

  if (!entrada) {
    return (
      <div className="flex justify-center py-16">
        <Loader2 className="size-6 animate-spin text-muted-foreground" />
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
