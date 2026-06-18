"use client";

import { usePathname } from "next/navigation";
import { Lock, ScrollText, ShieldCheck } from "lucide-react";
import { ThemeToggle } from "@/components/theme-toggle";
import { cn } from "@/lib/utils";

const PASOS: [string, string][] = [
  ["login", "Identidad"],
  ["mfa", "Verificación"],
  ["app", "Sesión"],
];

const CARACTERISTICAS: [React.ComponentType<{ className?: string }>, string][] = [
  [Lock, "Cifrado en reposo y en tránsito"],
  [ShieldCheck, "Doble factor para cada cuenta"],
  [ScrollText, "Auditoría inmutable de solo anexado"],
];

function pasoActual(path: string): number {
  if (path.startsWith("/login")) return 0;
  if (path.startsWith("/mfa") || path.startsWith("/password")) return 1;
  return 0;
}

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const idx = pasoActual(pathname);

  return (
    <div className="grid min-h-screen bg-background lg:grid-cols-[1.1fr_1fr]">
      <div className="absolute top-4 right-4 z-10">
        <ThemeToggle />
      </div>

      {/* Panel de marca */}
      <div className="hidden flex-col justify-between border-r bg-sidebar p-12 lg:flex">
        <div className="flex items-center gap-2.5">
          <ShieldCheck className="size-[26px] text-foreground" />
          <div className="leading-tight">
            <div className="text-base font-semibold">passwd</div>
            <div className="text-xs text-muted-foreground">Gestor de Contraseñas</div>
          </div>
        </div>

        <div className="max-w-[380px]">
          <h1 className="text-[30px] leading-tight font-semibold tracking-[-0.02em]">
            Custodia de credenciales de su infraestructura.
          </h1>
          <p className="mt-3.5 text-sm leading-relaxed text-muted-foreground">
            Acceso por denegación predeterminada, MFA obligatorio y bitácora exhaustiva. Cada
            acceso a una contraseña queda registrado.
          </p>
          <div className="mt-7 flex flex-col gap-3.5">
            {CARACTERISTICAS.map(([Icono, t]) => (
              <div key={t} className="flex items-center gap-3">
                <div className="flex size-8 items-center justify-center rounded-lg bg-muted">
                  <Icono className="size-4 text-foreground" />
                </div>
                <span className="text-[13.5px]">{t}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-2.5">
          {PASOS.map((p, i) => (
            <div key={p[0]} className="flex items-center gap-2.5">
              <div className={cn("flex items-center gap-1.5", i <= idx ? "opacity-100" : "opacity-40")}>
                <span
                  className={cn(
                    "flex size-[18px] items-center justify-center rounded-full border text-[10px] font-semibold",
                    i < idx
                      ? "border-primary bg-primary text-primary-foreground"
                      : i === idx
                        ? "border-primary text-foreground"
                        : "border-border text-muted-foreground",
                  )}
                >
                  {i < idx ? "✓" : i + 1}
                </span>
                <span
                  className={cn(
                    "text-xs",
                    i === idx ? "font-semibold text-foreground" : "text-muted-foreground",
                  )}
                >
                  {p[1]}
                </span>
              </div>
              {i < PASOS.length - 1 && <div className="h-px w-[18px] bg-border" />}
            </div>
          ))}
        </div>
      </div>

      {/* Panel del formulario */}
      <div className="flex items-center justify-center p-6 sm:p-10">
        <div className="w-full max-w-[360px]">{children}</div>
      </div>
    </div>
  );
}
