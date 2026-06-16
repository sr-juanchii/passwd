"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Loader2, Search } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { ResultadoBusqueda } from "@/lib/types";
import { ETIQUETAS_TIPO_ACTIVO, rutaActivo } from "@/lib/constants";
import { PageHeader } from "@/components/page-header";
import { EstadoBadge } from "@/components/estado-badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { toast } from "sonner";

function SeccionVacia() {
  return (
    <p className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">
      Sin coincidencias.
    </p>
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

  const tieneResultados =
    resultado &&
    (resultado.servidores.length > 0 ||
      resultado.hipervisores.length > 0 ||
      resultado.vms.length > 0 ||
      resultado.credenciales.length > 0);

  return (
    <div className="space-y-6">
      <PageHeader
        titulo="Búsqueda global"
        descripcion="Busque servidores, hipervisores, máquinas virtuales y credenciales del inventario."
      />

      <form onSubmit={enviar} className="flex max-w-xl gap-2">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            autoFocus
            value={texto}
            onChange={(e) => setTexto(e.target.value)}
            placeholder="Nombre, IP, usuario de acceso…"
            className="pl-8"
          />
        </div>
      </form>

      {!q.trim() ? (
        <p className="rounded-md border border-dashed p-10 text-center text-sm text-muted-foreground">
          Escriba un término de búsqueda para comenzar.
        </p>
      ) : cargando ? (
        <div className="flex items-center justify-center p-10">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : !tieneResultados ? (
        <p className="rounded-md border border-dashed p-10 text-center text-sm text-muted-foreground">
          No se encontraron resultados para <strong>{q}</strong>.
        </p>
      ) : (
        resultado && (
          <div className="grid gap-6">
            <Card>
              <CardHeader>
                <CardTitle>Servidores ({resultado.servidores.length})</CardTitle>
              </CardHeader>
              <CardContent>
                {resultado.servidores.length === 0 ? (
                  <SeccionVacia />
                ) : (
                  <div className="rounded-md border">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Nombre</TableHead>
                          <TableHead>IP de gestión</TableHead>
                          <TableHead>Ubicación</TableHead>
                          <TableHead>Estado</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {resultado.servidores.map((s) => (
                          <TableRow key={s.id}>
                            <TableCell>
                              <Link href={rutaActivo("fisico", s.id)} className="font-medium hover:underline">
                                {s.nombre}
                              </Link>
                            </TableCell>
                            <TableCell className="font-mono">{s.ip_gestion || "—"}</TableCell>
                            <TableCell>{s.ubicacion || "—"}</TableCell>
                            <TableCell>
                              <EstadoBadge estado={s.estado} />
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Hipervisores ({resultado.hipervisores.length})</CardTitle>
              </CardHeader>
              <CardContent>
                {resultado.hipervisores.length === 0 ? (
                  <SeccionVacia />
                ) : (
                  <div className="rounded-md border">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Nombre</TableHead>
                          <TableHead>Plataforma</TableHead>
                          <TableHead>IP de gestión</TableHead>
                          <TableHead>Estado</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {resultado.hipervisores.map((h) => (
                          <TableRow key={h.id}>
                            <TableCell>
                              <Link href={rutaActivo("hipervisor", h.id)} className="font-medium hover:underline">
                                {h.nombre}
                              </Link>
                            </TableCell>
                            <TableCell>{h.plataforma || "—"}</TableCell>
                            <TableCell className="font-mono">{h.ip_gestion || "—"}</TableCell>
                            <TableCell>
                              <EstadoBadge estado={h.estado} />
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Máquinas virtuales ({resultado.vms.length})</CardTitle>
              </CardHeader>
              <CardContent>
                {resultado.vms.length === 0 ? (
                  <SeccionVacia />
                ) : (
                  <div className="rounded-md border">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Nombre</TableHead>
                          <TableHead>IP</TableHead>
                          <TableHead>Sistema operativo</TableHead>
                          <TableHead>Estado</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {resultado.vms.map((v) => (
                          <TableRow key={v.id}>
                            <TableCell>
                              <Link href={rutaActivo("vm", v.id)} className="font-medium hover:underline">
                                {v.nombre}
                              </Link>
                            </TableCell>
                            <TableCell className="font-mono">{v.ip || "—"}</TableCell>
                            <TableCell>{v.sistema_operativo || "—"}</TableCell>
                            <TableCell>
                              <EstadoBadge estado={v.estado} />
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Credenciales ({resultado.credenciales.length})</CardTitle>
              </CardHeader>
              <CardContent>
                {resultado.credenciales.length === 0 ? (
                  <SeccionVacia />
                ) : (
                  <div className="rounded-md border">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Usuario</TableHead>
                          <TableHead>Servicio</TableHead>
                          <TableHead>Puerto</TableHead>
                          <TableHead>Activo</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {resultado.credenciales.map((c) => (
                          <TableRow key={c.id}>
                            <TableCell className="font-mono">{c.usuario_acceso}</TableCell>
                            <TableCell>{c.servicio}</TableCell>
                            <TableCell>{c.puerto ?? "—"}</TableCell>
                            <TableCell>
                              <Link
                                href={rutaActivo(c.tipo_activo, c.activo_id)}
                                className="hover:underline"
                              >
                                {ETIQUETAS_TIPO_ACTIVO[c.tipo_activo]} #{c.activo_id}
                              </Link>
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        )
      )}
    </div>
  );
}

export default function BuscarPage() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center p-10">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      }
    >
      <BuscarContenido />
    </Suspense>
  );
}
