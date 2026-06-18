"use client";

import { useRef, useState } from "react";
import { Download, FileUp, Loader2, TriangleAlert, Upload } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { ResultadoImportacion } from "@/lib/types";
import { useSession } from "@/lib/session";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Mono } from "@/components/ui/mono";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { cn } from "@/lib/utils";
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
  const [arrastrando, setArrastrando] = useState(false);
  const [resultado, setResultado] = useState<ResultadoImportacion | null>(null);

  function elegir(f: File | null) {
    setArchivo(f);
    setResultado(null);
  }

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
      <>
        <PageHeader titulo="Importar" />
        <p className="rounded-[14px] border border-dashed p-10 text-center text-sm text-muted-foreground">
          No tiene permiso para importar inventario.
        </p>
      </>
    );
  }

  return (
    <div className="max-w-3xl">
      <PageHeader
        titulo="Importar"
        descripcion="Cargue activos y credenciales desde un archivo CSV."
      />

      <div className="flex flex-col gap-4">
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setArrastrando(true);
          }}
          onDragLeave={() => setArrastrando(false)}
          onDrop={(e) => {
            e.preventDefault();
            setArrastrando(false);
            const f = e.dataTransfer.files?.[0];
            if (f) elegir(f);
          }}
          className={cn(
            "rounded-[14px] border-2 border-dashed bg-card p-12 text-center transition-colors",
            arrastrando ? "border-foreground/40 bg-muted" : "border-border",
          )}
        >
          <div className="mx-auto flex size-12 items-center justify-center rounded-xl bg-muted">
            <Upload className="size-[22px] text-foreground" />
          </div>
          {archivo ? (
            <p className="mt-3.5 text-[14.5px] font-medium">
              <Mono>{archivo.name}</Mono>
            </p>
          ) : (
            <>
              <p className="mt-3.5 text-[14.5px] font-medium">Arrastre un archivo CSV aquí</p>
              <p className="text-[12.5px] text-muted-foreground">o</p>
            </>
          )}
          <div className="mt-3 flex items-center justify-center gap-2">
            <Button onClick={() => inputRef.current?.click()} variant={archivo ? "outline" : "default"}>
              <Upload /> {archivo ? "Cambiar archivo" : "Seleccionar archivo"}
            </Button>
            {archivo && (
              <Button onClick={importar} disabled={importando}>
                {importando ? <Loader2 className="animate-spin" /> : <FileUp />} Importar
              </Button>
            )}
          </div>
          <input
            ref={inputRef}
            type="file"
            accept=".csv"
            className="hidden"
            onChange={(e) => elegir(e.target.files?.[0] ?? null)}
          />
        </div>

        <Alert variant="destructive">
          <TriangleAlert className="size-4" />
          <AlertTitle>El CSV contiene secretos en claro</AlertTitle>
          <AlertDescription>
            El archivo incluye contraseñas sin cifrar. Las contraseñas se cifran al importar y se
            registra cada alta en la bitácora. Maneje el archivo por un canal seguro y destrúyalo de
            forma permanente inmediatamente después de importarlo.
          </AlertDescription>
        </Alert>

        {resultado && (
          <div className="overflow-hidden rounded-[14px] border bg-card">
            <div className="border-b px-4 py-3.5">
              <span className="text-sm font-semibold">Resultado de la importación</span>
              <span className="ml-2 text-[13px] text-muted-foreground">
                {resultado.total} registro(s) creado(s)
              </span>
            </div>
            <div className="grid grid-cols-2 gap-px bg-border sm:grid-cols-4">
              {(
                [
                  ["Servidores", resultado.creados.servidor],
                  ["Hipervisores", resultado.creados.hipervisor],
                  ["VMs", resultado.creados.vm],
                  ["Credenciales", resultado.creados.credencial],
                ] as [string, number][]
              ).map(([l, v]) => (
                <div key={l} className="flex flex-col gap-1 bg-card px-4 py-3.5">
                  <span className="text-xs text-muted-foreground">{l}</span>
                  <span className="text-xl font-semibold tabular-nums">{v}</span>
                </div>
              ))}
            </div>
            {resultado.errores.length > 0 && (
              <div className="p-4">
                <Alert variant="destructive">
                  <TriangleAlert className="size-4" />
                  <AlertTitle>{resultado.errores.length} error(es)</AlertTitle>
                  <AlertDescription>
                    <ul className="list-disc space-y-1 pl-4">
                      {resultado.errores.map((e, i) => (
                        <li key={i}>{e}</li>
                      ))}
                    </ul>
                  </AlertDescription>
                </Alert>
              </div>
            )}
          </div>
        )}

        <div className="overflow-hidden rounded-[14px] border bg-card">
          <div className="flex items-center gap-2.5 border-b px-4 py-3.5">
            <FileUp className="size-4 text-muted-foreground" />
            <span className="text-sm font-semibold">Formato del CSV</span>
          </div>
          <div className="flex flex-col gap-3 p-4">
            <p className="text-[13px] text-muted-foreground">
              La primera columna de cada fila es el <Mono>tipo</Mono> (servidor, hipervisor, vm o
              credencial), seguida de sus columnas. El campo <Mono>padre</Mono> referencia el nombre
              del activo contenedor.
            </p>
            {FORMATO.map((f) => (
              <div key={f.tipo} className="flex flex-col gap-1">
                <div className="text-sm font-medium">{f.tipo}</div>
                <code className="block rounded-lg bg-muted px-3 py-2 font-mono text-xs break-words">
                  {f.columnas}
                </code>
              </div>
            ))}
          </div>
        </div>

        <Button variant="outline" className="self-start" disabled>
          <Download /> Descargar plantilla CSV
        </Button>
      </div>
    </div>
  );
}
