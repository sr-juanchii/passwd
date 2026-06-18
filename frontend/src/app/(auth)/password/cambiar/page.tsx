"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { KeyRound, Loader2 } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useSession } from "@/lib/session";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { toast } from "sonner";

export default function CambiarPasswordPage() {
  const router = useRouter();
  const { stage, refrescar } = useSession();
  const forzado = stage === "cambio_password";
  const [actual, setActual] = useState("");
  const [nueva, setNueva] = useState("");
  const [confirmacion, setConfirmacion] = useState("");
  const [error, setError] = useState("");
  const [enviando, setEnviando] = useState(false);

  async function enviar(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setEnviando(true);
    try {
      const r = await api.cambiarPassword({
        password_actual: actual,
        password_nueva: nueva,
        password_confirmacion: confirmacion,
      });
      await refrescar();
      toast.success("Contraseña actualizada correctamente.");
      router.replace(r.next || "/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo cambiar la contraseña.");
      setEnviando(false);
    }
  }

  return (
    <div>
      <div className="mb-6 flex size-11 items-center justify-center rounded-[11px] bg-muted">
        <KeyRound className="size-[22px] text-foreground" />
      </div>
      <h2 className="text-[22px] font-semibold">
        {forzado ? "Cambio de contraseña requerido" : "Cambiar contraseña"}
      </h2>
      <p className="mt-1.5 text-[13.5px] leading-normal text-muted-foreground">
        {forzado
          ? "Su contraseña inicial es de un solo uso. Defina una nueva para continuar."
          : "Mínimo 12 caracteres, sin palabras comunes ni su nombre de usuario."}
      </p>

      <form onSubmit={enviar} className="mt-6 flex flex-col gap-4">
        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        <div className="flex flex-col gap-2">
          <Label htmlFor="actual">Contraseña actual</Label>
          <Input
            id="actual"
            type="password"
            autoComplete="current-password"
            required
            value={actual}
            onChange={(e) => setActual(e.target.value)}
          />
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="nueva">Nueva contraseña</Label>
          <Input
            id="nueva"
            type="password"
            autoComplete="new-password"
            required
            minLength={12}
            value={nueva}
            onChange={(e) => setNueva(e.target.value)}
          />
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="confirmacion">Confirmar nueva contraseña</Label>
          <Input
            id="confirmacion"
            type="password"
            autoComplete="new-password"
            required
            value={confirmacion}
            onChange={(e) => setConfirmacion(e.target.value)}
          />
        </div>
        <Button type="submit" className="h-10 w-full" disabled={enviando}>
          {enviando && <Loader2 className="animate-spin" />}
          Guardar
        </Button>
      </form>
    </div>
  );
}
