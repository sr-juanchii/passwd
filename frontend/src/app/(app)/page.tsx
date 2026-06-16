"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  Boxes,
  ChevronRight,
  Cpu,
  HardDrive,
  KeyRound,
  Loader2,
  MonitorSmartphone,
  Plus,
  Server,
  TriangleAlert,
} from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { Concesion, Dashboard, HipervisorNodo, Resumen, ServidorNodo } from "@/lib/types";
import { ETIQUETAS_TIPO_ACTIVO, rutaActivo } from "@/lib/constants";
import { PageHeader } from "@/components/page-header";
import { EstadoBadge } from "@/components/estado-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { toast } from "sonner";

function TarjetaResumen({
  icono: Icono,
  etiqueta,
  valor,
  alerta,
}: {
  icono: React.ComponentType<{ className?: string }>;
  etiqueta: string;
  valor: number;
  alerta?: boolean;
}) {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 py-4">
        <div
          className={`flex h-10 w-10 items-center justify-center rounded-md ${
            alerta ? "bg-destructive/10 text-destructive" : "bg-primary/10 text-primary"
          }`}
        >
          <Icono className="h-5 w-5" />
        </div>
        <div>
          <p className="text-2xl font-semibold leading-none">{valor}</p>
          <p className="text-sm text-muted-foreground">{etiqueta}</p>
        </div>
      </CardContent>
    </Card>
  );
}

function CredCount({ n }: { n: number }) {
  return (
    <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
      <KeyRound className="h-3 w-3" /> {n}
    </span>
  );
}

function rotacionPendiente(nodo: ServidorNodo | HipervisorNodo): number {
  let total = nodo.credenciales.filter((c) => c.rotacion_vencida).length;
  if ("hipervisores" in nodo) {
    for (const h of nodo.hipervisores) total += rotacionPendiente(h);
  }
  if ("vms" in nodo) {
    for (const v of nodo.vms) total += v.credenciales.filter((c) => c.rotacion_vencida).length;
  }
  return total;
}

