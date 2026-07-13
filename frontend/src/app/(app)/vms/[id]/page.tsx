"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { Loader2, Pencil } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { VmDetalle } from "@/lib/types";
import { PageHeader } from "@/components/page-header";
import { Propiedades } from "@/components/propiedades";
import { CredencialesTabla } from "@/components/credenciales-tabla";
import { NotasPanel } from "@/components/notas-panel";
import { AccesosPanel } from "@/components/accesos-panel";
import { BotonEliminar } from "@/components/boton-eliminar";
import { ErrorRecurso } from "@/components/error-recurso";
import { TituloActivo } from "@/components/inventario/titulo-activo";
import { Chip } from "@/components/ui/chip";
import { Mono } from "@/components/ui/mono";
import { Button } from "@/components/ui/button";
import { nivelActivo } from "@/lib/riesgo";
import { toast } from "sonner";

export default function VmDetallePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const vid = Number(id);
  const [d, setD] = useState<VmDetalle | null>(null);
  const [error, setError] = useState<string | null>(null);

  const cargar = useCallback(async () => {
    try {
      setError(null);
      setD(await api.vm(vid));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "No se pudo cargar la VM.");
    }
  }, [vid]);

  useEffect(() => {
    void cargar();
  }, [cargar]);

  if (error) {
    return <ErrorRecurso titulo="Máquina virtual no disponible" mensaje={error} />;
  }
  if (!d) {
    return (
      <div className="flex justify-center py-20">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  async function eliminar() {
    try {
      const r = await api.eliminarVm(vid);
      toast.success("Máquina virtual eliminada.");
      router.push(`/hipervisores/${r.hipervisor_id}`);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "No se pudo eliminar.");
    }
  }

  return (
    <>
      <PageHeader
        titulo={
          <TituloActivo
            tipo="vm"
            nombre={d.nombre}
            estado={d.estado}
            nivel={nivelActivo({ credenciales: d.credenciales })}
          />
        }
        descripcion={d.descripcion}
        migas={[
          { label: "Inventario", href: "/" },
          { label: d.hipervisor_nombre, href: `/hipervisores/${d.hipervisor_id}` },
          { label: d.nombre },
        ]}
        acciones={
          d.puede_gestionar && (
            <>
              <Button variant="outline" asChild>
                <Link href={`/vms/${vid}/editar`}>
                  <Pencil /> Editar
                </Link>
              </Button>
              <BotonEliminar
                titulo={`¿Eliminar ${d.nombre}?`}
                descripcion="Se eliminarán también sus credenciales asociadas. Esta acción no se puede deshacer."
                onConfirmar={eliminar}
              />
            </>
          )
        }
      />

      <div className="space-y-6">
        <Propiedades
          titulo="Información de la máquina virtual"
          items={[
            { etiqueta: "Sistema operativo", valor: d.sistema_operativo },
            { etiqueta: "Dirección IP", valor: d.ip, mono: true },
            { etiqueta: "RAM asignada", valor: d.ram, mono: true },
            { etiqueta: "CPU asignada", valor: d.cpu, mono: true },
            { etiqueta: "Almacenamiento", valor: d.almacenamiento, mono: true },
            {
              etiqueta: "Hipervisor",
              valor: (
                <Link href={`/hipervisores/${d.hipervisor_id}`} className="hover:underline">
                  <Mono>{d.hipervisor_nombre}</Mono>
                </Link>
              ),
            },
            {
              etiqueta: "Etiquetas",
              valor: d.etiquetas ? (
                <span className="flex flex-wrap gap-1.5">
                  {d.etiquetas.split(",").map((t) => t.trim()).filter(Boolean).map((t) => (
                    <Chip key={t} tono="outline">
                      {t}
                    </Chip>
                  ))}
                </span>
              ) : (
                ""
              ),
            },
          ]}
        />

        <CredencialesTabla
          credenciales={d.credenciales}
          puedeGestionar={d.puede_gestionar}
          tipo="vm"
          activoId={vid}
          onCambio={cargar}
        />

        <NotasPanel tipo="vm" activoId={vid} tieneNotas={d.tiene_notas} puedeGestionar={d.puede_gestionar} />

        {d.puede_gestionar_accesos && d.accesos && d.analistas && (
          <AccesosPanel tipo="vm" activoId={vid} accesos={d.accesos} analistas={d.analistas} onCambio={cargar} />
        )}
      </div>
    </>
  );
}
