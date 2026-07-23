"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Boxes, Plus } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { Concesion, Dashboard } from "@/lib/types";
import { construirInventario, type ActivoInv } from "@/lib/inventario";
import { ETIQUETAS_TIPO_ACTIVO, rutaActivo } from "@/lib/constants";
import { PageHeader } from "@/components/page-header";
import { PostureHero } from "@/components/inventario/posture-hero";
import { Inventory } from "@/components/inventario/inventory";
import { AssetDrawer } from "@/components/inventario/asset-drawer";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Mono } from "@/components/ui/mono";
import { PageSkeleton } from "@/components/ui/page-skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { toast } from "sonner";

function VistaAnalista({ concesiones }: { concesiones: Concesion[] }) {
  if (concesiones.length === 0) {
    return (
      <EmptyState
        icono={Boxes}
        titulo="Sin accesos concedidos"
        descripcion="Aún no tiene accesos concedidos. Solicite acceso a un administrador."
      />
    );
  }
  return (
    <div className="overflow-hidden rounded-xl border bg-card">
      <Table>
        <TableHeader className="bg-muted">
          <TableRow>
            <TableHead>Activo</TableHead>
            <TableHead>Tipo</TableHead>
            <TableHead>Nivel</TableHead>
            <TableHead>Caduca</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {concesiones.map((c) => (
            <TableRow key={c.id}>
              <TableCell>
                <Link href={rutaActivo(c.tipo, c.activo_id)} className="hover:underline">
                  <Mono className="font-medium">{c.activo_nombre}</Mono>
                </Link>
              </TableCell>
              <TableCell>{ETIQUETAS_TIPO_ACTIVO[c.tipo]}</TableCell>
              <TableCell>
                <Badge variant={c.nivel === "ver_credenciales" ? "default" : "secondary"}>
                  {c.nivel_label}
                </Badge>
              </TableCell>
              <TableCell className="text-muted-foreground">
                {c.expira_en ? new Date(c.expira_en).toLocaleDateString() : "Sin caducidad"}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

export default function DashboardPage() {
  const { puede } = useSession();
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState("");
  const [asset, setAsset] = useState<ActivoInv | null>(null);
  const puedeGestionar = puede("inventario.gestionar");

  const cargar = useCallback(async () => {
    try {
      setData(await api.dashboard());
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "No se pudo cargar el inventario.";
      setError(msg);
      toast.error(msg);
    }
  }, []);

  useEffect(() => {
    void cargar();
  }, [cargar]);

  if (error && !data) {
    return <p className="text-sm text-destructive">{error}</p>;
  }
  if (!data) {
    return <PageSkeleton variante="hero" />;
  }

  if (data.es_analista) {
    return (
      <>
        <PageHeader titulo="Mi inventario" descripcion="Activos concedidos a su cuenta." />
        <VistaAnalista concesiones={data.concesiones} />
      </>
    );
  }

  const modelo = construirInventario(data);
  const vacio =
    modelo.servidores.length === 0 &&
    modelo.hipervisores.length === 0 &&
    modelo.dispositivos.length === 0;

  return (
    <>
      <PageHeader
        titulo="Inventario"
        descripcion="Servidores dedicados, hipervisores con sus máquinas virtuales y dispositivos de red."
        acciones={
          puedeGestionar && (
            <div className="flex flex-wrap gap-2">
              <Button asChild variant="outline">
                <Link href="/servidores/nuevo">
                  <Plus /> Servidor
                </Link>
              </Button>
              <Button asChild variant="outline">
                <Link href="/dispositivos/nuevo">
                  <Plus /> Dispositivo
                </Link>
              </Button>
              <Button asChild>
                <Link href="/hipervisores/nuevo">
                  <Plus /> Hipervisor
                </Link>
              </Button>
            </div>
          )
        }
      />

      <div className="flex flex-col gap-4">
        <PostureHero
          postura={modelo.postura}
          colaRiesgo={modelo.colaRiesgo}
          onOpen={setAsset}
        />
        {vacio ? (
          <EmptyState
            icono={Boxes}
            titulo="Aún no hay activos registrados"
            descripcion="Registre su primer servidor, hipervisor o dispositivo de red para empezar a inventariar sus credenciales."
            accion={
              puedeGestionar && (
                <div className="flex flex-wrap justify-center gap-2">
                  <Button asChild variant="outline">
                    <Link href="/servidores/nuevo">
                      <Plus /> Añadir servidor
                    </Link>
                  </Button>
                  <Button asChild variant="outline">
                    <Link href="/dispositivos/nuevo">
                      <Plus /> Añadir dispositivo
                    </Link>
                  </Button>
                  <Button asChild>
                    <Link href="/hipervisores/nuevo">
                      <Plus /> Añadir hipervisor
                    </Link>
                  </Button>
                </div>
              )
            }
          />
        ) : (
          <Inventory
            servidores={modelo.servidores}
            hipervisores={modelo.hipervisores}
            dispositivos={modelo.dispositivos}
            onOpen={setAsset}
          />
        )}
      </div>

      <AssetDrawer
        asset={asset}
        puedeGestionar={puedeGestionar}
        onOpenChange={(o) => !o && setAsset(null)}
        onOpenVm={setAsset}
      />
    </>
  );
}
