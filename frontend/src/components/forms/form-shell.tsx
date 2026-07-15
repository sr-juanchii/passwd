"use client";

import { Loader2, Save } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Eyebrow } from "@/components/ui/mono";

// Panel con cabecera para agrupar los campos de un formulario, en el mismo
// estilo de tarjeta del rediseño (borde hairline, radio de tarjeta).
export function FormPanel({
  titulo,
  children,
}: {
  titulo: string;
  children: React.ReactNode;
}) {
  return (
    <div className="overflow-hidden rounded-xl border bg-card">
      <div className="border-b px-5 py-3.5">
        <Eyebrow>{titulo}</Eyebrow>
      </div>
      <div className="grid gap-4 p-5 sm:grid-cols-2">{children}</div>
    </div>
  );
}

// Barra de acciones (Guardar / Cancelar) común a todos los formularios. El CTA
// primario va en h-9 (size="lg") para marcar jerarquía frente a Cancelar.
export function FormAcciones({
  enviando,
  onCancelar,
  etiqueta = "Guardar",
}: {
  enviando: boolean;
  onCancelar: () => void;
  etiqueta?: string;
}) {
  return (
    <div className="mt-4 flex gap-2">
      <Button type="submit" size="lg" disabled={enviando}>
        {enviando ? <Loader2 className="animate-spin" /> : <Save />}
        {etiqueta}
      </Button>
      <Button type="button" variant="ghost" onClick={onCancelar}>
        Cancelar
      </Button>
    </div>
  );
}
