"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/app-sidebar";
import { AppHeader } from "@/components/app-header";
import { useSession } from "@/lib/session";

const DESTINO_ETAPA: Record<string, string> = {
  cambio_password: "/password/cambiar",
  mfa_enrolamiento: "/mfa/configurar",
  mfa_pendiente: "/mfa/verificar",
};

// El primitivo ui/sidebar.tsx persiste el colapso en la cookie `sidebar_state`;
// aquí solo se lee para arrancar con el último estado elegido.
function sidebarAbiertaInicial(): boolean {
  if (typeof document === "undefined") return true;
  const par = document.cookie
    .split("; ")
    .find((c) => c.startsWith("sidebar_state="));
  return par ? par.split("=")[1] === "true" : true;
}

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { authenticated, stage, cargando } = useSession();
  const [sidebarAbierta] = useState(sidebarAbiertaInicial);

  useEffect(() => {
    if (cargando) return;
    if (!authenticated) {
      router.replace("/login");
      return;
    }
    if (stage && stage !== "activa") {
      router.replace(DESTINO_ETAPA[stage] ?? "/login");
    }
  }, [authenticated, stage, cargando, router]);

  if (cargando || !authenticated || (stage && stage !== "activa")) {
    return (
      <div className="flex min-h-svh items-center justify-center bg-background">
        <Loader2 className="size-5 animate-spin text-muted-foreground/70" aria-hidden="true" />
        <span className="sr-only">Comprobando su sesión…</span>
      </div>
    );
  }

  return (
    <SidebarProvider defaultOpen={sidebarAbierta}>
      <AppSidebar />
      <SidebarInset>
        <AppHeader />
        <main className="flex-1 p-4 md:p-6">
          <div className="mx-auto w-full max-w-[1180px]">{children}</div>
        </main>
      </SidebarInset>
    </SidebarProvider>
  );
}
