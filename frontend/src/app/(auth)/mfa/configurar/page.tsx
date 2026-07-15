"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Image from "next/image";
import { Copy, Loader2, ShieldCheck } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useSession } from "@/lib/session";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { OtpInput } from "@/components/ui/otp-input";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { toast } from "sonner";

export default function MfaConfigurarPage() {
  const router = useRouter();
  const { refrescar } = useSession();
  const [qr, setQr] = useState("");
  const [secreto, setSecreto] = useState("");
  const [digitos, setDigitos] = useState(["", "", "", "", "", ""]);
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
      .catch((err) =>
        setError(err instanceof ApiError ? err.message : "No se pudo iniciar el enrolamiento."),
      );
  }, []);

  async function confirmar(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    const codigo = digitos.join("");
    if (codigo.length < 6) {
      setError("Introduzca los 6 dígitos del código.");
      return;
    }
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
      <div>
        <div className="mb-4 flex size-11 items-center justify-center rounded-lg bg-muted">
          <ShieldCheck className="size-[22px] text-foreground" />
        </div>
        <h2 className="text-[22px] font-semibold">Códigos de recuperación</h2>
        <p className="mt-1.5 text-[13.5px] leading-normal text-muted-foreground">
          Guárdelos en un lugar seguro. Se muestran <strong>una sola vez</strong> y permiten entrar
          si pierde su dispositivo. Cada código sirve una vez.
        </p>
        <div className="mt-5 grid grid-cols-2 gap-2 rounded-lg border bg-muted/40 p-4 font-mono text-sm">
          {codigosRecuperacion.map((c) => (
            <span key={c}>{c}</span>
          ))}
        </div>
        <Button
          variant="outline"
          className="mt-4 w-full"
          onClick={() => {
            navigator.clipboard?.writeText(codigosRecuperacion.join("\n"));
            toast.success("Códigos copiados al portapapeles.");
          }}
        >
          <Copy /> Copiar códigos
        </Button>
        <Button className="mt-2 h-10 w-full" onClick={() => router.replace("/")}>
          He guardado mis códigos, continuar
        </Button>
      </div>
    );
  }

  return (
    <div>
      <div className="mb-4 flex size-11 items-center justify-center rounded-lg bg-muted">
        <ShieldCheck className="size-[22px] text-foreground" />
      </div>
      <h2 className="text-[22px] font-semibold">Configurar segundo factor</h2>
      <p className="mt-1.5 text-[13.5px] leading-normal text-muted-foreground">
        Escanee el código QR con su aplicación de autenticación (Aegis, FreeOTP, Google/Microsoft
        Authenticator…) y confirme el código de 6 dígitos.
      </p>

      <div className="mt-6 flex flex-col gap-4">
        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        {qr && (
          <div className="my-1 flex justify-center">
            {/* El QR va SIEMPRE sobre blanco, también en oscuro (DESIGN.md §7). */}
            <div className="rounded-xl bg-white p-3 ring-1 ring-foreground/10">
              <Image
                src={qr}
                alt="Código QR de enrolamiento MFA"
                width={200}
                height={200}
                unoptimized
              />
            </div>
          </div>
        )}
        {secreto && (
          <div className="rounded-lg border bg-muted/40 px-3.5 py-3">
            <div className="text-[11px] font-medium tracking-[0.06em] text-muted-foreground uppercase">
              Entrada manual
            </div>
            <div className="mt-1 font-mono text-[13px] break-all">{secreto}</div>
          </div>
        )}
        <form onSubmit={confirmar} className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label>Código de verificación</Label>
            <OtpInput
              valor={digitos}
              onChange={setDigitos}
              autoFocus={false}
            />
          </div>
          <Button type="submit" className="h-10 w-full" disabled={enviando || !secreto}>
            {enviando && <Loader2 className="animate-spin" />}
            Confirmar y activar MFA
          </Button>
        </form>
      </div>
    </div>
  );
}
