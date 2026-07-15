"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import type { ServidorInput } from "@/lib/types";
import { ApiError } from "@/lib/api";
import { CampoArea, CampoEstado, CampoTexto } from "./campos";
import { FormAcciones, FormPanel } from "./form-shell";
import { toast } from "sonner";

const VACIO: ServidorInput = {
  nombre: "",
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
      <FormPanel titulo="Datos del servidor">
          <CampoTexto id="nombre" label="Nombre" required value={v.nombre} onChange={(x) => set("nombre", x)} />
          <CampoTexto id="so" label="Sistema operativo" value={v.sistema_operativo} onChange={(x) => set("sistema_operativo", x)} />
          <CampoTexto id="marca" label="Marca / Modelo" value={v.marca_modelo} onChange={(x) => set("marca_modelo", x)} />
          <CampoTexto id="ubic" label="Ubicación" value={v.ubicacion} onChange={(x) => set("ubicacion", x)} />
          <CampoTexto id="ip" label="IP de gestión" value={v.ip_gestion} onChange={(x) => set("ip_gestion", x)} />
          <CampoTexto id="ram" label="RAM" value={v.ram} onChange={(x) => set("ram", x)} />
          <CampoTexto id="cpu" label="CPU" value={v.cpu} onChange={(x) => set("cpu", x)} />
          <CampoTexto id="alm" label="Almacenamiento" value={v.almacenamiento} onChange={(x) => set("almacenamiento", x)} />
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
