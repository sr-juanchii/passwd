"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Activity,
  Clock,
  KeyRound,
  Loader2,
  Lock,
  ShieldAlert,
  TrendingUp,
} from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { Metricas } from "@/lib/types";
import { ETIQUETAS_TIPO_ACTIVO, rutaActivo } from "@/lib/constants";
import { useSession } from "@/lib/session";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Mono } from "@/components/ui/mono";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

function MetricTile({
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
    <div className="flex flex-col gap-2.5 rounded-[14px] border bg-card p-4">
      <div className="flex items-center justify-between">
        <span className="text-[12.5px] text-muted-foreground">{etiqueta}</span>
        <div
          className={cn(
            "flex size-[30px] items-center justify-center rounded-lg",
            alerta ? "bg-destructive/10 text-destructive" : "bg-muted text-muted-foreground",
          )}
        >
          <Icono className="size-4" />
        </div>
      </div>
      <span
        className={cn(
          "text-[28px] leading-none font-semibold tabular-nums",
          alerta && valor > 0 ? "text-destructive" : "text-foreground",
        )}
      >
        {valor}
      </span>
    </div>
  );
}

function CardPanel({
  icono: Icono,
  titulo,
  accion,
  className,
  children,
}: {
  icono: React.ComponentType<{ className?: string }>;
  titulo: string;
  accion?: React.ReactNode;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={cn("overflow-hidden rounded-[14px] border bg-card", className)}>
      <div className="flex items-center justify-between border-b px-4 py-3.5">
        <div className="flex items-center gap-2.5">
          <Icono className="size-4 text-muted-foreground" />
          <span className="text-sm font-semibold">{titulo}</span>
        </div>
        {accion}
      </div>
      <div className="p-4">{children}</div>
    </div>
  );
}

const vacio = (txt: string) => <p className="py-2 text-[13px] text-muted-foreground">{txt}</p>;

