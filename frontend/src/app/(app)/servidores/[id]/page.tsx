"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { Pencil } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { ServidorDetalle } from "@/lib/types";
import { PageHeader } from "@/components/page-header";
import { Propiedades } from "@/components/propiedades";
import { CredencialesTabla } from "@/components/credenciales-tabla";
import { NotasPanel } from "@/components/notas-panel";
import { AccesosPanel } from "@/components/accesos-panel";
import { BotonEliminar } from "@/components/boton-eliminar";
import { ErrorRecurso } from "@/components/error-recurso";
import { TituloActivo } from "@/components/inventario/titulo-activo";
import { Chip } from "@/components/ui/chip";
import { Button } from "@/components/ui/button";
import { PageSkeleton } from "@/components/ui/page-skeleton";
import { nivelActivo } from "@/lib/riesgo";
import { toast } from "sonner";

export default function ServidorDetallePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const sid = Number(id);
  const [d, setD] = useState<ServidorDetalle | null>(null);
  const [error, setError] = useState<string | null>(null);

  const cargar = useCallback(async () => {
    try {
      setError(null);
      setD(await api.servidor(sid));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "No se pudo cargar el servidor.");
    }
  }, [sid]);

  useEffect(() => {
    void cargar();
  }, [cargar]);

  if (error) {
    return <ErrorRecurso titulo="Servidor no disponible" mensaje={error} />;
  }
  if (!d) {
    return <PageSkeleton variante="ficha" />;
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

  return (
    <>
      <PageHeader
        titulo={
          <TituloActivo
            tipo="fisico"
            nombre={d.nombre}
            estado={d.estado}
            nivel={nivelActivo({ credenciales: d.credenciales })}
          />
        }
        descripcion={d.descripcion}
        migas={[{ label: "Inventario", href: "/" }, { label: d.nombre }]}
        acciones={
          d.puede_gestionar && (
            <>
              <Button variant="outline" asChild>
                <Link href={`/servidores/${sid}/editar`}>
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
          titulo="Información del servidor"
          items={[
            { etiqueta: "Sistema operativo", valor: d.sistema_operativo },
            { etiqueta: "Marca / Modelo", valor: d.marca_modelo },
            { etiqueta: "Ubicación", valor: d.ubicacion },
            { etiqueta: "IP de gestión", valor: d.ip_gestion, mono: true },
            { etiqueta: "RAM", valor: d.ram, mono: true },
            { etiqueta: "CPU", valor: d.cpu, mono: true },
            { etiqueta: "Almacenamiento", valor: d.almacenamiento, mono: true },
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
