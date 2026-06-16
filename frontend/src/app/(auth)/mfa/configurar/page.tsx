"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Image from "next/image";
import { Copy, Loader2 } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useSession } from "@/lib/session";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { toast } from "sonner";

export default function MfaConfigurarPage() {
  const router = useRouter();
  const { refrescar } = useSession();
  const [qr, setQr] = useState("");
  const [secreto, setSecreto] = useState("");
  const [codigo, setCodigo] = useState("");
  const [error, setError] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [codigosRecuperacion, setCodigosRecuperacion] = useState<string[] | null>(null);

  useEffect(() => {
    api
      .mfaConfigurar()
      .then((r) => {
        setQr(r.qr_data_uri);
        setSecreto(r.secreto);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "No se pudo iniciar el enrolamiento."));
  }, []);

  async function confirmar(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setEnviando(true);
    try {
      const r = await api.mfaConfirmar(codigo);
      await refrescar();
      setCodigosRecuperacion(r.codigos_recuperacion);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Código incorrecto.");
      setEnviando(false);
    }
  }

  if (codigosRecuperacion) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Códigos de recuperación</CardTitle>
          <CardDescription>
            Guárdelos en un lugar seguro. Se muestran <strong>una sola vez</strong> y permiten
            entrar si pierde su dispositivo. Cada código sirve una vez.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-2 rounded-md border bg-muted/40 p-4 font-mono text-sm">
            {codigosRecuperacion.map((c) => (
              <span key={c}>{c}</span>
            ))}
          </div>
          <Button
            variant="outline"
            className="w-full"
            onClick={() => {
              navigator.clipboard?.writeText(codigosRecuperacion.join("\n"));
              toast.success("Códigos copiados al portapapeles.");
            }}
          >
            <Copy className="h-4 w-4" /> Copiar códigos
          </Button>
          <Button className="w-full" onClick={() => router.replace("/")}>
            He guardado mis códigos, continuar
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Configurar segundo factor (MFA)</CardTitle>
        <CardDescription>
          Escanee el código QR con su aplicación autenticadora (Aegis, FreeOTP, Google/Microsoft
          Authenticator…) y confirme el código de 6 dígitos.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        {qr && (
          <div className="flex justify-center rounded-md border bg-white p-4">
            {/* QR SVG embebido como data-URI generado por el servidor */}
            <Image src={qr} alt="Código QR de enrolamiento MFA" width={200} height={200} unoptimized />
          </div>
        )}
        {secreto && (
          <Alert>
            <AlertTitle>Entrada manual</AlertTitle>
            <AlertDescription className="font-mono break-all">{secreto}</AlertDescription>
          </Alert>
        )}
        <form onSubmit={confirmar} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="codigo">Código de verificación</Label>
            <Input
              id="codigo"
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="[0-9]*"
              maxLength={6}
              placeholder="000000"
              required
              value={codigo}
              onChange={(e) => setCodigo(e.target.value)}
            />
          </div>
          <Button type="submit" className="w-full" disabled={enviando || !secreto}>
            {enviando && <Loader2 className="h-4 w-4 animate-spin" />}
            Confirmar y activar MFA
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
