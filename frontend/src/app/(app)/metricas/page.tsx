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

function Resumen({
  titulo,
  valor,
  icono,
}: {
  titulo: string;
  valor: number;
  icono: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">{titulo}</CardTitle>
        {icono}
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-semibold">{valor}</div>
      </CardContent>
    </Card>
  );
}

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
        if (activo) toast.error(err instanceof ApiError ? err.message : "No se pudieron cargar las métricas.");
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
      <div className="space-y-6">
        <PageHeader titulo="Métricas" />
        <p className="rounded-md border border-dashed p-10 text-center text-sm text-muted-foreground">
          No tiene permiso para ver las métricas.
        </p>
      </div>
    );
  }

  if (cargando) {
    return (
      <div className="space-y-6">
        <PageHeader titulo="Métricas de seguridad" />
        <div className="flex items-center justify-center p-10">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      </div>
    );
  }

  if (!datos) return null;

  return (
    <div className="space-y-6">
      <PageHeader
        titulo="Métricas de seguridad"
        descripcion="Panel de control del estado de seguridad del inventario."
      />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <Resumen
          titulo="Logins fallidos (24 h)"
          valor={datos.logins_fallidos_24h}
          icono={<Activity className="h-4 w-4 text-muted-foreground" />}
        />
        <Resumen
          titulo="Logins fallidos (7 d)"
          valor={datos.logins_fallidos_7d}
          icono={<Activity className="h-4 w-4 text-muted-foreground" />}
        />
        <Resumen
          titulo="Rotación vencida"
          valor={datos.rotacion_vencida.length}
          icono={<KeyRound className="h-4 w-4 text-muted-foreground" />}
        />
        <Resumen
          titulo="Cuentas sin MFA"
          valor={datos.sin_mfa.length}
          icono={<ShieldAlert className="h-4 w-4 text-muted-foreground" />}
        />
        <Resumen
          titulo="Usuarios bloqueados"
          valor={datos.bloqueados.length}
          icono={<Lock className="h-4 w-4 text-muted-foreground" />}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <KeyRound className="h-4 w-4" /> Credenciales con rotación vencida
            </CardTitle>
          </CardHeader>
          <CardContent>
            {datos.rotacion_vencida.length === 0 ? (
              <p className="text-sm text-muted-foreground">Ninguna credencial con rotación vencida.</p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Activo</TableHead>
                    <TableHead>Tipo</TableHead>
                    <TableHead>Usuario</TableHead>
                    <TableHead className="text-right">Días</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {datos.rotacion_vencida.map((c) => (
                    <TableRow key={c.id}>
                      <TableCell>
                        <Link href={rutaActivo(c.tipo, c.id)} className="hover:underline">
                          {c.activo}
                        </Link>
                      </TableCell>
                      <TableCell>{ETIQUETAS_TIPO_ACTIVO[c.tipo]}</TableCell>
                      <TableCell className="font-mono">{c.usuario_acceso}</TableCell>
                      <TableCell className="text-right">
                        <Badge variant="destructive">{c.dias} días</Badge>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ShieldAlert className="h-4 w-4" /> Cuentas sin MFA
            </CardTitle>
          </CardHeader>
          <CardContent>
            {datos.sin_mfa.length === 0 ? (
              <p className="text-sm text-muted-foreground">Todas las cuentas tienen MFA habilitado.</p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Usuario</TableHead>
                    <TableHead>Rol</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {datos.sin_mfa.map((u) => (
                    <TableRow key={u.username}>
                      <TableCell className="font-mono">{u.username}</TableCell>
                      <TableCell>{u.rol}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Lock className="h-4 w-4" /> Usuarios bloqueados
            </CardTitle>
          </CardHeader>
          <CardContent>
            {datos.bloqueados.length === 0 ? (
              <p className="text-sm text-muted-foreground">No hay usuarios bloqueados.</p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Usuario</TableHead>
                    <TableHead>Bloqueado hasta</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {datos.bloqueados.map((b) => (
                    <TableRow key={b.username}>
                      <TableCell className="font-mono">{b.username}</TableCell>
                      <TableCell>{new Date(b.bloqueado_hasta).toLocaleString()}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <TrendingUp className="h-4 w-4" /> Top accesos a credenciales
            </CardTitle>
          </CardHeader>
          <CardContent>
            {datos.top_accesos.length === 0 ? (
              <p className="text-sm text-muted-foreground">Sin accesos registrados.</p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Usuario</TableHead>
                    <TableHead className="text-right">Accesos</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {datos.top_accesos.map((t) => (
                    <TableRow key={t.username}>
                      <TableCell className="font-mono">{t.username}</TableCell>
                      <TableCell className="text-right">{t.accesos}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Clock className="h-4 w-4" /> Concesiones por caducar
            </CardTitle>
          </CardHeader>
          <CardContent>
            {datos.concesiones_por_caducar.length === 0 ? (
              <p className="text-sm text-muted-foreground">No hay concesiones próximas a caducar.</p>
            ) : (
              <Table>
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
                      <TableCell className="font-mono">{c.username}</TableCell>
                      <TableCell>
                        <Link href={rutaActivo(c.tipo, c.activo_id)} className="hover:underline">
                          {c.activo_nombre}
                        </Link>
                      </TableCell>
                      <TableCell>
                        <Badge variant="secondary">{c.nivel_label}</Badge>
                      </TableCell>
                      <TableCell>{c.expira_en ? new Date(c.expira_en).toLocaleString() : "—"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
