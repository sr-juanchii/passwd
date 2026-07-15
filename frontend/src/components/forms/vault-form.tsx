"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import type { VaultInput } from "@/lib/types";
import { CATEGORIAS_VAULT, ETIQUETAS_CATEGORIA_VAULT } from "@/lib/constants";
import { ApiError } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { CampoPassword } from "./campo-password";
import { FormAcciones, FormPanel } from "./form-shell";
import { toast } from "sonner";

export function VaultForm({
  inicial,
  edicion,
  onGuardar,
}: {
  inicial?: Partial<VaultInput>;
  edicion?: boolean;
  onGuardar: (v: VaultInput) => Promise<{ id: number }>;
}) {
  const router = useRouter();
  const [v, setV] = useState<VaultInput>({
    titulo: inicial?.titulo ?? "",
    usuario_acceso: inicial?.usuario_acceso ?? "",
    password: "",
    url: inicial?.url ?? "",
    categoria: inicial?.categoria ?? "cuenta",
    notas: inicial?.notas ?? "",
  });
  const [errores, setErrores] = useState<{ titulo?: string; password?: string }>({});
  const [enviando, setEnviando] = useState(false);
  const set = <K extends keyof VaultInput>(k: K, val: VaultInput[K]) =>
    setV((prev) => ({ ...prev, [k]: val }));

  async function enviar(e: React.FormEvent) {
    e.preventDefault();
    // Validación inline: el toast queda para errores de red/API.
    const errs: typeof errores = {};
    if (!v.titulo.trim()) errs.titulo = "El título es obligatorio.";
    if (!edicion && !v.password) errs.password = "La contraseña es obligatoria.";
    setErrores(errs);
    if (Object.keys(errs).length > 0) return;
    setEnviando(true);
    try {
      await onGuardar(v);
      toast.success("Entrada guardada en su vault.");
      router.push("/vault");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "No se pudo guardar.");
      setEnviando(false);
    }
  }

  return (
    <form onSubmit={enviar} noValidate>
      <FormPanel titulo="Datos de la entrada">
        <div className="space-y-2">
          <Label htmlFor="titulo">
            Título<span className="text-destructive"> *</span>
          </Label>
          <Input
            id="titulo"
            required
            value={v.titulo}
            aria-invalid={errores.titulo ? true : undefined}
            aria-describedby={errores.titulo ? "titulo-error" : undefined}
            onChange={(e) => {
              set("titulo", e.target.value);
              if (errores.titulo) setErrores((p) => ({ ...p, titulo: undefined }));
            }}
            placeholder="Ej.: Correo corporativo, Panel del proveedor…"
          />
          {errores.titulo && (
            <p id="titulo-error" className="text-xs text-destructive">
              {errores.titulo}
            </p>
          )}
        </div>
        <div className="space-y-2">
          <Label htmlFor="usuario">Usuario / cuenta</Label>
          <Input id="usuario" className="font-mono" value={v.usuario_acceso}
                 onChange={(e) => set("usuario_acceso", e.target.value)} placeholder="usuario@correo.com" />
        </div>
        <div className="space-y-2 sm:col-span-2">
          <CampoPassword
            id="password"
            value={v.password}
            edicion={edicion}
            onChange={(x) => {
              set("password", x);
              if (errores.password) setErrores((p) => ({ ...p, password: undefined }));
            }}
          />
          {errores.password && (
            <p className="text-xs text-destructive">{errores.password}</p>
          )}
        </div>
        <div className="space-y-2">
          <Label>Categoría</Label>
          <Select value={v.categoria} onValueChange={(x) => set("categoria", x as VaultInput["categoria"])}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {CATEGORIAS_VAULT.map((c) => (
                <SelectItem key={c} value={c}>
                  {ETIQUETAS_CATEGORIA_VAULT[c]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-2">
          <Label htmlFor="url">URL (opcional)</Label>
          <Input id="url" type="url" value={v.url} onChange={(e) => set("url", e.target.value)} placeholder="https://…" />
        </div>
        <div className="space-y-2 sm:col-span-2">
          <Label htmlFor="notas">Notas (opcional)</Label>
          <Textarea id="notas" rows={3} value={v.notas} onChange={(e) => set("notas", e.target.value)}
                    placeholder="Información adicional (no escriba aquí la contraseña)." />
        </div>
      </FormPanel>
      <FormAcciones enviando={enviando} onCancelar={() => router.back()} />
    </form>
  );
}
