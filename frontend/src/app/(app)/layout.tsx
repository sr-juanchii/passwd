"use client";

import { useEffect } from "react";
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

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { authenticated, stage, cargando } = useSession();

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
      <div className="flex min-h-screen items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset>
        <AppHeader />
        <main className="flex-1 p-4 md:p-6">{children}</main>
      </SidebarInset>
    </SidebarProvider>
  );
}
