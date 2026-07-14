"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowLeft, Clipboard, Loader2 } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { Rol } from "@/lib/types";
import { ETIQUETAS_ROL } from "@/lib/constants";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { FormPanel } from "@/components/forms/form-shell";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { toast } from "sonner";

const ROLES = Object.keys(ETIQUETAS_ROL) as Rol[];

export default function NuevoUsuarioPage() {
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [nombre, setNombre] = useState("");
  const [rol, setRol] = useState<Rol>("operador");
  const [enviando, setEnviando] = useState(false);
  const [creado, setCreado] = useState<{ username: string; password_temporal: string } | null>(null);

  async function enviar(e: React.FormEvent) {
    e.preventDefault();
    setEnviando(true);
    try {
      const r = await api.crearUsuario({
        username: username.trim(),
        email: email.trim(),
        nombre_completo: nombre.trim(),
        rol,
      });
      setCreado(r);
      toast.success(`Usuario ${r.username} creado.`);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "No se pudo crear el usuario.");
    } finally {
      setEnviando(false);
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

  return (
    <div className="max-w-xl space-y-6">
      <PageHeader
        titulo="Nuevo usuario"
        descripcion="Cree una cuenta de usuario. Se generará una contraseña temporal."
        migas={[{ label: "Usuarios", href: "/usuarios" }, { label: "Nuevo" }]}
      />

      {creado ? (
        <div className="space-y-4">
          <Alert>
            <AlertTitle>Usuario {creado.username} creado</AlertTitle>
            <AlertDescription className="space-y-3">
              <span>
                Esta contraseña temporal se muestra <strong>una sola vez</strong>. Entréguela al usuario
                por un canal seguro; deberá cambiarla en su primer inicio de sesión.
              </span>
              <span className="flex w-full items-center gap-2">
                <code className="flex-1 rounded-lg bg-muted px-3 py-2 font-mono text-sm break-all">
                  {creado.password_temporal}
                </code>
                <Button
                  size="icon"
                  variant="outline"
                  onClick={() => void copiar(creado.password_temporal)}
                  title="Copiar"
                >
                  <Clipboard />
                </Button>
              </span>
            </AlertDescription>
          </Alert>
          <Button asChild variant="outline">
            <Link href="/usuarios">
              <ArrowLeft /> Volver a usuarios
            </Link>
          </Button>
        </div>
      ) : (
        <form onSubmit={enviar}>
          <FormPanel titulo="Datos del usuario">
            <div className="flex flex-col gap-4 sm:col-span-2">
              <div className="space-y-2">
                <Label htmlFor="username">Usuario<span className="text-destructive"> *</span></Label>
                <Input
                  id="username"
                  autoComplete="off"
                  required
                  className="font-mono"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="email">Email<span className="text-destructive"> *</span></Label>
                <Input
                  id="email"
                  type="email"
                  autoComplete="off"
                  required
                  className="font-mono"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="nombre">Nombre completo<span className="text-destructive"> *</span></Label>
                <Input
                  id="nombre"
                  required
                  value={nombre}
                  onChange={(e) => setNombre(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="rol">Rol</Label>
                <Select value={rol} onValueChange={(v) => setRol(v as Rol)}>
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
            </div>
          </FormPanel>
          <div className="mt-4 flex gap-2">
            <Button type="submit" size="lg" disabled={enviando}>
              {enviando && <Loader2 className="animate-spin" />}
              Crear usuario
            </Button>
            <Button type="button" variant="outline" asChild>
              <Link href="/usuarios">Cancelar</Link>
            </Button>
          </div>
        </form>
      )}
    </div>
  );
}
