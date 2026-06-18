"use client";

import { useRouter } from "next/navigation";
import Link from "next/link";
import { useEffect, useState } from "react";
import { ChevronDown, KeyRound, LogOut, Search } from "lucide-react";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { Badge } from "@/components/ui/badge";
import { Kbd } from "@/components/ui/mono";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ThemeToggle } from "@/components/theme-toggle";
import { CommandPalette } from "@/components/command-palette";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";

function iniciales(nombre: string | undefined, username: string | undefined): string {
  const base = (nombre || username || "?").trim();
  const partes = base.split(/\s+/).filter(Boolean);
  if (partes.length === 0) return "?";
  if (partes.length === 1) return partes[0].slice(0, 2).toUpperCase();
  return (partes[0][0] + partes[1][0]).toUpperCase();
}

export function AppHeader() {
  const router = useRouter();
  const { usuario, refrescar } = useSession();
  const [cmd, setCmd] = useState(false);

  // ⌘K / Ctrl+K abre la paleta de comandos.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setCmd((v) => !v);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  async function cerrarSesion() {
    try {
      await api.logout();
    } finally {
      await refrescar();
      router.replace("/login");
    }
  }

  return (
    <header className="sticky top-0 z-20 flex h-14 shrink-0 items-center gap-3 border-b bg-background/90 px-4 backdrop-blur">
      <SidebarTrigger className="size-8 rounded-[9px] border bg-card text-muted-foreground" />

      <button
        type="button"
        onClick={() => setCmd(true)}
        className="flex h-9 max-w-md flex-1 items-center gap-2.5 rounded-[10px] border bg-card px-3 text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        <Search className="size-4 shrink-0" />
        <span className="flex-1 truncate text-left">
          Buscar activos, credenciales, usuarios…
        </span>
        <Kbd className="hidden sm:inline-flex">⌘K</Kbd>
      </button>

      <div className="ml-auto flex items-center gap-1.5">
        <ThemeToggle />
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              className="flex h-9 items-center gap-2 rounded-[9px] border bg-card pr-2 pl-1.5 transition-colors hover:bg-muted"
            >
              <span className="flex size-[26px] items-center justify-center rounded-[7px] bg-primary text-[11.5px] font-semibold text-primary-foreground">
                {iniciales(usuario?.nombre_completo, usuario?.username)}
              </span>
              <span className="hidden text-sm font-medium text-foreground sm:inline">
                {usuario?.username}
              </span>
              <ChevronDown className="size-3.5 text-muted-foreground" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-60">
            <DropdownMenuLabel>
              <div className="flex flex-col gap-1">
                <span className="text-sm font-semibold">
                  {usuario?.nombre_completo || usuario?.username}
                </span>
                <span className="font-mono text-xs font-normal text-muted-foreground">
                  {usuario?.email}
                </span>
                {usuario && (
                  <Badge variant="secondary" className="mt-1 w-fit">
                    {usuario.rol_label}
                  </Badge>
                )}
              </div>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem asChild>
              <Link href="/password/cambiar">
                <KeyRound className="size-4" /> Cambiar contraseña
              </Link>
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={cerrarSesion} variant="destructive">
              <LogOut className="size-4" /> Cerrar sesión
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      <CommandPalette open={cmd} onOpenChange={setCmd} />
    </header>
  );
}
