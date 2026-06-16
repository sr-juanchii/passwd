"use client";

import { useRouter } from "next/navigation";
import Link from "next/link";
import { useState } from "react";
import { KeyRound, LogOut, Search, UserCircle } from "lucide-react";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { Separator } from "@/components/ui/separator";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ThemeToggle } from "@/components/theme-toggle";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";

export function AppHeader() {
  const router = useRouter();
  const { usuario, refrescar } = useSession();
  const [q, setQ] = useState("");

  function buscar(e: React.FormEvent) {
    e.preventDefault();
    if (q.trim()) router.push(`/buscar?q=${encodeURIComponent(q.trim())}`);
  }

  async function cerrarSesion() {
    try {
      await api.logout();
    } finally {
      await refrescar();
      router.replace("/login");
    }
  }

  return (
    <header className="sticky top-0 z-10 flex h-14 shrink-0 items-center gap-2 border-b bg-background/95 px-4 backdrop-blur">
      <SidebarTrigger />
      <Separator orientation="vertical" className="mr-1 h-5" />
      <form onSubmit={buscar} className="relative hidden flex-1 sm:block max-w-md">
        <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
        <Input
          type="search"
          placeholder="Buscar activos o credenciales…"
          className="pl-8"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </form>
      <div className="ml-auto flex items-center gap-1">
        <ThemeToggle />
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" className="gap-2">
              <UserCircle className="h-5 w-5" />
              <span className="hidden md:inline">{usuario?.username}</span>
              {usuario && (
                <Badge variant="secondary" className="hidden md:inline-flex">
                  {usuario.rol_label}
                </Badge>
              )}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            <DropdownMenuLabel>
              <div className="flex flex-col">
                <span>{usuario?.nombre_completo || usuario?.username}</span>
                <span className="text-xs font-normal text-muted-foreground">{usuario?.email}</span>
              </div>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem asChild>
              <Link href="/password/cambiar">
                <KeyRound className="h-4 w-4" /> Cambiar contraseña
              </Link>
            </DropdownMenuItem>
            <DropdownMenuItem onClick={cerrarSesion} variant="destructive">
              <LogOut className="h-4 w-4" /> Cerrar sesión
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}
