"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  Clipboard,
  KeyRound,
  Loader2,
  MoreHorizontal,
  Plus,
  Search,
  ShieldAlert,
  ShieldCheck,
  ShieldOff,
  UserCheck,
  UserX,
} from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { Rol, Usuario } from "@/lib/types";
import { ETIQUETAS_ROL } from "@/lib/constants";
import { useSession } from "@/lib/session";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Mono } from "@/components/ui/mono";
import { EstadoBadge } from "@/components/estado-badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";

const ROLES = Object.keys(ETIQUETAS_ROL) as Rol[];

const ROL_DESC: Record<Rol, string> = {
  admin: "Control total: usuarios, activos, concesiones.",
  operador: "Gestiona activos y credenciales.",
  auditor: "Solo lectura de bitácora y métricas.",
  analista: "Acceso únicamente a activos concedidos.",
};

function iniciales(nombre: string, username: string): string {
  const base = (nombre || username || "?").trim().split(/\s+/).filter(Boolean);
  if (base.length === 0) return "?";
  if (base.length === 1) return base[0].slice(0, 2).toUpperCase();
  return (base[0][0] + base[1][0]).toUpperCase();
}

export default function UsuariosPage() {
  const { puede } = useSession();
  const [usuarios, setUsuarios] = useState<Usuario[]>([]);
  const [cargando, setCargando] = useState(true);
  const [filtro, setFiltro] = useState("");

  const [rolUsuario, setRolUsuario] = useState<Usuario | null>(null);
  const [rolSeleccionado, setRolSeleccionado] = useState<Rol>("operador");
  const [guardandoRol, setGuardandoRol] = useState(false);
  const [mfaUsuario, setMfaUsuario] = useState<Usuario | null>(null);
  const [passwordTemporal, setPasswordTemporal] = useState<{ username: string; password: string } | null>(null);

  const cargar = useCallback(async () => {
    setCargando(true);
    try {
      const r = await api.usuarios();
      setUsuarios(r.usuarios);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "No se pudieron cargar los usuarios.");
    } finally {
      setCargando(false);
    }
  }, []);

  useEffect(() => {
    void cargar();
  }, [cargar]);

  const conteos = useMemo(
    () => ROLES.map((r) => [r, usuarios.filter((u) => u.rol === r).length] as const),
    [usuarios],
  );

  const visibles = useMemo(() => {
    const q = filtro.trim().toLowerCase();
    if (!q) return usuarios;
    return usuarios.filter((u) =>
      (u.nombre_completo + u.username + u.email + u.rol_label).toLowerCase().includes(q),
    );
  }, [usuarios, filtro]);

  function abrirRol(u: Usuario) {
    setRolUsuario(u);
    setRolSeleccionado(u.rol);
  }

  async function guardarRol() {
    if (!rolUsuario) return;
    setGuardandoRol(true);
    try {
      await api.cambiarRol(rolUsuario.id, rolSeleccionado);
      toast.success(`Rol de ${rolUsuario.username} actualizado.`);
      setRolUsuario(null);
      await cargar();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "No se pudo cambiar el rol.");
    } finally {
      setGuardandoRol(false);
    }
  }

  async function alternarActivo(u: Usuario) {
    try {
      if (u.activo) {
        await api.desactivarUsuario(u.id);
        toast.success(`Usuario ${u.username} desactivado.`);
      } else {
        await api.reactivarUsuario(u.id);
        toast.success(`Usuario ${u.username} reactivado.`);
      }
      await cargar();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "No se pudo actualizar el usuario.");
    }
  }

  async function resetPassword(u: Usuario) {
    try {
      const r = await api.resetPassword(u.id);
      setPasswordTemporal({ username: r.username, password: r.password_temporal });
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "No se pudo restablecer la contraseña.");
    }
  }

  async function resetMfa() {
    if (!mfaUsuario) return;
    try {
      await api.resetMfa(mfaUsuario.id);
      toast.success(`MFA de ${mfaUsuario.username} restablecido.`);
      setMfaUsuario(null);
      await cargar();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "No se pudo restablecer el MFA.");
    }
  }

  async function copiar(texto: string) {
    try {
      await navigator.clipboard.writeText(texto);
      toast.success("Copiado al portapapeles.");
    } catch {
      toast.error("No se pudo copiar.");
    }
  }

  if (!puede("usuarios.gestionar")) {
    return (
      <>
        <PageHeader titulo="Usuarios" />
        <p className="rounded-[14px] border border-dashed p-10 text-center text-sm text-muted-foreground">
          No tiene permiso para gestionar usuarios.
        </p>
      </>
    );
  }

  return (
    <>
      <PageHeader
        titulo="Usuarios"
        descripcion="Cuentas y control de acceso basado en roles."
        acciones={
          <Button asChild>
            <Link href="/usuarios/nuevo">
              <Plus /> Nuevo usuario
            </Link>
          </Button>
        }
      />

      <div className="flex flex-col gap-4">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {conteos.map(([r, n]) => (
            <div key={r} className="flex flex-col gap-1.5 rounded-[14px] border bg-card p-4">
              <div className="flex items-center justify-between">
                <span className="text-[13px] font-semibold">{ETIQUETAS_ROL[r]}</span>
                <Mono className="text-base font-semibold">{n}</Mono>
              </div>
              <span className="text-[11.5px] leading-snug text-muted-foreground">{ROL_DESC[r]}</span>
            </div>
          ))}
        </div>

        <div className="relative max-w-xs">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-[15px] -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Filtrar usuarios…"
            className="pl-8"
            value={filtro}
            onChange={(e) => setFiltro(e.target.value)}
          />
        </div>

        {cargando ? (
          <div className="flex items-center justify-center p-10">
            <Loader2 className="size-6 animate-spin text-muted-foreground" />
          </div>
        ) : visibles.length === 0 ? (
          <p className="rounded-[14px] border border-dashed p-10 text-center text-sm text-muted-foreground">
            {usuarios.length === 0 ? "No hay usuarios registrados." : "Sin coincidencias."}
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Usuario</TableHead>
                <TableHead>Rol</TableHead>
                <TableHead>MFA</TableHead>
                <TableHead>Estado</TableHead>
                <TableHead>Último acceso</TableHead>
                <TableHead className="text-right">Acciones</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visibles.map((u) => (
                <TableRow key={u.id}>
                  <TableCell>
                    <div className="flex items-center gap-2.5">
                      <span className="flex size-[30px] shrink-0 items-center justify-center rounded-lg bg-muted text-[11.5px] font-semibold">
                        {iniciales(u.nombre_completo, u.username)}
                      </span>
                      <div>
                        <div className="text-[13px] font-medium">{u.nombre_completo || u.username}</div>
                        <Mono className="text-xs text-muted-foreground">{u.username}</Mono>
                      </div>
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge variant={u.rol === "admin" ? "default" : "secondary"}>{u.rol_label}</Badge>
                  </TableCell>
                  <TableCell>
                    {u.mfa_habilitado ? (
                      <span className="inline-flex items-center gap-1.5 text-[12.5px] text-muted-foreground">
                        <ShieldCheck className="size-3.5" /> Activo
                      </span>
                    ) : (
                      <Badge variant="destructive" className="gap-1">
                        <ShieldAlert /> Sin MFA
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell>
                    {u.activo ? (
                      <EstadoBadge estado="activo" />
                    ) : (
                      <Badge variant="destructive">Inactivo</Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-[12.5px] text-muted-foreground">
                    {u.ultimo_acceso ? new Date(u.ultimo_acceso).toLocaleString() : "Nunca"}
                  </TableCell>
                  <TableCell className="text-right">
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button size="icon" variant="ghost" title="Acciones">
                          <MoreHorizontal />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem onSelect={() => abrirRol(u)}>
                          <UserCheck /> Cambiar rol
                        </DropdownMenuItem>
                        <DropdownMenuItem onSelect={() => void resetPassword(u)}>
                          <KeyRound /> Restablecer contraseña
                        </DropdownMenuItem>
                        <DropdownMenuItem onSelect={() => setMfaUsuario(u)}>
                          <ShieldOff /> Restablecer MFA
                        </DropdownMenuItem>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem onSelect={() => void alternarActivo(u)}>
                          {u.activo ? (
                            <>
                              <UserX /> Desactivar
                            </>
                          ) : (
                            <>
                              <UserCheck /> Reactivar
                            </>
                          )}
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>

      {/* Diálogo cambiar rol */}
      <Dialog open={rolUsuario !== null} onOpenChange={(o) => !o && setRolUsuario(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Cambiar rol</DialogTitle>
            <DialogDescription>
              Asigne un nuevo rol a <strong>{rolUsuario?.username}</strong>.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="rol">Rol</Label>
            <Select value={rolSeleccionado} onValueChange={(v) => setRolSeleccionado(v as Rol)}>
              <SelectTrigger id="rol" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {ROLES.map((r) => (
                  <SelectItem key={r} value={r}>
                    {ETIQUETAS_ROL[r]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRolUsuario(null)} disabled={guardandoRol}>
              Cancelar
            </Button>
            <Button onClick={guardarRol} disabled={guardandoRol}>
              {guardandoRol && <Loader2 className="animate-spin" />}
              Guardar
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Diálogo reset MFA */}
      <AlertDialog open={mfaUsuario !== null} onOpenChange={(o) => !o && setMfaUsuario(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>¿Restablecer el MFA?</AlertDialogTitle>
            <AlertDialogDescription>
              Se eliminará la configuración de doble factor de <strong>{mfaUsuario?.username}</strong>.
              El usuario deberá volver a enrolarse en su próximo inicio de sesión.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction onClick={resetMfa}>Restablecer</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Diálogo contraseña temporal */}
      <Dialog open={passwordTemporal !== null} onOpenChange={(o) => !o && setPasswordTemporal(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Contraseña temporal</DialogTitle>
            <DialogDescription>
              Entréguela al usuario <strong>{passwordTemporal?.username}</strong> por un canal seguro.
              Se muestra una sola vez.
            </DialogDescription>
          </DialogHeader>
          <div className="flex items-center gap-2">
            <code className="flex-1 rounded-lg bg-muted px-3 py-2 font-mono text-sm break-all">
              {passwordTemporal?.password}
            </code>
            <Button
              size="icon"
              variant="outline"
              onClick={() => passwordTemporal && void copiar(passwordTemporal.password)}
              title="Copiar"
            >
              <Clipboard />
            </Button>
          </div>
          <DialogFooter>
            <Button onClick={() => setPasswordTemporal(null)}>Cerrar</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
