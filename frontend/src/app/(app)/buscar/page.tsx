"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Cpu, KeyRound, Loader2, MonitorSmartphone, Search, Server } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { ResultadoBusqueda, TipoActivo } from "@/lib/types";
import { ETIQUETAS_TIPO_ACTIVO, rutaActivo } from "@/lib/constants";
import { PageHeader } from "@/components/page-header";
import { EstadoBadge } from "@/components/estado-badge";
import { Input } from "@/components/ui/input";
import { Chip } from "@/components/ui/chip";
import { Mono } from "@/components/ui/mono";
import { toast } from "sonner";

const ICONO: Record<TipoActivo, typeof Server> = {
  fisico: Server,
  hipervisor: Cpu,
  vm: MonitorSmartphone,
};

function TarjetaActivo({
  tipo,
  id,
  nombre,
  meta,
  estado,
}: {
  tipo: TipoActivo;
  id: number;
  nombre: string;
  meta: string;
  estado: ResultadoBusqueda["servidores"][number]["estado"];
}) {
  const Icono = ICONO[tipo];
  return (
    <Link
      href={rutaActivo(tipo, id)}
      className="flex flex-col gap-2 rounded-[11px] border bg-card p-3.5 transition-colors hover:border-foreground/20 hover:bg-muted"
    >
      <div className="flex items-center gap-2">
        <Icono className="size-[15px] text-muted-foreground" />
        <Mono className="truncate text-[13.5px] font-semibold">{nombre}</Mono>
        {estado !== "activo" && <EstadoBadge estado={estado} />}
      </div>
      <span className="text-[11.5px] text-muted-foreground">
        {ETIQUETAS_TIPO_ACTIVO[tipo]}
        {meta ? ` · ${meta}` : ""}
      </span>
    </Link>
  );
}

function BuscarContenido() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const q = searchParams.get("q") ?? "";

  const [texto, setTexto] = useState(q);
  const [resultado, setResultado] = useState<ResultadoBusqueda | null>(null);
  const [cargando, setCargando] = useState(false);

  useEffect(() => {
    setTexto(q);
  }, [q]);

  useEffect(() => {
    const consulta = q.trim();
    if (!consulta) {
      setResultado(null);
      return;
    }
    let activo = true;
    setCargando(true);
    api
      .buscar(consulta)
      .then((r) => {
        if (activo) setResultado(r);
      })
      .catch((err) => {
        if (activo) toast.error(err instanceof ApiError ? err.message : "No se pudo buscar.");
      })
      .finally(() => {
        if (activo) setCargando(false);
      });
    return () => {
      activo = false;
    };
  }, [q]);

  function enviar(e: React.FormEvent) {
    e.preventDefault();
    const consulta = texto.trim();
    router.push(consulta ? `/buscar?q=${encodeURIComponent(consulta)}` : "/buscar");
  }

  const total =
    (resultado?.servidores.length ?? 0) +
    (resultado?.hipervisores.length ?? 0) +
    (resultado?.vms.length ?? 0) +
    (resultado?.credenciales.length ?? 0);

  return (
    <>
      <PageHeader
        titulo="Buscar"
        descripcion="Encuentre activos y credenciales en todo el inventario."
      />

      <form onSubmit={enviar} className="relative mb-4 max-w-xl">
        <Search className="pointer-events-none absolute top-1/2 left-3.5 size-[18px] -translate-y-1/2 text-muted-foreground" />
        <Input
          autoFocus
          value={texto}
          onChange={(e) => setTexto(e.target.value)}
          placeholder="Nombre, IP, usuario, servicio…"
          className="h-11 pl-11 text-[15px]"
        />
      </form>

      {!q.trim() ? (
        <div className="rounded-[12px] border border-dashed p-12 text-center">
          <Search className="mx-auto size-7 text-muted-foreground" />
          <p className="mt-2.5 text-[13.5px] text-muted-foreground">
            Escriba para buscar activos y credenciales.
          </p>
        </div>
      ) : cargando ? (
        <div className="flex items-center justify-center p-10">
          <Loader2 className="size-6 animate-spin text-muted-foreground" />
        </div>
      ) : total === 0 ? (
        <p className="rounded-[12px] border border-dashed p-10 text-center text-sm text-muted-foreground">
          Sin resultados para <strong>{q}</strong>.
        </p>
      ) : (
        resultado && (
          <div className="flex flex-col gap-5">
            <Mono className="text-[12.5px] text-muted-foreground">{total} resultado(s)</Mono>

            {(resultado.servidores.length > 0 ||
              resultado.hipervisores.length > 0 ||
              resultado.vms.length > 0) && (
              <div className="grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(248px,1fr))]">
                {resultado.servidores.map((s) => (
                  <TarjetaActivo
                    key={`f${s.id}`}
                    tipo="fisico"
                    id={s.id}
                    nombre={s.nombre}
                    meta={s.ip_gestion}
                    estado={s.estado}
                  />
                ))}
                {resultado.hipervisores.map((h) => (
                  <TarjetaActivo
                    key={`h${h.id}`}
                    tipo="hipervisor"
                    id={h.id}
                    nombre={h.nombre}
                    meta={h.plataforma || h.ip_gestion}
                    estado={h.estado}
                  />
                ))}
                {resultado.vms.map((v) => (
                  <TarjetaActivo
                    key={`v${v.id}`}
                    tipo="vm"
                    id={v.id}
                    nombre={v.nombre}
                    meta={v.sistema_operativo || v.ip}
                    estado={v.estado}
                  />
                ))}
              </div>
            )}

            {resultado.credenciales.length > 0 && (
              <div className="flex flex-col gap-2">
                <Mono className="text-[12.5px] text-muted-foreground">Credenciales</Mono>
                <div className="grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(248px,1fr))]">
                  {resultado.credenciales.map((c) => (
                    <Link
                      key={c.id}
                      href={rutaActivo(c.tipo_activo, c.activo_id)}
                      className="flex flex-col gap-2 rounded-[11px] border bg-card p-3.5 transition-colors hover:border-foreground/20 hover:bg-muted"
                    >
                      <div className="flex items-center gap-2">
                        <KeyRound className="size-[15px] text-muted-foreground" />
                        <Mono className="truncate text-[13.5px] font-semibold">
                          {c.usuario_acceso}
                        </Mono>
                        <Chip tono="outline">{c.servicio}</Chip>
                      </div>
                      <span className="text-[11.5px] text-muted-foreground">
                        {ETIQUETAS_TIPO_ACTIVO[c.tipo_activo]}
                        {c.puerto != null ? ` · :${c.puerto}` : ""}
                      </span>
                    </Link>
                  ))}
                </div>
              </div>
            )}
          </div>
        )
      )}
    </>
  );
}

export default function BuscarPage() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center p-10">
          <Loader2 className="size-6 animate-spin text-muted-foreground" />
        </div>
      }
    >
      <BuscarContenido />
    </Suspense>
  );
}
