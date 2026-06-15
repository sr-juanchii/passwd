"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Save } from "lucide-react";
import type { VmInput } from "@/lib/types";
import { ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { CampoArea, CampoEstado, CampoTexto } from "./campos";
import { toast } from "sonner";

const VACIO: VmInput = {
  nombre: "",
  sistema_operativo: "",
  ip: "",
  descripcion: "",
  estado: "activo",
  etiquetas: "",
};

export function VmForm({
  inicial,
  onGuardar,
  destinoOk,
}: {
  inicial?: Partial<VmInput>;
  onGuardar: (v: VmInput) => Promise<{ id: number }>;
  destinoOk?: (id: number) => string;
}) {
  const router = useRouter();
  const [v, setV] = useState<VmInput>({ ...VACIO, ...inicial });
  const [enviando, setEnviando] = useState(false);
  const set = <K extends keyof VmInput>(k: K, val: VmInput[K]) =>
    setV((prev) => ({ ...prev, [k]: val }));

  async function enviar(e: React.FormEvent) {
    e.preventDefault();
    setEnviando(true);
    try {
      const r = await onGuardar(v);
      toast.success("Máquina virtual guardada.");
      router.push(destinoOk ? destinoOk(r.id) : `/vms/${r.id}`);
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
          <CampoTexto id="so" label="Sistema operativo" value={v.sistema_operativo} onChange={(x) => set("sistema_operativo", x)} />
          <CampoTexto id="ip" label="Dirección IP" value={v.ip} onChange={(x) => set("ip", x)} />
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
