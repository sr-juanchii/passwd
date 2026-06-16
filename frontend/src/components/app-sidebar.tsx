"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  KeyRound,
  ScrollText,
  Search,
  ServerCog,
  ShieldCheck,
  Upload,
  Users,
} from "lucide-react";
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
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
  { titulo: "Buscar", url: "/buscar", icono: Search, permiso: "inventario.ver" },
  { titulo: "Importar", url: "/importar", icono: Upload, permiso: "inventario.gestionar" },
];

const ADMINISTRACION: Item[] = [
  { titulo: "Métricas", url: "/metricas", icono: Activity, permiso: "metricas.ver" },
  { titulo: "Usuarios", url: "/usuarios", icono: Users, permiso: "usuarios.gestionar" },
  { titulo: "Tokens API", url: "/tokens", icono: KeyRound, permiso: "tokens.gestionar" },
  { titulo: "Auditoría", url: "/auditoria", icono: ScrollText, permiso: "auditoria.ver" },
];

function Grupo({ etiqueta, items }: { etiqueta: string; items: Item[] }) {
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
            return (
              <SidebarMenuItem key={item.url}>
                <SidebarMenuButton asChild isActive={activo} tooltip={item.titulo}>
                  <Link href={item.url}>
                    <item.icono className="h-4 w-4" />
                    <span>{item.titulo}</span>
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>
            );
          })}
        </SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  );
}

export function AppSidebar() {
  return (
    <Sidebar>
      <SidebarHeader>
        <div className="flex items-center gap-2 px-2 py-1.5 text-sm font-semibold">
          <ShieldCheck className="h-5 w-5 text-primary" />
          <span className="truncate">Gestor de Contraseñas</span>
        </div>
      </SidebarHeader>
      <SidebarContent>
        <Grupo etiqueta="Principal" items={PRINCIPAL} />
        <Grupo etiqueta="Administración" items={ADMINISTRACION} />
      </SidebarContent>
    </Sidebar>
  );
}
