"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Network, Plus } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { Concesion, Dashboard } from "@/lib/types";
import { deDispositivo, type ActivoInv } from "@/lib/inventario";
import { alertas, nivelActivo, rangoUrgencia } from "@/lib/riesgo";
import { rutaActivo } from "@/lib/constants";
import { PageHeader } from "@/components/page-header";
import { AssetDrawer } from "@/components/inventario/asset-drawer";
import { EstadoBadge } from "@/components/estado-badge";
import { RestringidoBadge } from "@/components/restringido-badge";
import { RiskDot } from "@/components/risk-dot";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { EmptyState } from "@/components/ui/empty-state";
import { Eyebrow, Mono } from "@/components/ui/mono";
import { PageSkeleton } from "@/components/ui/page-skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

// Vista del analista: solo sus concesiones sobre dispositivos de red.
function VistaAnalista({ concesiones }: { concesiones: Concesion[] }) {
  const propias = concesiones.filter((c) => c.tipo === "dispositivo");
  if (propias.length === 0) {
    return (
      <EmptyState
        icono={Network}
        titulo="Sin accesos a dispositivos"
        descripcion="No tiene accesos concedidos sobre dispositivos de red. Solicítelos a un administrador."
      />
    );
  }
  return (
    <div className="overflow-hidden rounded-xl border bg-card">
      <Table>
        <TableHeader className="bg-muted">
          <TableRow>
            <TableHead>Dispositivo</TableHead>
            <TableHead>Nivel</TableHead>
            <TableHead>Caduca</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {propias.map((c) => (
            <TableRow key={c.id}>
              <TableCell>
                <Link href={rutaActivo(c.tipo, c.activo_id)} className="hover:underline">
                  <Mono className="font-medium">{c.activo_nombre}</Mono>
                </Link>
              </TableCell>
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

export default function DispositivosPage() {
  const { puede } = useSession();
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState("");
  const [asset, setAsset] = useState<ActivoInv | null>(null);
  const puedeGestionar = puede("inventario.gestionar");

  const cargar = useCallback(async () => {
    try {
      setData(await api.dashboard());
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "No se pudieron cargar los dispositivos.";
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
    return <PageSkeleton variante="tabla" />;
  }

  if (data.es_analista) {
    return (
      <>
        <PageHeader
          titulo="Dispositivos de red"
          descripcion="Dispositivos de red concedidos a su cuenta."
        />
        <VistaAnalista concesiones={data.concesiones} />
      </>
    );
  }

  const dispositivos = (data.dispositivos ?? [])
    .map(deDispositivo)
    .sort((a, b) => rangoUrgencia(b) - rangoUrgencia(a));

  const botonNuevo = (
    <Button asChild>
      <Link href="/dispositivos/nuevo">
        <Plus /> Nuevo dispositivo
      </Link>
    </Button>
  );

  return (
    <>
      <PageHeader
        titulo="Dispositivos de red"
        descripcion="Switches, routers, firewalls y demás electrónica de red con sus credenciales."
        migas={[{ label: "Inventario", href: "/" }, { label: "Dispositivos de red" }]}
        acciones={puedeGestionar && botonNuevo}
      />

      {dispositivos.length === 0 ? (
        <EmptyState
          icono={Network}
          titulo="Aún no hay dispositivos registrados"
          descripcion="Registre su primer dispositivo de red para empezar a inventariar sus credenciales."
          accion={puedeGestionar && botonNuevo}
        />
      ) : (
        <section className="overflow-hidden rounded-xl border bg-card">
          <div className="flex items-center gap-3 px-5 py-4">
            <Eyebrow>Dispositivos</Eyebrow>
            <span className="hidden text-xs text-muted-foreground sm:inline">
              ordenados por urgencia
            </span>
          </div>
          <div className="border-t">
            <Table>
              <TableHeader className="bg-muted">
                <TableRow>
                  <TableHead>Dispositivo</TableHead>
                  <TableHead>Tipo</TableHead>
                  <TableHead>IP gestión</TableHead>
                  <TableHead>Estado</TableHead>
                  <TableHead className="text-right">Credenciales</TableHead>
                  <TableHead className="text-right">Alertas</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {dispositivos.map((d) => {
                  const al = alertas(d);
                  return (
                    <TableRow
                      key={d.id}
                      onClick={() => setAsset(d)}
                      className={cn(
                        "cursor-pointer",
                        nivelActivo(d) === "vencida" && "bg-destructive/[0.05]",
                      )}
                    >
                      <TableCell>
                        <span className="inline-flex items-center gap-2">
                          <RiskDot nivel={nivelActivo(d)} size={7} />
                          <Network className="size-4 text-muted-foreground" />
                          <Mono className="font-medium">{d.nombre}</Mono>
                          {d.restringido && <RestringidoBadge compacto />}
                        </span>
                      </TableCell>
                      <TableCell>
                        <Chip tono="outline">{d.tipoDispositivo ?? "—"}</Chip>
                      </TableCell>
                      <TableCell>
                        <Mono className="text-muted-foreground">{d.ip || "—"}</Mono>
                      </TableCell>
                      <TableCell>
                        <EstadoBadge estado={d.estado} />
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {d.credenciales.length}
                      </TableCell>
                      <TableCell className="text-right">
                        {al > 0 ? (
                          <Badge variant="destructive">{al}</Badge>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        </section>
      )}

      <AssetDrawer
        asset={asset}
        puedeGestionar={puedeGestionar}
        onOpenChange={(o) => !o && setAsset(null)}
        onOpenVm={setAsset}
      />
    </>
  );
}
