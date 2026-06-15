"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { Cpu, Loader2, Pencil, Plus } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { ServidorDetalle } from "@/lib/types";
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

export default function ServidorDetallePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const sid = Number(id);
  const [d, setD] = useState<ServidorDetalle | null>(null);

  const cargar = useCallback(async () => {
    try {
      setD(await api.servidor(sid));
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "No se pudo cargar el servidor.");
    }
  }, [sid]);

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
      await api.eliminarServidor(sid);
      toast.success("Servidor eliminado.");
      router.push("/");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "No se pudo eliminar.");
    }
  }

  const esHost = d.tipo === "host_virtualizacion";

  return (
    <>
      <PageHeader
        titulo={
          <span className="flex items-center gap-2">
            {d.nombre}
            <Badge variant="outline">{d.etiqueta_tipo}</Badge>
            <EstadoBadge estado={d.estado} />
          </span>
        }
        descripcion={d.descripcion}
        migas={[{ label: "Inventario", href: "/" }, { label: d.nombre }]}
        acciones={
          d.puede_gestionar && (
            <>
              <Button variant="outline" asChild>
                <Link href={`/servidores/${sid}/editar`}>
                  <Pencil className="h-4 w-4" /> Editar
                </Link>
              </Button>
              <BotonEliminar
                titulo={`¿Eliminar ${d.nombre}?`}
                descripcion="Se eliminarán también sus hipervisores, VMs y credenciales asociadas. Esta acción no se puede deshacer."
                onConfirmar={eliminar}
              />
            </>
          )
        }
      />

      <div className="space-y-6">
        <Propiedades
          titulo="Información del servidor"
          items={[
            { etiqueta: "Sistema operativo", valor: d.sistema_operativo },
            { etiqueta: "Marca / Modelo", valor: d.marca_modelo },
            { etiqueta: "Ubicación", valor: d.ubicacion },
            { etiqueta: "IP de gestión", valor: d.ip_gestion },
            { etiqueta: "RAM", valor: d.ram },
            { etiqueta: "CPU", valor: d.cpu },
            { etiqueta: "Almacenamiento", valor: d.almacenamiento },
            { etiqueta: "Número de serie", valor: d.numero_serie },
            { etiqueta: "Garantía hasta", valor: d.garantia_hasta },
            { etiqueta: "Proveedor", valor: d.proveedor },
            {
              etiqueta: "Etiquetas",
              valor:
                d.lista_etiquetas.length > 0 ? (
                  <span className="flex flex-wrap gap-1">
                    {d.lista_etiquetas.map((t) => (
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

        {esHost && (
          <Card>
            <CardHeader className="flex-row items-center justify-between space-y-0">
              <CardTitle className="text-base">Hipervisores</CardTitle>
              {d.puede_gestionar && (
                <Button size="sm" asChild>
                  <Link href={`/servidores/${sid}/hipervisores/nuevo`}>
                    <Plus className="h-4 w-4" /> Nuevo hipervisor
                  </Link>
                </Button>
              )}
            </CardHeader>
            <CardContent>
              {d.hipervisores.length === 0 ? (
                <p className="text-sm text-muted-foreground">Sin hipervisores registrados.</p>
              ) : (
                <ul className="space-y-2">
                  {d.hipervisores.map((h) => (
                    <li key={h.id} className="flex items-center gap-2 rounded-md border p-2">
                      <Cpu className="h-4 w-4 text-muted-foreground" />
                      <Link href={rutaActivo("hipervisor", h.id)} className="font-medium hover:underline">
                        {h.nombre}
                      </Link>
                      {h.plataforma && <Badge variant="secondary">{h.plataforma}</Badge>}
                      <EstadoBadge estado={h.estado} />
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        )}

        <CredencialesTabla
          credenciales={d.credenciales}
          puedeGestionar={d.puede_gestionar}
          tipo="fisico"
          activoId={sid}
          onCambio={cargar}
        />

        <NotasPanel tipo="fisico" activoId={sid} tieneNotas={d.tiene_notas} puedeGestionar={d.puede_gestionar} />

        {d.puede_gestionar_accesos && d.accesos && d.analistas && (
          <AccesosPanel tipo="fisico" activoId={sid} accesos={d.accesos} analistas={d.analistas} onCambio={cargar} />
        )}
      </div>
    </>
  );
}