export default function MetricasPage() {
  const { puede } = useSession();
  const [datos, setDatos] = useState<Metricas | null>(null);
  const [cargando, setCargando] = useState(true);

  useEffect(() => {
    let activo = true;
    api
      .metricas()
      .then((r) => {
        if (activo) setDatos(r);
      })
      .catch((err) => {
        if (activo)
          toast.error(err instanceof ApiError ? err.message : "No se pudieron cargar las métricas.");
      })
      .finally(() => {
        if (activo) setCargando(false);
      });
    return () => {
      activo = false;
    };
  }, []);

  if (!puede("metricas.ver")) {
    return (
      <>
        <PageHeader titulo="Métricas" />
        <p className="rounded-[14px] border border-dashed p-10 text-center text-sm text-muted-foreground">
          No tiene permiso para ver las métricas.
        </p>
      </>
    );
  }

  if (cargando || !datos) {
    return (
      <>
        <PageHeader titulo="Métricas de seguridad" />
        <div className="flex items-center justify-center p-10">
          <Loader2 className="size-6 animate-spin text-muted-foreground" />
        </div>
      </>
    );
  }

  const maxAcc = Math.max(1, ...datos.top_accesos.map((t) => t.accesos));

  return (
    <>
      <PageHeader
        titulo="Métricas de seguridad"
        descripcion="Panel del estado de seguridad del inventario."
        acciones={
          <Button variant="outline" asChild>
            <Link href={api.auditoriaExportUrl({})} target="_blank">
              Ver bitácora
            </Link>
          </Button>
        }
      />

      <div className="flex flex-col gap-4">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          <MetricTile icono={Activity} etiqueta="Logins fallidos (24 h)" valor={datos.logins_fallidos_24h} />
          <MetricTile icono={Activity} etiqueta="Logins fallidos (7 d)" valor={datos.logins_fallidos_7d} />
          <MetricTile icono={KeyRound} etiqueta="Rotación vencida" valor={datos.rotacion_vencida.length} alerta />
          <MetricTile icono={ShieldAlert} etiqueta="Cuentas sin MFA" valor={datos.sin_mfa.length} alerta />
          <MetricTile icono={Lock} etiqueta="Usuarios bloqueados" valor={datos.bloqueados.length} alerta />
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          <CardPanel icono={KeyRound} titulo="Credenciales con rotación vencida">
            {datos.rotacion_vencida.length === 0 ? (
              vacio("Ninguna credencial vencida.")
            ) : (
              <Table className="rounded-none shadow-none">
                <TableHeader>
                  <TableRow>
                    <TableHead>Activo</TableHead>
                    <TableHead>Usuario</TableHead>
                    <TableHead className="text-right">Días</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {datos.rotacion_vencida.map((c) => (
                    <TableRow key={c.id}>
                      <TableCell>
                        <Link href={rutaActivo(c.tipo, c.id)} className="hover:underline">
                          <Mono className="font-medium">{c.activo}</Mono>
                        </Link>
                      </TableCell>
                      <TableCell>
                        <Mono>{c.usuario_acceso}</Mono>
                      </TableCell>
                      <TableCell className="text-right">
                        <Badge variant="destructive">{c.dias} días</Badge>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardPanel>

          <CardPanel icono={TrendingUp} titulo="Top accesos a credenciales">
            {datos.top_accesos.length === 0 ? (
              vacio("Sin accesos registrados.")
            ) : (
              <div className="flex flex-col gap-3">
                {datos.top_accesos.map((t) => (
                  <div key={t.username} className="flex items-center gap-3">
                    <Mono className="w-24 truncate text-[13px]">{t.username}</Mono>
                    <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
                      <div
                        className="h-full rounded-full"
                        style={{
                          width: `${(t.accesos / maxAcc) * 100}%`,
                          background: "var(--chart-3)",
                        }}
                      />
                    </div>
                    <Mono className="w-9 text-right text-[13px] font-semibold">{t.accesos}</Mono>
                  </div>
                ))}
              </div>
            )}
          </CardPanel>

          <CardPanel
            icono={ShieldAlert}
            titulo="Cuentas sin MFA"
            accion={
              puede("usuarios.gestionar") && datos.sin_mfa.length > 0 ? (
                <Button variant="outline" size="sm" asChild>
                  <Link href="/usuarios">Gestionar</Link>
                </Button>
              ) : undefined
            }
          >
            {datos.sin_mfa.length === 0 ? (
              vacio("Todas las cuentas tienen MFA.")
            ) : (
              <div className="flex flex-col gap-2">
                {datos.sin_mfa.map((u) => (
                  <div key={u.username} className="flex items-center gap-2.5">
                    <ShieldAlert className="size-[15px] text-destructive" />
                    <Mono className="text-[13px] font-medium">{u.username}</Mono>
                    <Badge variant="secondary">{u.rol}</Badge>
                  </div>
                ))}
              </div>
            )}
          </CardPanel>

          <CardPanel icono={Lock} titulo="Usuarios bloqueados">
            {datos.bloqueados.length === 0 ? (
              vacio("No hay usuarios bloqueados.")
            ) : (
              <div className="flex flex-col gap-2">
                {datos.bloqueados.map((b) => (
                  <div key={b.username} className="flex items-center gap-2.5">
                    <Lock className="size-[15px] text-muted-foreground" />
                    <Mono className="text-[13px] font-medium">{b.username}</Mono>
                    <span className="text-xs text-muted-foreground">
                      hasta {new Date(b.bloqueado_hasta).toLocaleString()}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </CardPanel>

          <CardPanel icono={Clock} titulo="Concesiones por caducar" className="lg:col-span-2">
            {datos.concesiones_por_caducar.length === 0 ? (
              vacio("No hay concesiones próximas a caducar.")
            ) : (
              <Table className="rounded-none shadow-none">
                <TableHeader>
                  <TableRow>
                    <TableHead>Usuario</TableHead>
                    <TableHead>Activo</TableHead>
                    <TableHead>Nivel</TableHead>
                    <TableHead>Expira</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {datos.concesiones_por_caducar.map((c) => (
                    <TableRow key={c.id}>
                      <TableCell>
                        <Mono>{c.username}</Mono>
                      </TableCell>
                      <TableCell>
                        <Link href={rutaActivo(c.tipo, c.activo_id)} className="hover:underline">
                          <Mono className="font-medium">{c.activo_nombre}</Mono>
                        </Link>
                      </TableCell>
                      <TableCell>
                        <Badge variant="secondary">{c.nivel_label}</Badge>
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {c.expira_en ? new Date(c.expira_en).toLocaleString() : "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardPanel>
        </div>
      </div>
    </>
  );
}
