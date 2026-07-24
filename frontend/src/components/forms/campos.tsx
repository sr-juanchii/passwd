"use client";

import { Lock } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { EstadoBadge } from "@/components/estado-badge";
import { ESTADOS } from "@/lib/constants";
import type { EstadoActivo } from "@/lib/types";

export function CampoTexto({
  id,
  label,
  value,
  onChange,
  required,
  placeholder,
  type = "text",
  error,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  required?: boolean;
  placeholder?: string;
  type?: string;
  // Mensaje de validación inline: marca el campo con aria-invalid (los estilos
  // ya viven en el primitivo Input) y lo muestra debajo en text-destructive.
  error?: string;
}) {
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>
        {label}
        {required && <span className="text-destructive"> *</span>}
      </Label>
      <Input
        id={id}
        type={type}
        required={required}
        placeholder={placeholder}
        value={value}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : undefined}
        onChange={(e) => onChange(e.target.value)}
      />
      {error && (
        <p id={`${id}-error`} className="text-xs text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}

export function CampoArea({
  id,
  label,
  value,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="space-y-2 sm:col-span-2">
      <Label htmlFor={id}>{label}</Label>
      <Textarea id={id} rows={3} value={value} onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}

// Interruptor "Restringir a administradores". Solo debe montarlo el formulario
// cuando el usuario actual es administrador. Ocupa las dos columnas de la rejilla
// para que el texto explicativo respire.
export function CampoRestringir({
  value,
  onChange,
  incluyeVms = false,
}: {
  value: boolean;
  onChange: (v: boolean) => void;
  incluyeVms?: boolean;
}) {
  return (
    <div className="flex items-start justify-between gap-4 rounded-lg border border-dashed p-4 sm:col-span-2">
      <div className="space-y-1">
        <Label htmlFor="restringido" className="flex items-center gap-1.5">
          <Lock className="size-3.5" /> Restringir a administradores
        </Label>
        <p className="text-xs text-muted-foreground">
          Los operadores no verán este activo
          {incluyeVms ? " ni sus máquinas virtuales" : ""}. Los auditores lo verán sin poder
          revelar contraseñas; los analistas, solo con una concesión explícita.
        </p>
      </div>
      <Switch
        id="restringido"
        checked={value}
        onCheckedChange={onChange}
        aria-label="Restringir a administradores"
      />
    </div>
  );
}

export function CampoEstado({
  value,
  onChange,
}: {
  value: EstadoActivo;
  onChange: (v: EstadoActivo) => void;
}) {
  return (
    <div className="space-y-2">
      <Label>Estado</Label>
      <Select value={value} onValueChange={(v) => onChange(v as EstadoActivo)}>
        <SelectTrigger>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {ESTADOS.map((e) => (
            <SelectItem key={e} value={e}>
              <EstadoBadge estado={e} />
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
