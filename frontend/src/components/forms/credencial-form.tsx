"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import type { CredencialInput } from "@/lib/types";
import { SERVICIOS } from "@/lib/constants";
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
    usada_por: inicial?.usada_por ?? "",
  });
  const [errores, setErrores] = useState<{ usuario?: string; password?: string }>({});
  const [enviando, setEnviando] = useState(false);
  const set = <K extends keyof CredencialInput>(k: K, val: CredencialInput[K]) =>
    setV((prev) => ({ ...prev, [k]: val }));

  async function enviar(e: React.FormEvent) {
    e.preventDefault();
    // Validación inline: el toast queda para errores de red/API.
    const errs: typeof errores = {};
    if (!v.usuario_acceso.trim()) errs.usuario = "El usuario de acceso es obligatorio.";
    if (!edicion && !v.password) errs.password = "La contraseña es obligatoria.";
    setErrores(errs);
    if (Object.keys(errs).length > 0) return;
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
    <form onSubmit={enviar} noValidate>
      <FormPanel titulo="Datos de la credencial">
        <div className="space-y-2">
          <Label htmlFor="usuario">
            Usuario de acceso<span className="text-destructive"> *</span>
          </Label>
          <Input
            id="usuario"
            required
            className="font-mono"
            value={v.usuario_acceso}
            aria-invalid={errores.usuario ? true : undefined}
            aria-describedby={errores.usuario ? "usuario-error" : undefined}
            onChange={(e) => {
              set("usuario_acceso", e.target.value);
              if (errores.usuario) setErrores((p) => ({ ...p, usuario: undefined }));
            }}
          />
          {errores.usuario && (
            <p id="usuario-error" className="text-xs text-destructive">
              {errores.usuario}
            </p>
          )}
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
        {edicion ? (
          // Desde la 1.3.0 la contraseña no se cambia editando la credencial:
          // se rota bajo gobernanza (solicitud con motivo + autorización de
          // otro administrador). El panel de rotación vive debajo de este
          // formulario, así que aquí solo se explica por qué no hay campo.
          <div className="space-y-1 rounded-lg border border-dashed p-3 sm:col-span-2">
            <p className="text-sm font-medium">La contraseña se cambia por rotación</p>
            <p className="text-xs text-muted-foreground">
              Solicite la rotación indicando el motivo, espere a que otro administrador la
              autorice y registre entonces la contraseña que quedó aplicada en el activo. Lo
              encontrará en el panel de rotación, bajo este formulario.
            </p>
          </div>
        ) : (
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
        )}
        <div className="space-y-2">
          <Label htmlFor="puerto">Puerto</Label>
          <Input
            id="puerto"
            type="number"
            inputMode="numeric"
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
        <div className="space-y-2 sm:col-span-2">
          <Label htmlFor="usada-por">Usada por (servicios y automatismos)</Label>
          <Input
            id="usada-por"
            maxLength={500}
            placeholder="Ej.: cron de respaldos, Ansible, Zabbix"
            value={v.usada_por}
            onChange={(e) => set("usada_por", e.target.value)}
          />
          <p className="text-xs text-muted-foreground">
            Qué depende de esta cuenta. Se muestra al solicitar y al autorizar una rotación: es
            el fallo operativo más probable al cambiar una contraseña.
          </p>
        </div>
      </FormPanel>
      <FormAcciones enviando={enviando} onCancelar={() => router.back()} />
    </form>
  );
}
