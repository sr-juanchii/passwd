"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Save } from "lucide-react";
import type { ServidorInput, TipoServidor } from "@/lib/types";
import { ETIQUETAS_TIPO_SERVIDOR } from "@/lib/constants";
import { ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { CampoArea, CampoEstado, CampoTexto } from "./campos";
import { toast } from "sonner";

const VACIO: ServidorInput = {
  nombre: "",
  tipo: "funcion_unica",
  descripcion: "",
  sistema_operativo: "",
  marca_modelo: "",
  ubicacion: "",
  ip_gestion: "",
  ram: "",
  cpu: "",
  almacenamiento: "",
  numero_serie: "",
  garantia_hasta: "",
  proveedor: "",
  estado: "activo",
  etiquetas: "",
};

export function ServidorForm({
  inicial,
  onGuardar,
}: {
  inicial?: Partial<ServidorInput>;
  onGuardar: (v: ServidorInput) => Promise<{ id: number }>;
}) {
  const router = useRouter();
  const [v, setV] = useState<ServidorInput>({ ...VACIO, ...inicial });
  const [enviando, setEnviando] = useState(false);
  const set = <K extends keyof ServidorInput>(k: K, val: ServidorInput[K]) =>
    setV((prev) => ({ ...prev, [k]: val }));

  async function enviar(e: React.FormEvent) {
    e.preventDefault();
    setEnviando(true);
    try {
      const r = await onGuardar(v);
      toast.success("Servidor guardado.");
      router.push(`/servidores/${r.id}`);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "No se pudo guardar.");
      setEnviando(false);
    }
  }

  return (
    <form onSubmit={enviar}>
      <Card>
        <CardContent className="grid gap-4 py-6 sm:grid-cols-2">
          <CampoTexto id="nombre" label="Nombre" required value={v.nombre} onChange={(x) => set("nombre", x)} />
          <div className="space-y-2">
            <Label>Tipo</Label>
            <Select value={v.tipo} onValueChange={(x) => set("tipo", x as TipoServidor)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(Object.keys(ETIQUETAS_TIPO_SERVIDOR) as TipoServidor[]).map((t) => (
                  <SelectItem key={t} value={t}>
                    {ETIQUETAS_TIPO_SERVIDOR[t]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <CampoTexto id="so" label="Sistema operativo" value={v.sistema_operativo} onChange={(x) => set("sistema_operativo", x)} />
          <CampoTexto id="marca" label="Marca / Modelo" value={v.marca_modelo} onChange={(x) => set("marca_modelo", x)} />
          <CampoTexto id="ubic" label="Ubicación" value={v.ubicacion} onChange={(x) => set("ubicacion", x)} />
          <CampoTexto id="ip" label="IP de gestión" value={v.ip_gestion} onChange={(x) => set("ip_gestion", x)} />
          <CampoTexto id="ram" label="RAM" value={v.ram} onChange={(x) => set("ram", x)} />
          <CampoTexto id="cpu" label="CPU" value={v.cpu} onChange={(x) => set("cpu", x)} />
          <CampoTexto id="alm" label="Almacenamiento" value={v.almacenamiento} onChange={(x) => set("almacenamiento", x)} />
          <CampoTexto id="serie" label="Número de serie" value={v.numero_serie} onChange={(x) => set("numero_serie", x)} />
          <CampoTexto id="gar" label="Garantía hasta" value={v.garantia_hasta} onChange={(x) => set("garantia_hasta", x)} placeholder="AAAA-MM-DD" />
          <CampoTexto id="prov" label="Proveedor" value={v.proveedor} onChange={(x) => set("proveedor", x)} />
          <CampoEstado value={v.estado} onChange={(x) => set("estado", x)} />
          <CampoTexto id="etq" label="Etiquetas (separadas por coma)" value={v.etiquetas} onChange={(x) => set("etiquetas", x)} />
          <CampoArea id="desc" label="Descripción" value={v.descripcion} onChange={(x) => set("descripcion", x)} />
        </CardContent>
      </Card>
      <div className="mt-4 flex gap-2">
        <Button type="submit" disabled={enviando}>
          {enviando ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
          Guardar
        </Button>
        <Button type="button" variant="ghost" onClick={() => router.back()}>
          Cancelar
        </Button>
      </div>
    </form>
  );
}
