"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Plus, Search, SearchX, Wallet } from "lucide-react";
import { api } from "@/lib/api";
import type { VaultEntrada } from "@/lib/types";
import { ETIQUETAS_CATEGORIA_VAULT } from "@/lib/constants";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { PageSkeleton } from "@/components/ui/page-skeleton";
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

  if (entradas === null) {
    return (
      <div className="max-w-3xl">
        <PageSkeleton variante="tabla" />
      </div>
    );
  }

  return (
    <div className="max-w-3xl">
      <PageHeader
        titulo="Mi vault personal"
        descripcion="Sus contraseñas de servicios, aplicaciones o cuentas propias, separadas del inventario. Solo usted las ve y las revela: ni el administrador accede a su contenido."
        acciones={
          <Button asChild>
            <Link href="/vault/nueva">
              <Plus /> Nueva entrada
            </Link>
          </Button>
        }
      />

      {entradas.length === 0 ? (
        <EmptyState
          icono={Wallet}
          titulo="Su vault está vacío"
          descripcion="Guarde su primera contraseña personal con «Nueva entrada»."
          accion={
            <Button asChild variant="outline">
              <Link href="/vault/nueva">
                <Plus /> Nueva entrada
              </Link>
            </Button>
          }
        />
      ) : (
        <div className="flex flex-col gap-3">
          <div className="relative">
            <Search className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Filtrar por título, usuario o categoría…"
              className="pl-9"
            />
          </div>
          {filtradas.map((e, i) => (
            <div key={e.id} className="anim-rise" style={{ "--stagger": i } as React.CSSProperties}>
              <VaultItem entrada={e} onCambio={cargar} />
            </div>
          ))}
          {filtradas.length === 0 && (
            <EmptyState compacto icono={SearchX} titulo="Sin coincidencias" />
          )}
        </div>
      )}
    </div>
  );
}
