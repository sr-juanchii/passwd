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
import { ErrorRecurso } from "@/components/error-recurso";
import { TituloActivo } from "@/components/inventario/titulo-activo";
import { RiskDot } from "@/components/risk-dot";
import { Chip } from "@/components/ui/chip";
import { Eyebrow, Mono } from "@/components/ui/mono";
import { Button } from "@/components/ui/button";
import { nivelActivo } from "@/lib/riesgo";
import { toast } from "sonner";

export default function HipervisorDetallePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const hid = Number(id);
  const [d, setD] = useState<HipervisorDetalle | null>(null);
  const [error, setError] = useState<string | null>(null);

  const cargar = useCallback(async () => {
    try {
      setError(null);
      setD(await api.hipervisor(hid));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "No se pudo cargar el hipervisor.");
    }
  }, [hid]);

  useEffect(() => {
    void cargar();
  }, [cargar]);

  if (error) {
    return <ErrorRecurso titulo="Hipervisor no disponible" mensaje={error} />;
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
      await api.eliminarHipervisor(hid);
      toast.success("Hipervisor eliminado.");
      router.push("/");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "No se pudo eliminar.");
    }
  }

  return (
    <>
      <PageHeader
        titulo={
          <TituloActivo
            tipo="hipervisor"
            nombre={d.nombre}
            estado={d.estado}
            nivel={nivelActivo({ credenciales: d.credenciales })}
            extra={d.plataforma ? <Chip>{d.plataforma}</Chip> : undefined}
          />
        }
        descripcion={d.descripcion}
        migas={[{ label: "Inventario", href: "/" }, { label: d.nombre }]}
        acciones={
          d.puede_gestionar && (
            <>
              <Button variant="outline" asChild>
                <Link href={`/hipervisores/${hid}/editar`}>
                  <Pencil /> Editar
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
            { etiqueta: "Versión", valor: d.version, mono: true },
            { etiqueta: "IP de gestión", valor: d.ip_gestion, mono: true },
            { etiqueta: "Marca / Modelo", valor: d.marca_modelo },
            { etiqueta: "Ubicación", valor: d.ubicacion },
            { etiqueta: "RAM", valor: d.ram, mono: true },
            { etiqueta: "CPU", valor: d.cpu, mono: true },
            { etiqueta: "Almacenamiento", valor: d.almacenamiento, mono: true },
            { etiqueta: "Número de serie", valor: d.numero_serie, mono: true },
            { etiqueta: "Garantía hasta", valor: d.garantia_hasta, mono: true },
            { etiqueta: "Proveedor", valor: d.proveedor },
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

        <section className="overflow-hidden rounded-[14px] border bg-card">
          <div className="flex items-center justify-between border-b px-5 py-3.5">
            <Eyebrow>Máquinas virtuales · {d.vms.length}</Eyebrow>
            {d.puede_gestionar && (
              <Button size="sm" asChild>
                <Link href={`/hipervisores/${hid}/vms/nueva`}>
                  <Plus /> Nueva VM
                </Link>
              </Button>
            )}
          </div>
          <div className="p-5">
            {d.vms.length === 0 ? (
              <p className="text-sm text-muted-foreground">Sin máquinas virtuales registradas.</p>
            ) : (
              <div className="flex flex-col gap-1.5">
                {d.vms.map((vm) => (
                  <Link
                    key={vm.id}
                    href={rutaActivo("vm", vm.id)}
                    className="flex items-center gap-2.5 rounded-[9px] border bg-background px-3 py-2.5 transition-colors hover:bg-muted"
                  >
                    <RiskDot nivel="ok" size={7} />
                    <MonitorSmartphone className="size-[15px] text-muted-foreground" />
                    <Mono className="text-[13px] font-medium">{vm.nombre}</Mono>
                    {vm.sistema_operativo && (
                      <span className="text-[11.5px] text-muted-foreground">
                        {vm.sistema_operativo}
                      </span>
                    )}
                    {vm.estado !== "activo" && (
                      <span className="ml-auto">
                        <EstadoBadge estado={vm.estado} />
                      </span>
                    )}
                  </Link>
                ))}
              </div>
            )}
          </div>
        </section>

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
