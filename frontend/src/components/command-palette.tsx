"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Activity,
  Cpu,
  KeyRound,
  MonitorSmartphone,
  ScrollText,
  Search,
  Server,
  ServerCog,
  Upload,
  Users,
} from "lucide-react";
import {
  Command,
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Mono } from "@/components/ui/mono";
import { api } from "@/lib/api";
import { rutaActivo } from "@/lib/constants";
import { useSession } from "@/lib/session";
import type { Permiso, ResultadoBusqueda, TipoActivo } from "@/lib/types";

const NAV: { titulo: string; url: string; icono: typeof Search; permiso: Permiso }[] = [
  { titulo: "Ir a Inventario", url: "/", icono: ServerCog, permiso: "inventario.ver" },
  { titulo: "Ir a Buscar", url: "/buscar", icono: Search, permiso: "inventario.ver" },
  { titulo: "Importar CSV", url: "/importar", icono: Upload, permiso: "inventario.gestionar" },
  { titulo: "Ir a Métricas", url: "/metricas", icono: Activity, permiso: "metricas.ver" },
  { titulo: "Ir a Usuarios", url: "/usuarios", icono: Users, permiso: "usuarios.gestionar" },
  { titulo: "Ir a Auditoría", url: "/auditoria", icono: ScrollText, permiso: "auditoria.ver" },
];

const ICONO_TIPO: Record<TipoActivo, typeof Server> = {
  fisico: Server,
  hipervisor: Cpu,
  vm: MonitorSmartphone,
};

interface ActivoRef {
  key: string;
  tipo: TipoActivo;
  id: number;
  nombre: string;
  meta?: string;
}

function aplanar(r: ResultadoBusqueda): ActivoRef[] {
  return [
    ...r.servidores.map((s) => ({
      key: `f${s.id}`,
      tipo: "fisico" as const,
      id: s.id,
      nombre: s.nombre,
      meta: s.ip_gestion,
    })),
    ...r.hipervisores.map((h) => ({
      key: `h${h.id}`,
      tipo: "hipervisor" as const,
      id: h.id,
      nombre: h.nombre,
      meta: h.plataforma,
    })),
    ...r.vms.map((v) => ({
      key: `v${v.id}`,
      tipo: "vm" as const,
      id: v.id,
      nombre: v.nombre,
      meta: v.sistema_operativo,
    })),
  ];
}

export function CommandPalette({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const router = useRouter();
  const { puede } = useSession();
  const [q, setQ] = useState("");
  const [activos, setActivos] = useState<ActivoRef[]>([]);
  const [creds, setCreds] = useState<ResultadoBusqueda["credenciales"]>([]);

  useEffect(() => {
    const term = q.trim();
    if (term.length < 2) {
      setActivos([]);
      setCreds([]);
      return;
    }
    let vivo = true;
    const id = setTimeout(() => {
      api
        .buscar(term)
        .then((r) => {
          if (!vivo) return;
          setActivos(aplanar(r).slice(0, 6));
          setCreds(r.credenciales.slice(0, 5));
        })
        .catch(() => {});
    }, 200);
    return () => {
      vivo = false;
      clearTimeout(id);
    };
  }, [q]);

  // Limpia la consulta cada vez que se cierra el panel.
  useEffect(() => {
    if (!open) setQ("");
  }, [open]);

  function ir(url: string) {
    onOpenChange(false);
    router.push(url);
  }

  const ql = q.trim().toLowerCase();
  const navs = NAV.filter((n) => puede(n.permiso) && (!ql || n.titulo.toLowerCase().includes(ql)));

  return (
    <CommandDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Paleta de comandos"
      description="Buscar activos o navegar"
    >
      <Command shouldFilter={false}>
        <CommandInput placeholder="Buscar activos o ir a…" value={q} onValueChange={setQ} />
        <CommandList>
          <CommandEmpty>Sin resultados.</CommandEmpty>
          {activos.length > 0 && (
            <CommandGroup heading="Activos">
              {activos.map((a) => {
                const Icono = ICONO_TIPO[a.tipo];
                return (
                  <CommandItem
                    key={a.key}
                    value={a.key}
                    onSelect={() => ir(rutaActivo(a.tipo, a.id))}
                  >
                    <Icono className="text-muted-foreground" />
                    <Mono className="font-medium">{a.nombre}</Mono>
                    {a.meta && (
                      <span className="ml-auto text-xs text-muted-foreground">{a.meta}</span>
                    )}
                  </CommandItem>
                );
              })}
            </CommandGroup>
          )}
          {creds.length > 0 && (
            <CommandGroup heading="Credenciales">
              {creds.map((c) => (
                <CommandItem
                  key={`c${c.id}`}
                  value={`c${c.id}`}
                  onSelect={() => ir(rutaActivo(c.tipo_activo, c.activo_id))}
                >
                  <KeyRound className="text-muted-foreground" />
                  <Mono className="font-medium">{c.usuario_acceso}</Mono>
                  <span className="ml-auto text-xs text-muted-foreground">{c.servicio}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          )}
          {navs.length > 0 && (
            <CommandGroup heading="Navegación">
              {navs.map((n) => (
                <CommandItem key={n.url} value={`nav:${n.url}`} onSelect={() => ir(n.url)}>
                  <n.icono className="text-muted-foreground" />
                  {n.titulo}
                </CommandItem>
              ))}
            </CommandGroup>
          )}
        </CommandList>
      </Command>
    </CommandDialog>
  );
}
