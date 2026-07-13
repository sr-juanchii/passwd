"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Loader2, Plus, Search, Wallet } from "lucide-react";
import { api } from "@/lib/api";
import type { VaultEntrada } from "@/lib/types";
import { ETIQUETAS_CATEGORIA_VAULT } from "@/lib/constants";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { VaultItem } from "@/components/vault/vault-item";

export default function VaultPage() {
  const [entradas, setEntradas] = useState<VaultEntrada[] | null>(null);
  const [q, setQ] = useState("");

  const cargar = useCallback(() => {
    api.vault().then((d) => setEntradas(d.entradas)).catch(() => setEntradas([]));
  }, []);

  useEffect(() => {
    cargar();
  }, [cargar]);

  const filtradas = useMemo(() => {
    if (!entradas) return [];
    const t = q.trim().toLowerCase();
    if (!t) return entradas;
    return entradas.filter(
      (e) =>
        e.titulo.toLowerCase().includes(t) ||
        e.usuario_acceso.toLowerCase().includes(t) ||
        ETIQUETAS_CATEGORIA_VAULT[e.categoria].toLowerCase().includes(t),
    );
  }, [entradas, q]);

  return (
    <div className="max-w-3xl">
      <PageHeader
        titulo="Mi vault personal"
        descripcion="Tus contraseñas de servicios, aplicaciones o cuentas propias, separadas del inventario. Solo tú las ves y revelas: ni el administrador accede a su contenido."
        acciones={
          <Button asChild>
            <Link href="/vault/nueva">
              <Plus /> Nueva entrada
            </Link>
          </Button>
        }
      />

      {entradas === null ? (
        <div className="flex justify-center py-16">
          <Loader2 className="size-6 animate-spin text-muted-foreground" />
        </div>
      ) : entradas.length === 0 ? (
        <div className="rounded-[14px] border border-dashed p-10 text-center">
          <div className="mx-auto flex size-12 items-center justify-center rounded-xl bg-muted">
            <Wallet className="size-[22px] text-muted-foreground" />
          </div>
          <p className="mt-3.5 text-sm font-medium">Tu vault está vacío</p>
          <p className="text-[13px] text-muted-foreground">
            Guarda tu primera contraseña personal con «Nueva entrada».
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          <div className="relative">
            <Search className="absolute left-3 top-2.5 size-4 text-muted-foreground" />
            <Input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Filtrar por título, usuario o categoría…"
              className="pl-9"
            />
          </div>
          {filtradas.map((e) => (
            <VaultItem key={e.id} entrada={e} onCambio={cargar} />
          ))}
          {filtradas.length === 0 && (
            <p className="rounded-[11px] border border-dashed p-6 text-center text-sm text-muted-foreground">
              Sin coincidencias.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
