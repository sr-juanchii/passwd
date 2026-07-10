"use client";

import { api } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { VaultForm } from "@/components/forms/vault-form";

export default function NuevaEntradaVaultPage() {
  return (
    <div className="max-w-3xl">
      <PageHeader
        titulo="Nueva entrada del vault"
        migas={[{ label: "Mi vault", href: "/vault" }, { label: "Nueva entrada" }]}
      />
      <VaultForm onGuardar={(v) => api.crearVault(v)} />
    </div>
  );
}
