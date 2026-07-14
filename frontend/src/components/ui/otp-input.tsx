"use client";

import { useRef } from "react";
import { cn } from "@/lib/utils";

// Representación única de códigos TOTP (DESIGN.md §4): 6 casillas h-12 con
// auto-avance, retroceso a la casilla previa y pegado distribuido. Conserva
// los atributos de accesibilidad del original (aria-label por dígito,
// inputMode numeric, maxLength 1).
export function OtpInput({
  valor,
  onChange,
  longitud = 6,
  autoFocus = true,
  invalido = false,
  className,
}: {
  valor: string[];
  onChange: (digitos: string[]) => void;
  longitud?: number;
  autoFocus?: boolean;
  invalido?: boolean;
  className?: string;
}) {
  const refs = useRef<(HTMLInputElement | null)[]>([]);

  function setDigito(i: number, v: string) {
    const limpio = v.replace(/\D/g, "").slice(-1);
    const next = [...valor];
    next[i] = limpio;
    onChange(next);
    if (limpio && i < longitud - 1) refs.current[i + 1]?.focus();
  }

  function onKey(i: number, e: React.KeyboardEvent) {
    if (e.key === "Backspace" && !valor[i] && i > 0) refs.current[i - 1]?.focus();
  }

  function onPaste(e: React.ClipboardEvent) {
    const txt = (e.clipboardData.getData("text") || "").replace(/\D/g, "").slice(0, longitud);
    if (!txt) return;
    e.preventDefault();
    const next = txt.split("");
    while (next.length < longitud) next.push("");
    onChange(next);
    refs.current[Math.min(txt.length, longitud - 1)]?.focus();
  }

  return (
    <div className={cn("flex gap-2.5", className)} onPaste={onPaste}>
      {valor.map((v, i) => (
        <input
          key={i}
          ref={(el) => {
            refs.current[i] = el;
          }}
          value={v}
          inputMode="numeric"
          maxLength={1}
          autoFocus={autoFocus && i === 0}
          aria-label={`Dígito ${i + 1}`}
          aria-invalid={invalido || undefined}
          onChange={(e) => setDigito(i, e.target.value)}
          onKeyDown={(e) => onKey(i, e)}
          data-filled={v ? "true" : "false"}
          className="h-12 w-full rounded-lg border bg-card text-center font-mono text-[22px] font-semibold text-foreground outline-none transition-colors focus:border-foreground aria-[invalid]:border-destructive data-[filled=true]:border-foreground"
        />
      ))}
    </div>
  );
}
