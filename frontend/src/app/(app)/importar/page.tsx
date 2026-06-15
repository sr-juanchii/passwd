"use client";

import { useRef, useState } from "react";
import { FileUp, Loader2, TriangleAlert, Upload } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { ResultadoImportacion } from "@/lib/types";
import { useSession } from "@/lib/session";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { toast } from "sonner";

const FORMATO: { tipo: string; columnas: string }[] = [
  { tipo: "servidor", columnas: "nombre, tipo_servidor, sistema_operativo, ip, descripcion, estado, etiquetas" },
  { tipo: "hipervisor", columnas: "nombre, padre, plataforma, version, ip, descripcion, estado, etiquetas" },
  { tipo: "vm", columnas: "nombre, padre, sistema_operativo, ip, descripcion, estado, etiquetas" },
  { tipo: "credencial", columnas: "activo_tipo, padre, usuario_acceso, password, servicio, puerto, descripcion" },
];

export default function ImportarPage() {
  const { puede } = useSession();
  const inputRef = useRef<HTMLInputElement>(null);
  const [archivo, setArchivo] = useState<File | null>(null);
  const [importando, setImportando] = useState(false);
  const [resultado, setResultado] = useState<ResultadoImportacion | null>(null);

  async function importar() {
    if (!archivo) return;
    setImportando(true);
    setResultado(null);
    try {
      const r = await api.importar(archivo);
      setResultado(r);
      toast.success(`Importación completada: ${r.total} registro(s) creado(s).`);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "No se pudo importar el archivo.");
    } finally {
      setImportando(false);
    }
  }

  if (!puede("inventario.gestionar")) {
    return (
      <div className="space-y-6">
        <PageHeader titulo="Importar CSV" />
        <p className="rounded-md border border-dashed p-10 text-center text-sm text-muted-foreground">
          No tiene permiso para importar inventario.
        </p>
      </div>
    );
  }

  return (
    <div className="max-w-3xl space-y-6">
      <PageHeader
        titulo="Importar CSV"
        descripcion="Cargue activos y credenciales de forma masiva desde un archivo CSV."
      />

      <Alert variant="destructive">
        <TriangleAlert className="h-4 w-4" />
        <AlertTitle>El CSV contiene secretos en claro</AlertTitle>
        <AlertDescription>
          El archivo incluye contraseñas sin cifrar. Manéjelo por un canal seguro y destrúyalo de forma
          permanente inmediatamente después de importarlo.
        </AlertDescription>
      </Alert>

      <Card>
        <CardHeader>
          <CardTitle>Archivo</CardTitle>
          <CardDescription>Seleccione un archivo CSV con el formato indicado más abajo.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex-1 min-w-60 space-y-2">
              <Input
                ref={inputRef}
                type="file"
                accept=".csv"
                onChange={(e) => {
                  setArchivo(e.target.files?.[0] ?? null);
                  setResultado(null);
                }}
              />
            </div>
            <Button onClick={importar} disabled={!archivo || importando}>
              {importando ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Upload className="h-4 w-4" />
              )}
              Importar
            </Button>
          </div>
        </CardContent>
      </Card>

      {resultado && (
        <Card>
          <CardHeader>
            <CardTitle>Resultado de la importación</CardTitle>
            <CardDescription>{resultado.total} registro(s) creado(s) en total.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div className="rounded-md border p-3">
                <div className="text-xs text-muted-foreground">Servidores</div>
                <div className="text-xl font-semibold">{resultado.creados.servidor}</div>
              </div>
              <div className="rounded-md border p-3">
                <div className="text-xs text-muted-foreground">Hipervisores</div>
                <div className="text-xl font-semibold">{resultado.creados.hipervisor}</div>
              </div>
              <div className="rounded-md border p-3">
                <div className="text-xs text-muted-foreground">VMs</div>
                <div className="text-xl font-semibold">{resultado.creados.vm}</div>
              </div>
              <div className="rounded-md border p-3">
                <div className="text-xs text-muted-foreground">Credenciales</div>
                <div className="text-xl font-semibold">{resultado.creados.credencial}</div>
              </div>
            </div>

            {resultado.errores.length > 0 && (
              <Alert variant="destructive">
                <TriangleAlert className="h-4 w-4" />
                <AlertTitle>{resultado.errores.length} error(es)</AlertTitle>
                <AlertDescription>
                  <ul className="list-disc space-y-1 pl-4">
                    {resultado.errores.map((e, i) => (
                      <li key={i}>{e}</li>
                    ))}
                  </ul>
                </AlertDescription>
              </Alert>
            )}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileUp className="h-4 w-4" /> Formato del CSV
          </CardTitle>
          <CardDescription>
            La primera columna de cada fila es el <code className="font-mono">tipo</code>
            (servidor, hipervisor, vm o credencial), seguida de sus columnas. El campo{" "}
            <code className="font-mono">padre</code> referencia el nombre del activo contenedor.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {FORMATO.map((f) => (
            <div key={f.tipo} className="space-y-1">
              <div className="text-sm font-medium">{f.tipo}</div>
              <code className="block rounded bg-muted px-3 py-2 font-mono text-xs break-words">
                {f.columnas}
              </code>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
