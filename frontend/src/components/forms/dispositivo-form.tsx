"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import type { DispositivoInput, TipoDispositivo } from "@/lib/types";
import { ApiError } from "@/lib/api";
import { ETIQUETAS_TIPO_DISPOSITIVO, TIPOS_DISPOSITIVO } from "@/lib/constants";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { CampoArea, CampoEstado, CampoTexto } from "./campos";
import { FormAcciones, FormPanel } from "./form-shell";
import { toast } from "sonner";

const VACIO: DispositivoInput = {
  nombre: "",
  tipo_dispositivo: "switch",
  marca_modelo: "",
  version: "",
  ip_gestion: "",
  ubicacion: "",
  puertos: "",
  descripcion: "",
  numero_serie: "",
  garantia_hasta: "",
  proveedor: "",
  estado: "activo",
  etiquetas: "",
};

function CampoTipoDispositivo({
  value,
  onChange,
}: {
  value: TipoDispositivo;
  onChange: (v: TipoDispositivo) => void;
}) {
  return (
    <div className="space-y-2">
      <Label>Tipo de dispositivo</Label>
      <Select value={value} onValueChange={(v) => onChange(v as TipoDispositivo)}>
        <SelectTrigger>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {TIPOS_DISPOSITIVO.map((t) => (
            <SelectItem key={t} value={t}>
              {ETIQUETAS_TIPO_DISPOSITIVO[t]}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

export function DispositivoForm({
  inicial,
  onGuardar,
}: {
  inicial?: Partial<DispositivoInput>;
  onGuardar: (v: DispositivoInput) => Promise<{ id: number }>;
}) {
  const router = useRouter();
  const [v, setV] = useState<DispositivoInput>({ ...VACIO, ...inicial });
  const [enviando, setEnviando] = useState(false);
  const set = <K extends keyof DispositivoInput>(k: K, val: DispositivoInput[K]) =>
    setV((prev) => ({ ...prev, [k]: val }));

  async function enviar(e: React.FormEvent) {
    e.preventDefault();
    setEnviando(true);
    try {
      const r = await onGuardar(v);
      toast.success("Dispositivo guardado.");
      router.push(`/dispositivos/${r.id}`);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "No se pudo guardar.");
      setEnviando(false);
    }
  }

  return (
    <form onSubmit={enviar}>
      <FormPanel titulo="Datos del dispositivo">
          <CampoTexto id="nombre" label="Nombre" required value={v.nombre} onChange={(x) => set("nombre", x)} />
          <CampoTipoDispositivo value={v.tipo_dispositivo} onChange={(x) => set("tipo_dispositivo", x)} />
          <CampoTexto id="marca" label="Marca / Modelo" value={v.marca_modelo} onChange={(x) => set("marca_modelo", x)} />
          <CampoTexto id="ver" label="Firmware / versión" value={v.version} onChange={(x) => set("version", x)} />
          <CampoTexto id="ip" label="IP de gestión" value={v.ip_gestion} onChange={(x) => set("ip_gestion", x)} />
          <CampoTexto id="ubic" label="Ubicación" value={v.ubicacion} onChange={(x) => set("ubicacion", x)} />
          <CampoTexto id="puertos" label="Puertos" value={v.puertos} onChange={(x) => set("puertos", x)} placeholder="48x 1GbE, 4x SFP+…" />
          <CampoTexto id="serie" label="Número de serie" value={v.numero_serie} onChange={(x) => set("numero_serie", x)} />
          <CampoTexto id="gar" label="Garantía hasta" type="date" value={v.garantia_hasta} onChange={(x) => set("garantia_hasta", x)} />
          <CampoTexto id="prov" label="Proveedor" value={v.proveedor} onChange={(x) => set("proveedor", x)} />
          <CampoEstado value={v.estado} onChange={(x) => set("estado", x)} />
          <CampoTexto id="etq" label="Etiquetas (separadas por coma)" value={v.etiquetas} onChange={(x) => set("etiquetas", x)} />
          <CampoArea id="desc" label="Descripción" value={v.descripcion} onChange={(x) => set("descripcion", x)} />
      </FormPanel>
      <FormAcciones enviando={enviando} onCancelar={() => router.back()} />
    </form>
  );
}
