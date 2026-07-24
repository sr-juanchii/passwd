"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { Pencil } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { DispositivoDetalle } from "@/lib/types";
import { PageHeader } from "@/components/page-header";
import { Propiedades } from "@/components/propiedades";
import { CredencialesTabla } from "@/components/credenciales-tabla";
import { NotasPanel } from "@/components/notas-panel";
import { AccesosPanel } from "@/components/accesos-panel";
import { BotonEliminar } from "@/components/boton-eliminar";
import { ErrorRecurso } from "@/components/error-recurso";
import { TituloActivo } from "@/components/inventario/titulo-activo";
import { RestringidoBadge } from "@/components/restringido-badge";
import { Chip } from "@/components/ui/chip";
import { Button } from "@/components/ui/button";
import { PageSkeleton } from "@/components/ui/page-skeleton";
import { nivelActivo } from "@/lib/riesgo";
import { toast } from "sonner";

export default function DispositivoDetallePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const did = Number(id);
  const [d, setD] = useState<DispositivoDetalle | null>(null);
  const [error, setError] = useState<string | null>(null);

  const cargar = useCallback(async () => {
    try {
      setError(null);
      setD(await api.dispositivoDetalle(did));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "No se pudo cargar el dispositivo.");
    }
  }, [did]);

  useEffect(() => {
    void cargar();
  }, [cargar]);

  if (error) {
    return <ErrorRecurso titulo="Dispositivo no disponible" mensaje={error} />;
  }
  if (!d) {
    return <PageSkeleton variante="ficha" />;
  }

  async function eliminar() {
    try {
      await api.eliminarDispositivo(did);
      toast.success("Dispositivo eliminado.");
      router.push("/dispositivos");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "No se pudo eliminar.");
    }
  }

  return (
    <>
      <PageHeader
        titulo={
          <TituloActivo
            tipo="dispositivo"
            nombre={d.nombre}
            estado={d.estado}
            nivel={nivelActivo({ credenciales: d.credenciales })}
            extra={d.restringido ? <RestringidoBadge /> : undefined}
          />
        }
        descripcion={d.descripcion}
        migas={[
          { label: "Inventario", href: "/" },
          { label: "Dispositivos de red", href: "/dispositivos" },
          { label: d.nombre },
        ]}
        acciones={
          d.puede_gestionar && (
            <>
              <Button variant="outline" asChild>
                <Link href={`/dispositivos/${did}/editar`}>
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
          titulo="Información del dispositivo"
          items={[
            { etiqueta: "Tipo de dispositivo", valor: d.tipo_dispositivo_label },
            { etiqueta: "Marca / Modelo", valor: d.marca_modelo },
            { etiqueta: "Firmware / versión", valor: d.version, mono: true },
            { etiqueta: "IP de gestión", valor: d.ip_gestion, mono: true },
            { etiqueta: "Ubicación", valor: d.ubicacion },
            { etiqueta: "Puertos", valor: d.puertos, mono: true },
            { etiqueta: "Número de serie", valor: d.numero_serie, mono: true },
            { etiqueta: "Garantía hasta", valor: d.garantia_hasta, mono: true },
            { etiqueta: "Proveedor", valor: d.proveedor },
            {
              etiqueta: "Etiquetas",
              valor:
                d.lista_etiquetas.length > 0 ? (
                  <span className="flex flex-wrap gap-1.5">
                    {d.lista_etiquetas.map((t) => (
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
          tipo="dispositivo"
          activoId={did}
          onCambio={cargar}
        />

        <NotasPanel
          tipo="dispositivo"
          activoId={did}
          tieneNotas={d.tiene_notas}
          puedeGestionar={d.puede_gestionar}
        />

        {d.puede_gestionar_accesos && d.accesos && d.analistas && (
          <AccesosPanel
            tipo="dispositivo"
            activoId={did}
            accesos={d.accesos}
            analistas={d.analistas}
            onCambio={cargar}
          />
        )}
      </div>
    </>
  );
}
