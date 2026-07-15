"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Lock } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useSession } from "@/lib/session";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

export default function LoginPage() {
  const router = useRouter();
  const { refrescar } = useSession();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [csrfLogin, setCsrfLogin] = useState("");
  const [error, setError] = useState("");
  const [enviando, setEnviando] = useState(false);

  useEffect(() => {
    api
      .csrfLogin()
      .then((r) => setCsrfLogin(r.csrf_login))
      .catch(() => setError("No se pudo contactar al servidor."));
  }, []);

  async function enviar(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setEnviando(true);
    try {
      const r = await api.login(username, password, csrfLogin);
      await refrescar();
      router.replace(r.next || "/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Error al iniciar sesión.");
      api.csrfLogin().then((c) => setCsrfLogin(c.csrf_login)).catch(() => {});
      setEnviando(false);
    }
  }

  return (
    <div>
      <div className="mb-6">
        <h2 className="text-[22px] font-semibold">Iniciar sesión</h2>
        <p className="mt-1.5 text-[13.5px] text-muted-foreground">
          Introduzca sus credenciales corporativas.
        </p>
      </div>
      <form onSubmit={enviar} className="flex flex-col gap-4">
        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        <div className="flex flex-col gap-2">
          <Label htmlFor="username">Usuario</Label>
          <Input
            id="username"
            autoComplete="username"
            autoFocus
            required
            className="font-mono"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </div>
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between gap-2">
            <Label htmlFor="password" className="shrink-0">
              Contraseña
            </Label>
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  className="truncate rounded-sm text-xs text-muted-foreground underline-offset-2 transition-colors hover:text-foreground hover:underline focus-visible:text-foreground focus-visible:underline focus-visible:outline-none"
                >
                  ¿Olvidó su contraseña?
                </button>
              </TooltipTrigger>
              <TooltipContent>Contacte a un administrador para restablecerla.</TooltipContent>
            </Tooltip>
          </div>
          <Input
            id="password"
            type="password"
            autoComplete="current-password"
            placeholder="••••••••••••"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        <Button type="submit" className="h-10 w-full" disabled={enviando || !csrfLogin}>
          {enviando && <Loader2 className="animate-spin" />}
          Entrar
        </Button>
        <p className="flex items-center justify-center gap-1.5 text-[11.5px] text-muted-foreground">
          <Lock className="size-3" /> Conexión cifrada · MFA obligatorio
        </p>
      </form>
    </div>
  );
}
