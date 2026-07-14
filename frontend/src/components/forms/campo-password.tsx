"use client";

import { useState } from "react";
import { Eye, EyeOff, Wand2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { generarPassword } from "@/lib/password-gen";
import { cn } from "@/lib/utils";

// Estimación local y orientativa de fuerza (no sustituye a la política del
// backend): longitud + variedad de clases de caracteres.
type Fuerza = "debil" | "media" | "fuerte";

export function estimarFuerza(password: string): Fuerza {
  let puntos = 0;
  if (password.length >= 12) puntos += 1;
  if (password.length >= 16) puntos += 1;
  if (password.length >= 20) puntos += 1;
  const clases = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((r) => r.test(password)).length;
  if (clases >= 3) puntos += 1;
  if (clases === 4) puntos += 1;
  if (puntos <= 2) return "debil";
  if (puntos <= 4) return "media";
  return "fuerte";
}

const NIVEL: Record<Fuerza, { etiqueta: string; segmentos: number; color: string }> = {
  debil: { etiqueta: "Débil", segmentos: 1, color: "var(--destructive)" },
  media: { etiqueta: "Aceptable", segmentos: 2, color: "var(--warning)" },
  fuerte: { etiqueta: "Fuerte", segmentos: 3, color: "var(--foreground)" },
};

// Medidor monocromo + estado (DESIGN.md §1): tres segmentos que se rellenan
// con el tono del nivel. El color nunca va solo: acompaña la etiqueta.
export function MedidorFuerza({ password, className }: { password: string; className?: string }) {
  if (!password) return null;
  const nivel = NIVEL[estimarFuerza(password)];
  return (
    <div className={cn("flex items-center gap-2", className)} aria-live="polite">
      <div className="flex flex-1 gap-1" aria-hidden>
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className="h-1 flex-1 rounded-full bg-muted transition-colors"
            style={i < nivel.segmentos ? { background: nivel.color } : undefined}
          />
        ))}
      </div>
      <span className="text-2xs font-medium text-muted-foreground">{nivel.etiqueta}</span>
    </div>
  );
}

// Campo de contraseña canónico (DESIGN.md §4): mostrar/ocultar, generador y
// medidor. En edición, vacío significa «conservar la actual» (contrato con el
// backend): el placeholder lo comunica y `required` solo aplica al crear.
export function CampoPassword({
  id,
  label = "Contraseña",
  value,
  onChange,
  edicion = false,
  autoComplete = "new-password",
  generador = true,
  medidor = true,
  required,
}: {
  id: string;
  label?: string;
  value: string;
  onChange: (v: string) => void;
  edicion?: boolean;
  autoComplete?: string;
  generador?: boolean;
  medidor?: boolean;
  required?: boolean;
}) {
  const [mostrar, setMostrar] = useState(false);
  const obligatorio = required ?? !edicion;

  function generar() {
    onChange(generarPassword());
    setMostrar(true);
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <Label htmlFor={id}>
          {label}
          {obligatorio && <span className="text-destructive"> *</span>}
        </Label>
        {generador && (
          <Button type="button" variant="ghost" size="xs" onClick={generar}>
            <Wand2 /> Generar
          </Button>
        )}
      </div>
      <div className="relative">
        <Input
          id={id}
          type={mostrar ? "text" : "password"}
          autoComplete={autoComplete}
          required={obligatorio}
          placeholder={edicion ? "Dejar vacío para conservar la actual" : undefined}
          className="pr-10 font-mono"
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
        <button
          type="button"
          aria-label={mostrar ? "Ocultar contraseña" : "Mostrar contraseña"}
          onClick={() => setMostrar((v) => !v)}
          className="absolute top-1/2 right-2.5 -translate-y-1/2 text-muted-foreground transition-colors hover:text-foreground"
        >
          {mostrar ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
        </button>
      </div>
      {medidor && <MedidorFuerza password={value} />}
    </div>
  );
}
