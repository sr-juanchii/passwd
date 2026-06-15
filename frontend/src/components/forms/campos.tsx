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
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  required?: boolean;
  placeholder?: string;
  type?: string;
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
        onChange={(e) => onChange(e.target.value)}
      />
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
