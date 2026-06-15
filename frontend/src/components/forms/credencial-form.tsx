"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Eye, EyeOff, Loader2, Save, Wand2 } from "lucide-react";
import type { CredencialInput } from "@/lib/types";
import { SERVICIOS } from "@/lib/constants";
import { ApiError } from "@/lib/api";
import { generarPassword } from "@/lib/password-gen";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
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
import { toast } from "sonner";

export function CredencialForm({
  inicial,
  edicion,
  destinoOk,
  onGuardar,
}: {
  inicial?: Partial<CredencialInput>;
  edicion?: boolean;
  destinoOk: string;
  onGuardar: (v: CredencialInput) => Promise<{ id: number }>;
}) {
  const router = useRouter();
  const [v, setV] = useState<CredencialInput>({
    usuario_acceso: inicial?.usuario_acceso ?? "",
    password: "",
    servicio: inicial?.servicio ?? "SSH",
    puerto: inicial?.puerto ?? null,
    descripcion: inicial?.descripcion ?? "",
  });
  const [mostrar, setMostrar] = useState(false);
  const [enviando, setEnviando] = useState(false);
  const set = <K extends keyof CredencialInput>(k: K, val: CredencialInput[K]) =>
    setV((prev) => ({ ...prev, [k]: val }));

  function generar() {
    set("password", generarPassword());
    setMostrar(true);
  }

  async function enviar(e: React.FormEvent) {
    e.preventDefault();
    if (!edicion && !v.password) {
      toast.error("La contraseña es obligatoria.");
      return;
    }
    setEnviando(true);
    try {
      await onGuardar(v);
      toast.success("Credencial guardada.");
      router.push(destinoOk);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "No se pudo guardar.");
      setEnviando(false);
    }
  }

  return (
    <form onSubmit={enviar}>
      <Card>
        <CardContent className="grid gap-4 py-6 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="usuario">
              Usuario de acceso<span className="text-destructive"> *</span>
            </Label>
            <Input id="usuario" required value={v.usuario_acceso} onChange={(e) => set("usuario_acceso", e.target.value)} />
          </div>
          <div className="space-y-2">
            <Label>Servicio / Protocolo</Label>
            <Select value={v.servicio} onValueChange={(x) => set("servicio", x)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SERVICIOS.map((s) => (
                  <SelectItem key={s} value={s}>
                    {s}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
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
            <Label htmlFor="puerto">Puerto</Label>
            <Input
              id="puerto"
              type="number"
              min={1}
              max={65535}
              value={v.puerto ?? ""}
              onChange={(e) => set("puerto", e.target.value ? Number(e.target.value) : null)}
            />
          </div>
          <div className="space-y-2 sm:col-span-2">
            <Label htmlFor="desc">Descripción (a qué sistema da acceso)</Label>
            <Textarea id="desc" rows={3} value={v.descripcion} onChange={(e) => set("descripcion", e.target.value)} />
          </div>
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
