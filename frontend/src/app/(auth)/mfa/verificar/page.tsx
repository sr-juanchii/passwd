"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useSession } from "@/lib/session";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { toast } from "sonner";

export default function MfaVerificarPage() {
  const router = useRouter();
  const { refrescar } = useSession();
  const [codigo, setCodigo] = useState("");
  const [error, setError] = useState("");
  const [enviando, setEnviando] = useState(false);

  async function enviar(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setEnviando(true);
    try {
      const r = await api.mfaVerificar(codigo);
      await refrescar();
      if (r.aviso) toast.warning(r.aviso, { duration: 10000 });
      router.replace("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Código incorrecto.");
      setEnviando(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Verificación en dos pasos</CardTitle>
        <CardDescription>
          Introduzca el código de 6 dígitos de su aplicación autenticadora, o un código de
          recuperación si perdió el dispositivo.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={enviar} className="space-y-4">
          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          <div className="space-y-2">
            <Label htmlFor="codigo">Código</Label>
            <Input
              id="codigo"
              autoComplete="one-time-code"
              autoFocus
              placeholder="000000 o XXXXX-XXXXX"
              required
              value={codigo}
              onChange={(e) => setCodigo(e.target.value)}
            />
          </div>
          <Button type="submit" className="w-full" disabled={enviando}>
            {enviando && <Loader2 className="h-4 w-4 animate-spin" />}
            Verificar
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
