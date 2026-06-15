"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  Clipboard,
  KeyRound,
  Loader2,
  MoreHorizontal,
  Plus,
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

export default function UsuariosPage() {
  const { puede } = useSession();
  const [usuarios, setUsuarios] = useState<Usuario[]>([]);
  const [cargando, setCargando] = useState(true);

  // Diálogo de cambio de rol.
  const [rolUsuario, setRolUsuario] = useState<Usuario | null>(null);
  const [rolSeleccionado, setRolSeleccionado] = useState<Rol>("operador");
  const [guardandoRol, setGuardandoRol] = useState(false);

  // Diálogo de confirmación de reset MFA.
  const [mfaUsuario, setMfaUsuario] = useState<Usuario | null>(null);

  // Diálogo de contraseña temporal.
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
      <div className="space-y-6">
        <PageHeader titulo="Usuarios" />
        <p className="rounded-md border border-dashed p-10 text-center text-sm text-muted-foreground">
          No tiene permiso para gestionar usuarios.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        titulo="Usuarios"
        descripcion="Gestione las cuentas, roles y autenticación de los usuarios."
        acciones={
          <Button asChild>
            <Link href="/usuarios/nuevo">
              <Plus className="h-4 w-4" /> Nuevo usuario
            </Link>
          </Button>
        }
      />

      {cargando ? (
        <div className="flex items-center justify-center p-10">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : usuarios.length === 0 ? (
        <p className="rounded-md border border-dashed p-10 text-center text-sm text-muted-foreground">
          No hay usuarios registrados.
        </p>
      ) : (
        <div className="rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Usuario</TableHead>
                <TableHead>Nombre</TableHead>
                <TableHead>Email</TableHead>
                <TableHead>Rol</TableHead>
                <TableHead>MFA</TableHead>
                <TableHead>Estado</TableHead>
                <TableHead className="text-right">Acciones</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {usuarios.map((u) => (
                <TableRow key={u.id}>
                  <TableCell className="font-mono">{u.username}</TableCell>
                  <TableCell>{u.nombre_completo}</TableCell>
                  <TableCell>{u.email}</TableCell>
                  <TableCell>
                    <Badge variant="secondary">{u.rol_label}</Badge>
                  </TableCell>
                  <TableCell>
                    {u.mfa_habilitado ? (
                      <Badge variant="default">Sí</Badge>
                    ) : (
                      <Badge variant="outline">No</Badge>
                    )}
                  </TableCell>
                  <TableCell>
                    {u.activo ? (
                      <Badge variant="default">Activo</Badge>
                    ) : (
                      <Badge variant="destructive">Inactivo</Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-right">
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button size="icon" variant="ghost" title="Acciones">
                          <MoreHorizontal className="h-4 w-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem onSelect={() => abrirRol(u)}>
                          <UserCheck className="h-4 w-4" /> Cambiar rol
                        </DropdownMenuItem>
                        <DropdownMenuItem onSelect={() => void resetPassword(u)}>
                          <KeyRound className="h-4 w-4" /> Restablecer contraseña
                        </DropdownMenuItem>
                        <DropdownMenuItem onSelect={() => setMfaUsuario(u)}>
                          <ShieldOff className="h-4 w-4" /> Restablecer MFA
                        </DropdownMenuItem>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem onSelect={() => void alternarActivo(u)}>
                          {u.activo ? (
                            <>
                              <UserX className="h-4 w-4" /> Desactivar
                            </>
                          ) : (
                            <>
                              <UserCheck className="h-4 w-4" /> Reactivar
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
        </div>
      )}

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
              {guardandoRol && <Loader2 className="h-4 w-4 animate-spin" />}
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
            <code className="flex-1 rounded bg-muted px-3 py-2 font-mono text-sm break-all">
              {passwordTemporal?.password}
            </code>
            <Button
              size="icon"
              variant="outline"
              onClick={() => passwordTemporal && void copiar(passwordTemporal.password)}
              title="Copiar"
            >
              <Clipboard className="h-4 w-4" />
            </Button>
          </div>
          <DialogFooter>
            <Button onClick={() => setPasswordTemporal(null)}>Cerrar</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
