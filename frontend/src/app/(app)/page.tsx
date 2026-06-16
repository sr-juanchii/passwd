"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  Boxes,
  ChevronRight,
  Cpu,
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

function alertasServidor(s: ServidorNodo): number {
  return s.credenciales.filter((c) => c.rotacion_vencida).length;
}

function alertasHipervisor(h: HipervisorNodo): number {
  let total = h.credenciales.filter((c) => c.rotacion_vencida).length;
  for (const v of h.vms) total += v.credenciales.filter((c) => c.rotacion_vencida).length;
  return total;
}

function TarjetaServidor({ s }: { s: ServidorNodo }) {
  const alertas = alertasServidor(s);
  return (
    <Card>
      <CardHeader className="flex-row items-center gap-2 space-y-0 py-3">
        <Server className="h-4 w-4 text-muted-foreground" />
        <Link href={rutaActivo("fisico", s.id)} className="flex-1 font-medium hover:underline">
          {s.nombre}
        </Link>
        <EstadoBadge estado={s.estado} />
        {alertas > 0 && (
          <Badge variant="destructive" className="gap-1">
            <TriangleAlert className="h-3 w-3" /> {alertas}
          </Badge>
        )}
        <CredCount n={s.credenciales.length} />
        {s.ip_gestion && <span className="hidden text-xs text-muted-foreground sm:inline">{s.ip_gestion}</span>}
      </CardHeader>
    </Card>
  );
}

function NodoHipervisor({ h }: { h: HipervisorNodo }) {
  const [abierto, setAbierto] = useState(false);
  const alertas = alertasHipervisor(h);
  return (
    <Card>
      <CardHeader className="flex-row items-center gap-2 space-y-0 py-3">
        <button
          onClick={() => setAbierto((v) => !v)}
          className="flex flex-1 items-center gap-2 text-left"
          aria-expanded={abierto}
        >
          <ChevronRight className={`h-4 w-4 transition-transform ${abierto ? "rotate-90" : ""}`} />
          <Cpu className="h-4 w-4 text-muted-foreground" />
          <span className="font-medium">{h.nombre}</span>
          {h.plataforma && <Badge variant="secondary">{h.plataforma}</Badge>}
          <EstadoBadge estado={h.estado} />
          {alertas > 0 && (
            <Badge variant="destructive" className="gap-1">
              <TriangleAlert className="h-3 w-3" /> {alertas}
            </Badge>
          )}
        </button>
        <span className="text-xs text-muted-foreground">{h.vms.length} VM(s)</span>
        <CredCount n={h.credenciales.length} />
        <Button size="sm" variant="ghost" asChild>
          <Link href={rutaActivo("hipervisor", h.id)}>Abrir</Link>
        </Button>
      </CardHeader>
      {abierto && (
        <CardContent className="space-y-1 pl-10">
          {h.ip_gestion && <p className="text-xs text-muted-foreground">Gestión: {h.ip_gestion}</p>}
          {h.vms.length === 0 ? (
            <p className="text-sm text-muted-foreground">Sin máquinas virtuales.</p>
          ) : (
            <ul className="space-y-1">
              {h.vms.map((v) => (
                <li key={v.id} className="flex items-center gap-2 text-sm">
                  <MonitorSmartphone className="h-3.5 w-3.5 text-muted-foreground" />
                  <Link href={rutaActivo("vm", v.id)} className="hover:underline">
                    {v.nombre}
                  </Link>
                  {v.sistema_operativo && (
                    <span className="text-xs text-muted-foreground">{v.sistema_operativo}</span>
                  )}
                  <CredCount n={v.credenciales.length} />
                </li>
              ))}
            </ul>
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
  const vacio = data.servidores.length === 0 && data.hipervisores.length === 0;
  return (
    <>
      <PageHeader
        titulo="Inventario"
        descripcion="Servidores dedicados e hipervisores con sus máquinas virtuales."
        acciones={
          puedeGestionar && (
            <div className="flex flex-wrap gap-2">
              <Button asChild variant="outline">
                <Link href="/servidores/nuevo">
                  <Plus className="h-4 w-4" /> Servidor dedicado
                </Link>
              </Button>
              <Button asChild>
                <Link href="/hipervisores/nuevo">
                  <Plus className="h-4 w-4" /> Hipervisor
                </Link>
              </Button>
            </div>
          )
        }
      />
      <div className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <TarjetaResumen icono={Server} etiqueta="Servidores dedicados" valor={r.servidores} />
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

      {vacio && (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
            <Boxes className="h-10 w-10 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">Aún no hay activos registrados.</p>
          </CardContent>
        </Card>
      )}

      <section className="mb-6 space-y-2">
        <h2 className="text-lg font-medium">Servidores dedicados</h2>
        {data.servidores.length === 0 ? (
          <p className="text-sm text-muted-foreground">No hay servidores dedicados.</p>
        ) : (
          data.servidores.map((s) => <TarjetaServidor key={s.id} s={s} />)
        )}
      </section>

      <section className="space-y-2">
        <h2 className="text-lg font-medium">Hipervisores</h2>
        {data.hipervisores.length === 0 ? (
          <p className="text-sm text-muted-foreground">No hay hipervisores.</p>
        ) : (
          data.hipervisores.map((h) => <NodoHipervisor key={h.id} h={h} />)
        )}
      </section>
    </>
  );
}
