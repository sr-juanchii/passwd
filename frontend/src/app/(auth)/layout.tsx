import { ShieldCheck } from "lucide-react";
import { ThemeToggle } from "@/components/theme-toggle";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-muted/30 px-4 py-10">
      <div className="absolute right-4 top-4">
        <ThemeToggle />
      </div>
      <div className="mb-6 flex items-center gap-2 text-lg font-semibold">
        <ShieldCheck className="h-6 w-6 text-primary" />
        <span>Gestor de Contraseñas</span>
      </div>
      <div className="w-full max-w-md">{children}</div>
      <p className="mt-8 max-w-md text-center text-xs text-muted-foreground">
        Acceso restringido. Toda actividad queda registrada en la bitácora de auditoría.
      </p>
    </div>
  );
}
