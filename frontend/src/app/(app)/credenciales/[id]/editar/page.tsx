"use client";

import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { Eye, EyeOff, Loader2 } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { CredencialDetalle, HistorialEntrada } from "@/lib/types";
import { rutaActivo } from "@/lib/constants";
import { PageHeader } from "@/components/page-header";
import { CredencialForm } from "@/components/forms/credencial-form";
import { ErrorRecurso } from "@/components/error-recurso";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { toast } from "sonner";

function FilaHistorial({ credId, h }: { credId: number; h: HistorialEntrada }) {
  const [pwd, setPwd] = useState<string | null>(null);
  const [cargando, setCargando] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  async function revelar() {
    if (pwd !== null) {
      if (timer.current) clearTimeout(timer.current);
      setPwd(null);
      return;
    }
    setCargando(true);
    try {
      const r = await api.revelarHistorial(credId, h.id);
      setPwd(r.password);
      timer.current = setTimeout(() => setPwd(null), 30_000);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "No se pudo revelar.");
    } finally {
      setCargando(false);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2 border-b py-2 text-sm last:border-0">
      <span className="text-muted-foreground">{new Date(h.rotada_en).toLocaleString()}</span>
      <span>· {h.rotada_por}</span>
      <Button size="sm" variant="outline" className="ml-auto" onClick={revelar} disabled={cargando}>
        {cargando ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : pwd !== null ? (
          <EyeOff className="h-3.5 w-3.5" />
        ) : (
          <Eye className="h-3.5 w-3.5" />
        )}
        {pwd !== null ? "Ocultar" : "Revelar"}
      </Button>
      {pwd !== null && <code className="w-full rounded bg-muted px-2 py-1 text-xs break-all">{pwd}</code>}
    </div>
  );
}

export default function EditarCredencialPage() {
  const { id } = useParams<{ id: string }>();
  const cid = Number(id);
  const [data, setData] = useState<CredencialDetalle | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.credencial(cid).then(setData).catch((e) => {
      setError(e instanceof ApiError ? e.message : "No se pudo cargar la credencial.");
    });
  }, [cid]);

  if (error) {
    return <ErrorRecurso titulo="Credencial no disponible" mensaje={error} />;
  }
  if (!data) {
    return (
      <div className="flex justify-center py-20">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const destino = rutaActivo(data.tipo_activo, data.activo_id);

  return (
    <>
      <PageHeader
        titulo="Editar credencial"
        migas={[
          { label: "Inventario", href: "/" },
          { label: data.activo_nombre, href: destino },
          { label: "Editar credencial" },
        ]}
      />
      <CredencialForm
        edicion
        inicial={data}
        destinoOk={destino}
        onGuardar={(v) => api.editarCredencial(cid, v)}
      />

      {data.historial.length > 0 && (
        <Card className="mt-6">
          <CardHeader>
            <CardTitle className="text-base">Historial de contraseñas anteriores</CardTitle>
            <CardDescription>
              Contraseñas reemplazadas en rotaciones previas. Revelarlas queda auditado.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {data.historial.map((h) => (
              <FilaHistorial key={h.id} credId={cid} h={h} />
            ))}
          </CardContent>
        </Card>
      )}
    </>
  );
}
