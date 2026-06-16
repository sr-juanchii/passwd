"use client";

import { useCallback, useEffect, useState } from "react";
import { Clipboard, Loader2, Plus, Trash2 } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { TokenApi } from "@/lib/types";
import { useSession } from "@/lib/session";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { toast } from "sonner";

function fecha(valor: string | null): string {
  return valor ? new Date(valor).toLocaleString() : "—";
}

export default function TokensPage() {
  const { puede } = useSession();
  const [tokens, setTokens] = useState<TokenApi[]>([]);
  const [cargando, setCargando] = useState(true);
  const [nombre, setNombre] = useState("");
  const [creando, setCreando] = useState(false);
  const [tokenNuevo, setTokenNuevo] = useState<string | null>(null);

  const cargar = useCallback(async () => {
    setCargando(true);
    try {
      const r = await api.tokens();
      setTokens(r.tokens);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "No se pudieron cargar los tokens.");
    } finally {
      setCargando(false);
    }
  }, []);

  useEffect(() => {
    void cargar();
  }, [cargar]);

  async function crear(e: React.FormEvent) {
    e.preventDefault();
    if (!nombre.trim()) return;
    setCreando(true);
    try {
      const r = await api.crearToken(nombre.trim());
      setTokenNuevo(r.token);
      setNombre("");
      toast.success("Token creado.");
      await cargar();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "No se pudo crear el token.");
    } finally {
      setCreando(false);
    }
  }

  async function revocar(t: TokenApi) {
    try {
      await api.revocarToken(t.id);
      toast.success(`Token "${t.nombre}" revocado.`);
      await cargar();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "No se pudo revocar el token.");
    }
  }

  async function copiar(texto: string) {
    try {
      await navigator.clipboard.writeText(texto);
      toast.success("Copiado al portapapeles.");
    } catch {
      toast.error("No se pudo copiar.");
    }
  }

  if (!puede("tokens.gestionar")) {
    return (
      <div className="space-y-6">
        <PageHeader titulo="Tokens de API" />
        <p className="rounded-md border border-dashed p-10 text-center text-sm text-muted-foreground">
          No tiene permiso para gestionar tokens.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        titulo="Tokens de API"
        descripcion="Tokens Bearer de solo lectura para integraciones con el SIEM. Preséntelos en la cabecera Authorization."
      />

      {tokenNuevo && (
        <Alert>
          <AlertTitle>Token generado</AlertTitle>
          <AlertDescription className="space-y-3">
            <span>
              Copie este token ahora: se muestra <strong>una sola vez</strong> y no podrá recuperarse.
            </span>
            <span className="flex w-full items-center gap-2">
              <code className="flex-1 rounded bg-muted px-3 py-2 font-mono text-sm break-all">
                {tokenNuevo}
              </code>
              <Button size="icon" variant="outline" onClick={() => void copiar(tokenNuevo)} title="Copiar">
                <Clipboard className="h-4 w-4" />
              </Button>
            </span>
          </AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Crear token</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={crear} className="flex flex-wrap items-end gap-3">
            <div className="flex-1 space-y-2 min-w-60">
              <Label htmlFor="nombre">Nombre descriptivo</Label>
              <Input
                id="nombre"
                placeholder="p. ej. SIEM producción"
                value={nombre}
                onChange={(e) => setNombre(e.target.value)}
              />
            </div>
            <Button type="submit" disabled={creando || !nombre.trim()}>
              {creando ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              Crear
            </Button>
          </form>
        </CardContent>
      </Card>

      {cargando ? (
        <div className="flex items-center justify-center p-10">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : tokens.length === 0 ? (
        <p className="rounded-md border border-dashed p-10 text-center text-sm text-muted-foreground">
          No hay tokens creados.
        </p>
      ) : (
        <div className="rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Nombre</TableHead>
                <TableHead>Creado</TableHead>
                <TableHead>Último uso</TableHead>
                <TableHead>Estado</TableHead>
                <TableHead>Creado por</TableHead>
                <TableHead className="text-right">Acciones</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {tokens.map((t) => (
                <TableRow key={t.id}>
                  <TableCell className="font-medium">{t.nombre}</TableCell>
                  <TableCell>{fecha(t.creado_en)}</TableCell>
                  <TableCell>{fecha(t.ultimo_uso)}</TableCell>
                  <TableCell>
                    {t.activo ? (
                      <Badge variant="default">Activo</Badge>
                    ) : (
                      <Badge variant="destructive">Revocado</Badge>
                    )}
                  </TableCell>
                  <TableCell>{t.creado_por}</TableCell>
                  <TableCell className="text-right">
                    {t.activo && (
                      <AlertDialog>
                        <AlertDialogTrigger asChild>
                          <Button size="icon" variant="ghost" title="Revocar">
                            <Trash2 className="h-4 w-4 text-destructive" />
                          </Button>
                        </AlertDialogTrigger>
                        <AlertDialogContent>
                          <AlertDialogHeader>
                            <AlertDialogTitle>¿Revocar este token?</AlertDialogTitle>
                            <AlertDialogDescription>
                              El token <strong>{t.nombre}</strong> dejará de funcionar de inmediato.
                              Esta acción no se puede deshacer.
                            </AlertDialogDescription>
                          </AlertDialogHeader>
                          <AlertDialogFooter>
                            <AlertDialogCancel>Cancelar</AlertDialogCancel>
                            <AlertDialogAction onClick={() => revocar(t)}>Revocar</AlertDialogAction>
                          </AlertDialogFooter>
                        </AlertDialogContent>
                      </AlertDialog>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
