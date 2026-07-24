"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { MonitorSmartphone, Pencil, Plus } from "lucide-react";
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
import { RestringidoBadge } from "@/components/restringido-badge";
import { RiskDot } from "@/components/risk-dot";
import { Chip } from "@/components/ui/chip";
import { EmptyState } from "@/components/ui/empty-state";
import { Mono } from "@/components/ui/mono";
import { Button } from "@/components/ui/button";
import { PageSkeleton } from "@/components/ui/page-skeleton";
import { SectionHeader } from "@/components/ui/section-header";
import { nivelActivo, type NivelRiesgo } from "@/lib/riesgo";
import { toast } from "sonner";

export default function HipervisorDetallePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const hid = Number(id);
  const [d, setD] = useState<HipervisorDetalle | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [nivelesVm, setNivelesVm] = useState<Record<number, NivelRiesgo>>({});

  const cargar = useCallback(async () => {
    try {
      setError(null);
      // El detalle no incluye las credenciales de cada VM; el árbol del
      // dashboard sí. De ahí sale el nivel de riesgo real de cada fila
      // (mismo criterio nivelActivo que el drawer del inventario). Si el
      // árbol no está disponible (analista, error), la fila queda sin señal
      // en lugar de fingir un "ok".
      const [det, dash] = await Promise.all([
        api.hipervisor(hid),
        api.dashboard().catch(() => null),
      ]);
      setD(det);
      if (dash && !dash.es_analista) {
        const nodo = dash.hipervisores.find((h) => h.id === hid);
        const niveles: Record<number, NivelRiesgo> = {};
        for (const v of nodo?.vms ?? []) niveles[v.id] = nivelActivo(v);
        setNivelesVm(niveles);
      }
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
    return <PageSkeleton variante="ficha" />;
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
            extra={
              <>
                {d.plataforma && <Chip>{d.plataforma}</Chip>}
                {d.restringido && <RestringidoBadge />}
              </>
            }
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

        <section className="overflow-hidden rounded-xl border bg-card">
          <div className="border-b px-5 py-3.5">
            <SectionHeader
              icono={MonitorSmartphone}
              titulo="Máquinas virtuales"
              contador={d.vms.length}
              accion={
                d.puede_gestionar && d.vms.length > 0 ? (
                  <Button size="sm" asChild>
                    <Link href={`/hipervisores/${hid}/vms/nueva`}>
                      <Plus /> Nueva VM
                    </Link>
                  </Button>
                ) : undefined
              }
            />
          </div>
          <div className="p-5">
            {d.vms.length === 0 ? (
              <EmptyState
                compacto
                icono={MonitorSmartphone}
                titulo="Sin máquinas virtuales"
                descripcion="Este hipervisor aún no tiene máquinas virtuales registradas."
                accion={
                  d.puede_gestionar ? (
                    <Button size="sm" asChild>
                      <Link href={`/hipervisores/${hid}/vms/nueva`}>
                        <Plus /> Nueva VM
                      </Link>
                    </Button>
                  ) : undefined
                }
              />
            ) : (
              <div className="flex flex-col gap-1.5">
                {d.vms.map((vm, i) => {
                  const nivelVm = nivelesVm[vm.id] as NivelRiesgo | undefined;
                  return (
                    <Link
                      key={vm.id}
                      href={rutaActivo("vm", vm.id)}
                      style={{ "--stagger": i } as React.CSSProperties}
                      className="anim-rise flex items-center gap-2.5 rounded-md border bg-background px-3 py-2.5 transition-colors hover:bg-muted"
                    >
                      {nivelVm !== undefined && <RiskDot nivel={nivelVm} size={7} />}
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
                  );
                })}
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
