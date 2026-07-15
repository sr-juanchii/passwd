"use client";

import { useCallback, useEffect, useState } from "react";
import { Clipboard, KeyRound, Loader2, Lock, Plus, Trash2 } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { TokenAlcance, TokenApi } from "@/lib/types";
import { ETIQUETAS_TOKEN_ALCANCE, TOKEN_ALCANCES } from "@/lib/constants";
import { useSession } from "@/lib/session";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Chip } from "@/components/ui/chip";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Mono } from "@/components/ui/mono";
import { PageSkeleton } from "@/components/ui/page-skeleton";
import { SectionHeader } from "@/components/ui/section-header";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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
  const [alcance, setAlcance] = useState<TokenAlcance>("todo");
  const [dias, setDias] = useState("0");
  const [creando, setCreando] = useState(false);
  const [tokenNuevo, setTokenNuevo] = useState<string | null>(null);
  // Instante de referencia para señalar caducidades próximas (14 días);
  // en inicializador de estado porque Date.now() es impuro durante el render.
  const [ahora] = useState(() => Date.now());

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
      const r = await api.crearToken({ nombre: nombre.trim(), alcance, dias_validez: Number(dias) || 0 });
      setTokenNuevo(r.token);
      setNombre("");
      setDias("0");
      setAlcance("todo");
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
      <>
        <PageHeader titulo="Tokens de API" />
        <EmptyState icono={Lock} titulo="Sin permiso" descripcion="No tiene permiso para gestionar tokens." />
      </>
    );
  }

  return (
    <>
      <PageHeader
        titulo="Tokens de API"
        descripcion="Tokens Bearer de solo lectura para integraciones con el SIEM. Preséntelos en la cabecera Authorization."
      />

      <div className="flex flex-col gap-4">
        {tokenNuevo && (
          <Alert>
            <KeyRound className="size-4" />
            <AlertTitle>Token generado</AlertTitle>
            <AlertDescription className="flex flex-col gap-3">
              <span>
                Copie este token ahora: se muestra <strong>una sola vez</strong> y no podrá
                recuperarse.
              </span>
              <span className="flex w-full items-center gap-2">
                <code className="flex-1 rounded-lg bg-muted px-3 py-2 font-mono text-sm break-all">
                  {tokenNuevo}
                </code>
                <Button size="icon" variant="outline" onClick={() => void copiar(tokenNuevo)} title="Copiar">
                  <Clipboard />
                </Button>
              </span>
            </AlertDescription>
          </Alert>
        )}

        <div className="overflow-hidden rounded-xl border bg-card">
          <div className="border-b px-5 py-3.5">
            <SectionHeader icono={KeyRound} titulo="Crear token" />
          </div>
          <form onSubmit={crear} className="flex flex-wrap items-end gap-3 p-5">
            <div className="min-w-60 flex-1 space-y-2">
              <Label htmlFor="nombre">Nombre descriptivo</Label>
              <Input
                id="nombre"
                placeholder="p. ej. SIEM producción"
                value={nombre}
                onChange={(e) => setNombre(e.target.value)}
              />
            </div>
            <div className="min-w-48 space-y-2">
              <Label>Alcance</Label>
              <Select value={alcance} onValueChange={(v) => setAlcance(v as TokenAlcance)}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {TOKEN_ALCANCES.map((a) => (
                    <SelectItem key={a} value={a}>
                      {ETIQUETAS_TOKEN_ALCANCE[a]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="w-40 space-y-2">
              <Label htmlFor="dias">Caducidad (días, 0=nunca)</Label>
              <Input id="dias" type="number" min={0} max={3650} value={dias}
                     onChange={(e) => setDias(e.target.value)} />
            </div>
            <Button type="submit" disabled={creando || !nombre.trim()}>
              {creando ? <Loader2 className="animate-spin" /> : <Plus />}
              Crear
            </Button>
          </form>
        </div>

        {cargando ? (
          <PageSkeleton variante="tabla" cabecera={false} />
        ) : tokens.length === 0 ? (
          <EmptyState
            icono={KeyRound}
            titulo="No hay tokens creados"
            descripcion="Cree el primero con el formulario superior; el secreto se muestra una sola vez."
          />
        ) : (
          <div className="overflow-hidden rounded-xl border bg-card">
          <Table>
            <TableHeader className="bg-muted">
              <TableRow>
                <TableHead>Nombre</TableHead>
                <TableHead>Alcance</TableHead>
                <TableHead>Creado</TableHead>
                <TableHead>Caduca</TableHead>
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
                  <TableCell className="text-muted-foreground">{ETIQUETAS_TOKEN_ALCANCE[t.alcance]}</TableCell>
                  <TableCell className="text-muted-foreground">{fecha(t.creado_en)}</TableCell>
                  <TableCell
                    className={
                      t.activo && !t.caducado && t.expira_en &&
                      new Date(t.expira_en).getTime() - ahora < 14 * 86_400_000
                        ? "font-medium text-warning"
                        : "text-muted-foreground"
                    }
                  >
                    {t.expira_en ? new Date(t.expira_en).toLocaleDateString() : "—"}
                  </TableCell>
                  <TableCell className="text-muted-foreground">{fecha(t.ultimo_uso)}</TableCell>
                  <TableCell>
                    {!t.activo ? (
                      <Badge variant="destructive">Revocado</Badge>
                    ) : t.caducado ? (
                      <Chip className="text-destructive">Caducado</Chip>
                    ) : (
                      <Chip tono="outline">Activo</Chip>
                    )}
                  </TableCell>
                  <TableCell>
                    <Mono className="text-muted-foreground">{t.creado_por}</Mono>
                  </TableCell>
                  <TableCell className="text-right">
                    {t.activo && (
                      <AlertDialog>
                        <AlertDialogTrigger asChild>
                          <Button size="icon-sm" variant="ghost" title="Revocar">
                            <Trash2 className="text-destructive" />
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
                            <AlertDialogAction variant="destructive" onClick={() => revocar(t)}>
                              Revocar
                            </AlertDialogAction>
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
    </>
  );
}
