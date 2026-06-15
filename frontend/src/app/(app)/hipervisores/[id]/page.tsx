"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { Loader2, MonitorSmartphone, Pencil, Plus } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { HipervisorDetalle } from "@/lib/types";
import { rutaActivo } from "@/lib/constants";
import { PageHeader } from "@/components/page-header";
import { EstadoBadge } from "@/components/estado-badge";
import { Propiedades } from "@/components/propiedades";
import { CredencialesTabla } from "@/components/credenciales-tabla";
import { NotasPanel } from "@/components/notas-panel";
import { AccesosPanel } from "@/components/accesos-panel";
import { BotonEliminar } from "@/components/boton-eliminar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { toast } from "sonner";

export default function HipervisorDetallePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const hid = Number(id);
  const [d, setD] = useState<HipervisorDetalle | null>(null);

  const cargar = useCallback(async () => {
    try {
      setD(await api.hipervisor(hid));
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "No se pudo cargar el hipervisor.");
    }
  }, [hid]);

  useEffect(() => {
    void cargar();
  }, [cargar]);

  if (!d) {
    return (
      <div className="flex justify-center py-20">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  async function eliminar() {
    try {
      const r = await api.eliminarHipervisor(hid);
      toast.success("Hipervisor eliminado.");
      router.push(`/servidores/${r.servidor_fisico_id}`);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "No se pudo eliminar.");
    }
  }

  return (
    <>
      <PageHeader
        titulo={
          <span className="flex items-center gap-2">
            {d.nombre}
            {d.plataforma && <Badge variant="secondary">{d.plataforma}</Badge>}
            <EstadoBadge estado={d.estado} />
          </span>
        }
        descripcion={d.descripcion}
        migas={[
          { label: "Inventario", href: "/" },
          { label: d.servidor_fisico_nombre, href: `/servidores/${d.servidor_fisico_id}` },
          { label: d.nombre },
        ]}
        acciones={
          d.puede_gestionar && (
            <>
              <Button variant="outline" asChild>
                <Link href={`/hipervisores/${hid}/editar`}>
                  <Pencil className="h-4 w-4" /> Editar
                </Link>
              </Button>
              <BotonEliminar
                titulo={`¿Eliminar ${d.nombre}?`}
                descripcion="Se eliminarán también sus máquinas virtuales y credenciales asociadas. Esta acción no se puede deshacer."
                onConfirmar={eliminar}
              />
            </>
          )
        }
      />

      <div className="space-y-6">
        <Propiedades
          titulo="Información del hipervisor"
          items={[
            { etiqueta: "Plataforma", valor: d.plataforma },
            { etiqueta: "Versión", valor: d.version },
            { etiqueta: "IP de gestión", valor: d.ip_gestion },
            { etiqueta: "Servidor físico", valor: (
              <Link href={`/servidores/${d.servidor_fisico_id}`} className="hover:underline">
                {d.servidor_fisico_nombre}
              </Link>
            ) },
            {
              etiqueta: "Etiquetas",
              valor: d.etiquetas ? (
                <span className="flex flex-wrap gap-1">
                  {d.etiquetas.split(",").map((t) => t.trim()).filter(Boolean).map((t) => (
                    <Badge key={t} variant="secondary">
                      {t}
                    </Badge>
                  ))}
                </span>
              ) : (
                ""
              ),
            },
          ]}
        />

        <Card>
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <CardTitle className="text-base">Máquinas virtuales</CardTitle>
            {d.puede_gestionar && (
              <Button size="sm" asChild>
                <Link href={`/hipervisores/${hid}/vms/nueva`}>
                  <Plus className="h-4 w-4" /> Nueva VM
                </Link>
              </Button>
            )}
          </CardHeader>
          <CardContent>
            {d.vms.length === 0 ? (
              <p className="text-sm text-muted-foreground">Sin máquinas virtuales registradas.</p>
            ) : (
              <ul className="space-y-2">
                {d.vms.map((vm) => (
                  <li key={vm.id} className="flex items-center gap-2 rounded-md border p-2">
                    <MonitorSmartphone className="h-4 w-4 text-muted-foreground" />
                    <Link href={rutaActivo("vm", vm.id)} className="font-medium hover:underline">
                      {vm.nombre}
                    </Link>
                    {vm.sistema_operativo && (
                      <span className="text-sm text-muted-foreground">{vm.sistema_operativo}</span>
                    )}
                    <EstadoBadge estado={vm.estado} />
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <CredencialesTabla
          credenciales={d.credenciales}
          puedeGestionar={d.puede_gestionar}
          tipo="hipervisor"
          activoId={hid}
          onCambio={cargar}
        />

        <NotasPanel tipo="hipervisor" activoId={hid} tieneNotas={d.tiene_notas} puedeGestionar={d.puede_gestionar} />

        {d.puede_gestionar_accesos && d.accesos && d.analistas && (
          <AccesosPanel tipo="hipervisor" activoId={hid} accesos={d.accesos} analistas={d.analistas} onCambio={cargar} />
        )}
      </div>
    </>
  );
}
