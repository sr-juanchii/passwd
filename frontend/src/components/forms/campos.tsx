"use client";

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