function NodoServidor({ s, puedeGestionar }: { s: ServidorNodo; puedeGestionar: boolean }) {
  const [abierto, setAbierto] = useState(false);
  const esHost = s.tipo === "host_virtualizacion";
  const alertas = rotacionPendiente(s);
  return (
    <Card>
      <CardHeader className="flex-row items-center gap-2 space-y-0 py-3">
        <button
          onClick={() => setAbierto((v) => !v)}
          className="flex flex-1 items-center gap-2 text-left"
          aria-expanded={abierto}
        >
          <ChevronRight className={`h-4 w-4 transition-transform ${abierto ? "rotate-90" : ""}`} />
          <Server className="h-4 w-4 text-muted-foreground" />
          <span className="font-medium">{s.nombre}</span>
          <Badge variant="outline">{s.etiqueta_tipo}</Badge>
          <EstadoBadge estado={s.estado} />
          {alertas > 0 && (
            <Badge variant="destructive" className="gap-1">
              <TriangleAlert className="h-3 w-3" /> {alertas}
            </Badge>
          )}
        </button>
        <CredCount n={s.credenciales.length} />
        <Button size="sm" variant="ghost" asChild>
          <Link href={rutaActivo("fisico", s.id)}>Abrir</Link>
        </Button>
      </CardHeader>
      {abierto && (
        <CardContent className="space-y-2 pl-10">
          {s.ip_gestion && (
            <p className="text-xs text-muted-foreground">Gestión: {s.ip_gestion}</p>
          )}
          {esHost && (
            <div className="space-y-1">
              {s.hipervisores.length === 0 && (
                <p className="text-sm text-muted-foreground">Sin hipervisores.</p>
              )}
              {s.hipervisores.map((h) => (
                <div key={h.id} className="rounded-md border p-2">
                  <div className="flex items-center gap-2">
                    <Cpu className="h-4 w-4 text-muted-foreground" />
                    <Link href={rutaActivo("hipervisor", h.id)} className="font-medium hover:underline">
                      {h.nombre}
                    </Link>
                    {h.plataforma && <Badge variant="secondary">{h.plataforma}</Badge>}
                    <EstadoBadge estado={h.estado} />
                    <CredCount n={h.credenciales.length} />
                  </div>
                  {h.vms.length > 0 && (
                    <ul className="mt-1 space-y-1 pl-6">
                      {h.vms.map((v) => (
                        <li key={v.id} className="flex items-center gap-2 text-sm">
                          <MonitorSmartphone className="h-3.5 w-3.5 text-muted-foreground" />
                          <Link href={rutaActivo("vm", v.id)} className="hover:underline">
                            {v.nombre}
                          </Link>
                          <CredCount n={v.credenciales.length} />
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              ))}
              {puedeGestionar && (
                <Button size="sm" variant="outline" asChild>
                  <Link href={`/servidores/${s.id}/hipervisores/nuevo`}>
                    <Plus className="h-3.5 w-3.5" /> Hipervisor
                  </Link>
                </Button>
              )}
            </div>
          )}
        </CardContent>
      )}
    </Card>
  );
}

function VistaAnalista({ concesiones }: { concesiones: Concesion[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Activos a los que tiene acceso</CardTitle>
      </CardHeader>
      <CardContent>
        {concesiones.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Aún no tiene accesos concedidos. Solicite acceso a un administrador.
          </p>
        ) : (
          <div className="rounded-md border">
            <Table>
              <TableHeader>
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
                      <Link href={rutaActivo(c.tipo, c.activo_id)} className="font-medium hover:underline">
                        {c.activo_nombre}
                      </Link>
                    </TableCell>
                    <TableCell>{ETIQUETAS_TIPO_ACTIVO[c.tipo]}</TableCell>
                    <TableCell>
                      <Badge variant={c.nivel === "ver_credenciales" ? "default" : "secondary"}>
                        {c.nivel_label}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      {c.expira_en ? new Date(c.expira_en).toLocaleDateString() : "Sin caducidad"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default function DashboardPage() {
  const { puede } = useSession();
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState("");
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
    return (
      <div className="flex justify-center py-20">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (data.es_analista) {
    return (
      <>
        <PageHeader titulo="Mi inventario" descripcion="Activos concedidos a su cuenta." />
        <VistaAnalista concesiones={data.concesiones} />
      </>
    );
  }

  const r: Resumen = data.resumen;
  return (
    <>
      <PageHeader
        titulo="Inventario"
        descripcion="Infraestructura de servidores, hipervisores y máquinas virtuales."
        acciones={
          puedeGestionar && (
            <Button asChild>
              <Link href="/servidores/nuevo">
                <Plus className="h-4 w-4" /> Nuevo servidor
              </Link>
            </Button>
          )
        }
      />
      <div className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <TarjetaResumen icono={Server} etiqueta="Servidores físicos" valor={r.servidores} />
        <TarjetaResumen icono={Cpu} etiqueta="Hipervisores" valor={r.hipervisores} />
        <TarjetaResumen icono={MonitorSmartphone} etiqueta="Máquinas virtuales" valor={r.vms} />
        <TarjetaResumen icono={KeyRound} etiqueta="Credenciales" valor={r.credenciales} />
        <TarjetaResumen
          icono={TriangleAlert}
          etiqueta="Rotación vencida"
          valor={r.rotacion_vencida}
          alerta={r.rotacion_vencida > 0}
        />
      </div>

      <div className="space-y-2">
        {data.arbol.length === 0 ? (
          <Card>
            <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
              <Boxes className="h-10 w-10 text-muted-foreground" />
              <p className="text-sm text-muted-foreground">
                Aún no hay servidores registrados.
              </p>
              {puedeGestionar && (
                <Button asChild>
                  <Link href="/servidores/nuevo">
                    <Plus className="h-4 w-4" /> Registrar el primero
                  </Link>
                </Button>
              )}
            </CardContent>
          </Card>
        ) : (
          data.arbol.map((s) => <NodoServidor key={s.id} s={s} puedeGestionar={puedeGestionar} />)
        )}
      </div>
    </>
  );
}
