"use client";

import { useState } from "react";
import { Loader2, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/**
 * Reautenticación del autorizador: contraseña + código de la aplicación
 * autenticadora.
 *
 * El código por correo NO sirve aquí, y el backend lo rechaza: un buzón puede
 * estar compartido o abierto en la misma sesión, de modo que no acredita a una
 * segunda persona, que es justo lo que la regla de dos pares exige.
 */
export function DialogoAutorizar({
  titulo,
  descripcion,
  textoBoton,
  disparador,
  onConfirmar,
}: {
  titulo: string;
  descripcion: string;
  textoBoton: string;
  disparador: React.ReactNode;
  onConfirmar: (password: string, codigo: string) => Promise<void>;
}) {
  const [abierto, setAbierto] = useState(false);
  const [password, setPassword] = useState("");
  const [codigo, setCodigo] = useState("");
  const [enviando, setEnviando] = useState(false);

  async function confirmar(e: React.FormEvent) {
    e.preventDefault();
    setEnviando(true);
    try {
      await onConfirmar(password, codigo);
      setAbierto(false);
      setPassword("");
      setCodigo("");
    } finally {
      setEnviando(false);
    }
  }

  return (
    <Dialog open={abierto} onOpenChange={setAbierto}>
      <DialogTrigger asChild>{disparador}</DialogTrigger>
      <DialogContent>
        <form onSubmit={confirmar}>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <ShieldCheck className="size-4" /> {titulo}
            </DialogTitle>
            <DialogDescription>{descripcion}</DialogDescription>
          </DialogHeader>
          <div className="my-4 space-y-4">
            <div className="space-y-2">
              <Label htmlFor="reauth-password">Su contraseña</Label>
              <Input
                id="reauth-password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="reauth-codigo">Código de su aplicación autenticadora</Label>
              <Input
                id="reauth-codigo"
                inputMode="numeric"
                autoComplete="one-time-code"
                required
                className="font-mono"
                value={codigo}
                onChange={(e) => setCodigo(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                El código enviado por correo no sirve para autorizar una rotación.
              </p>
            </div>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setAbierto(false)}>
              Cancelar
            </Button>
            <Button type="submit" disabled={enviando}>
              {enviando && <Loader2 className="size-4 animate-spin" />}
              {textoBoton}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
