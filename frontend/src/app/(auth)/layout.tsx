"use client";

import { usePathname } from "next/navigation";
import { Lock, ScrollText, ShieldCheck } from "lucide-react";
import { ThemeToggle } from "@/components/theme-toggle";
import { cn } from "@/lib/utils";

// Stepper con solo pasos alcanzables del flujo de autenticación: el cambio de
// contraseña forzado (clave de un solo uso) ocurre entre el login y el MFA, así
// que /password/cambiar es el paso «Credenciales» propio. «Sesión» se eliminó:
// nunca se alcanzaba dentro de este layout.
const PASOS: [string, string][] = [
  ["login", "Identidad"],
  ["password", "Credenciales"],
  ["mfa", "Verificación"],
];

const CARACTERISTICAS: [React.ComponentType<{ className?: string }>, string][] = [
  [Lock, "Cifrado en reposo y en tránsito"],
  [ShieldCheck, "Doble factor para cada cuenta"],
  [ScrollText, "Auditoría inmutable de solo anexado"],
];

function pasoActual(path: string): number {
  if (path.startsWith("/password")) return 1;
  if (path.startsWith("/mfa")) return 2;
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
      <div className="relative hidden overflow-hidden border-r bg-sidebar lg:block">
        {/* Patrón de puntos sutil, CSS puro (sin recursos externos: CSP §7) */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0"
          style={{
            backgroundImage:
              "radial-gradient(color-mix(in oklab, var(--foreground) 6%, transparent) 1px, transparent 1px)",
            backgroundSize: "22px 22px",
          }}
        />
        {/* Halo radial muy suave en la esquina superior izquierda */}
        <div
          aria-hidden
          className="pointer-events-none absolute -top-40 -left-40 size-[480px] rounded-full"
          style={{
            background:
              "radial-gradient(closest-side, color-mix(in oklab, var(--foreground) 5%, transparent), transparent)",
          }}
        />

        <div className="relative flex h-full flex-col justify-between p-12">
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
      </div>

      {/* Panel del formulario */}
      <div className="flex items-center justify-center p-6 sm:p-10">
        <div className="w-full max-w-[360px]">{children}</div>
      </div>
    </div>
  );
}
