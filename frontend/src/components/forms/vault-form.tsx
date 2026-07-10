"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Eye, EyeOff, Wand2 } from "lucide-react";
import type { VaultInput } from "@/lib/types";
import { CATEGORIAS_VAULT, ETIQUETAS_CATEGORIA_VAULT } from "@/lib/constants";
import { ApiError } from "@/lib/api";
import { generarPassword } from "@/lib/password-gen";
import { Button } from "@/components/ui/button";
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
  const [mostrar, setMostrar] = useState(false);
  const [enviando, setEnviando] = useState(false);
  const set = <K extends keyof VaultInput>(k: K, val: VaultInput[K]) =>
    setV((prev) => ({ ...prev, [k]: val }));

  function generar() {
    set("password", generarPassword());
    setMostrar(true);
  }

  async function enviar(e: React.FormEvent) {
    e.preventDefault();
    if (!v.titulo.trim()) {
      toast.error("El título es obligatorio.");
      return;
    }
    if (!edicion && !v.password) {
      toast.error("La contraseña es obligatoria.");
      return;
    }
    setEnviando(true);
    try {
      await onGuardar(v);
      toast.success("Entrada guardada en tu vault.");
      router.push("/vault");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "No se pudo guardar.");
      setEnviando(false);
    }
  }

  return (
    <form onSubmit={enviar}>
      <FormPanel titulo="Datos de la entrada">
        <div className="space-y-2">
          <Label htmlFor="titulo">
            Título<span className="text-destructive"> *</span>
          </Label>
          <Input id="titulo" required value={v.titulo} onChange={(e) => set("titulo", e.target.value)}
                 placeholder="Ej.: Correo personal, Panel del banco…" />
        </div>
        <div className="space-y-2">
          <Label htmlFor="usuario">Usuario / cuenta</Label>
          <Input id="usuario" className="font-mono" value={v.usuario_acceso}
                 onChange={(e) => set("usuario_acceso", e.target.value)} placeholder="usuario@correo.com" />
        </div>
        <div className="space-y-2 sm:col-span-2">
          <Label htmlFor="password">
            Contraseña {edicion && <span className="text-muted-foreground">(en blanco = conservar la actual)</span>}
          </Label>
          <div className="flex gap-2">
            <div className="relative flex-1">
              <Input
                id="password"
                type={mostrar ? "text" : "password"}
                autoComplete="new-password"
                value={v.password}
                onChange={(e) => set("password", e.target.value)}
                className="pr-10 font-mono"
              />
              <button
                type="button"
                onClick={() => setMostrar((m) => !m)}
                className="absolute right-2 top-2 text-muted-foreground hover:text-foreground"
                aria-label={mostrar ? "Ocultar" : "Mostrar"}
              >
                {mostrar ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
            <Button type="button" variant="outline" onClick={generar}>
              <Wand2 className="h-4 w-4" /> Generar
            </Button>
          </div>
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
          <Input id="url" value={v.url} onChange={(e) => set("url", e.target.value)} placeholder="https://…" />
        </div>
        <div className="space-y-2 sm:col-span-2">
          <Label htmlFor="notas">Notas (opcional)</Label>
          <Textarea id="notas" rows={3} value={v.notas} onChange={(e) => set("notas", e.target.value)}
                    placeholder="Información adicional (no pongas aquí la contraseña)." />
        </div>
      </FormPanel>
      <FormAcciones enviando={enviando} onCancelar={() => router.back()} />
    </form>
  );
}
