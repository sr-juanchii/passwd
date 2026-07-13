"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  KeyRound,
  Lock,
  ScrollText,
  Search,
  ServerCog,
  ShieldCheck,
  Upload,
  Users,
  Wallet,
} from "lucide-react";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from "@/components/ui/sidebar";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { Permiso } from "@/lib/types";

interface Item {
  titulo: string;
  url: string;
  icono: React.ComponentType<{ className?: string }>;
  permiso: Permiso;
}

const PRINCIPAL: Item[] = [
  { titulo: "Inventario", url: "/", icono: ServerCog, permiso: "inventario.ver" },
  { titulo: "Mi vault", url: "/vault", icono: Wallet, permiso: "vault.usar" },
  { titulo: "Buscar", url: "/buscar", icono: Search, permiso: "inventario.ver" },
  { titulo: "Importar", url: "/importar", icono: Upload, permiso: "inventario.gestionar" },
];

const ADMINISTRACION: Item[] = [
  { titulo: "Métricas", url: "/metricas", icono: Activity, permiso: "metricas.ver" },
  { titulo: "Usuarios", url: "/usuarios", icono: Users, permiso: "usuarios.gestionar" },
  { titulo: "Tokens API", url: "/tokens", icono: KeyRound, permiso: "tokens.gestionar" },
  { titulo: "Auditoría", url: "/auditoria", icono: ScrollText, permiso: "auditoria.ver" },
];

function Grupo({
  etiqueta,
  items,
  vencidas,
}: {
  etiqueta: string;
  items: Item[];
  vencidas: number;
}) {
  const { puede } = useSession();
  const pathname = usePathname();
  const visibles = items.filter((i) => puede(i.permiso));
  if (visibles.length === 0) return null;
  return (
    <SidebarGroup>
      <SidebarGroupLabel>{etiqueta}</SidebarGroupLabel>
      <SidebarGroupContent>
        <SidebarMenu>
          {visibles.map((item) => {
            const activo = item.url === "/" ? pathname === "/" : pathname.startsWith(item.url);
            const conAlerta = item.url === "/metricas" && vencidas > 0;
            return (
              <SidebarMenuItem key={item.url}>
                <SidebarMenuButton asChild isActive={activo} tooltip={item.titulo}>
                  <Link href={item.url}>
                    <item.icono className="h-4 w-4" />
                    <span>{item.titulo}</span>
                  </Link>
                </SidebarMenuButton>
                {conAlerta && (
                  <SidebarMenuBadge className="bg-destructive/10 font-mono text-destructive">
                    {vencidas}
                  </SidebarMenuBadge>
                )}
              </SidebarMenuItem>
            );
          })}
        </SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  );
}

export function AppSidebar() {
  const { puede } = useSession();
  const [vencidas, setVencidas] = useState(0);

  // Recuento de credenciales con rotación vencida, para señalar Métricas.
  useEffect(() => {
    if (!puede("metricas.ver")) return;
    let vivo = true;
    api
      .metricas()
      .then((m) => {
        if (vivo) setVencidas(m.rotacion_vencida.length);
      })
      .catch(() => {});
    return () => {
      vivo = false;
    };
  }, [puede]);

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <div className="flex h-12 items-center gap-2.5 px-1.5 group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:px-0">
          <ShieldCheck className="size-[22px] shrink-0 text-foreground" />
          <div className="flex min-w-0 flex-col leading-tight group-data-[collapsible=icon]:hidden">
            <span className="truncate text-sm font-semibold">passwd</span>
            <span className="truncate text-[11px] text-muted-foreground">
              Gestor de Contraseñas
            </span>
          </div>
        </div>
      </SidebarHeader>
      <SidebarContent>
        <Grupo etiqueta="Principal" items={PRINCIPAL} vencidas={vencidas} />
        <Grupo etiqueta="Administración" items={ADMINISTRACION} vencidas={vencidas} />
      </SidebarContent>
      <SidebarFooter>
        <div className="flex items-center gap-2 px-1.5 py-1 text-[11px] leading-snug text-muted-foreground group-data-[collapsible=icon]:hidden">
          <Lock className="size-3.5 shrink-0" />
          <span>Cada acceso queda registrado.</span>
        </div>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}
