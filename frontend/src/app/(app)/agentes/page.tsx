"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, Bot } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { ListaAgentes } from "@/lib/types";
import { haceCuanto, rutaActivo } from "@/lib/agentes";
import { PageHeader } from "@/components/page-header";
import { CoberturaBadge } from "@/components/agentes/cobertura-badge";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { EmptyState } from "@/components/ui/empty-state";
import { Label } from "@/components/ui/label";
import { PageSkeleton } from "@/components/ui/page-skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { toast } from "sonner";

/**
 * Los agentes de rotación y su cobertura.
 *
 * Se dan de alta desde la ficha de cada activo, que es donde se decide qué
 * servidor rota por agente. Aquí se ve el parque entero: quién late, quién lleva
 * demasiado tiempo callado y quién tiene una rotación entre manos.
 */
export default function AgentesPage() {
  const [datos, setDatos] = useState<ListaAgentes | null>(null);
  const [revocados, setRevocados] = useState(false);

  const cargar = useCallback(() => {
    api
      .agentes(revocados)
      .then(setDatos)
      .catch((e) => toast.error(e instanceof ApiError ? e.message : "No se pudieron cargar los agentes."));
  }, [revocados]);

  useEffect(cargar, [cargar]);

  if (!datos) return <PageSkeleton />;

  return (
    <>
      <PageHeader
        titulo="Agentes de rotación"
        descripcion="Aplican en cada servidor las rotaciones que ya autorizaron dos personas, las verifican y las revierten si fallan."
        migas={[{ label: "Agentes" }]}
      />

      {!datos.habilitados && (
        <Card className="mb-6 border-amber-500/40">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <AlertTriangle className="size-4" /> Agentes desactivados
            </CardTitle>
            <CardDescription>
              El interruptor «Agentes de rotación activos» está apagado en la configuración: no se
              pueden dar de alta agentes y toda rotación sigue el flujo manual.
            </CardDescription>
          </CardHeader>
        </Card>
      )}

      <div className="mb-4 flex items-center gap-2">
        <Checkbox id="ver-revocados" checked={revocados} onCheckedChange={(v) => setRevocados(v === true)} />
        <Label htmlFor="ver-revocados">Mostrar también los revocados</Label>
      </div>

      {datos.agentes.length === 0 ? (
        <EmptyState
          icono={Bot}
          titulo="Ningún agente todavía"
          descripcion="Un agente se da de alta desde la ficha del servidor, hipervisor o máquina virtual en la que se va a instalar."
        />
      ) : (
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Agente</TableHead>
                  <TableHead>Activo</TableHead>
                  <TableHead>Estado</TableHead>
                  <TableHead>Versión</TableHead>
                  <TableHead>Último latido</TableHead>
                  <TableHead>Trabajo en curso</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {datos.agentes.map((a) => (
                  <TableRow key={a.id}>
                    <TableCell className="font-medium">
                      {a.nombre}
                      {a.nombre_host && <span className="block text-xs text-muted-foreground">{a.nombre_host}</span>}
                    </TableCell>
                    <TableCell>
                      <Link href={rutaActivo(a.activo.tipo, a.activo.id)} className="hover:underline">
                        {a.activo.nombre}
                      </Link>
                    </TableCell>
                    <TableCell>
                      {a.estado === "revocado" ? <Badge variant="secondary">Revocado</Badge> : <CoberturaBadge cobertura={a.cobertura} />}
                    </TableCell>
                    <TableCell>
                      {a.version_agente || "—"}
                      {!a.version_admitida && <span className="block text-xs text-destructive">Por debajo de la mínima</span>}
                    </TableCell>
                    <TableCell>{haceCuanto(a.ultimo_contacto_en)}</TableCell>
                    <TableCell>
                      {a.trabajo_en_curso ? (
                        <span className={a.trabajo_en_curso.sin_confirmar ? "text-destructive" : ""}>
                          {a.trabajo_en_curso.usuario_acceso}
                          {a.trabajo_en_curso.sin_confirmar ? " · sin confirmar" : ` · ${a.trabajo_en_curso.estado}`}
                        </span>
                      ) : (
                        "—"
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </>
  );
}
