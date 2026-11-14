"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, ShieldCheck } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { consumirRetorno } from "@/lib/expiracion";
import { useSession } from "@/lib/session";
import type { MetodosAccesoMfa } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { OtpInput } from "@/components/ui/otp-input";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { CodigoCorreo } from "@/components/mfa/codigo-correo";
import { toast } from "sonner";

type Via = "totp" | "correo" | "recuperacion";

const DESCRIPCION: Record<Via, string> = {
  totp: "Introduzca el código de 6 dígitos de su aplicación de autenticación.",
  correo: "Introduzca el código de 8 dígitos que recibirá en su correo.",
  recuperacion: "Introduzca uno de sus códigos de recuperación.",
};

const ETIQUETA_VIA: Record<Via, string> = {
  totp: "Usar la aplicación autenticadora",
  correo: "Recibir un código por correo",
  recuperacion: "Usar un código de recuperación",
};

export default function MfaVerificarPage() {
  const router = useRouter();
  const { refrescar } = useSession();
  const [metodos, setMetodos] = useState<MetodosAccesoMfa | null>(null);
  const [via, setVia] = useState<Via>("totp");
  const [digitos, setDigitos] = useState(["", "", "", "", "", ""]);
  const [codigoTexto, setCodigoTexto] = useState("");
  const [error, setError] = useState("");
  const [enviando, setEnviando] = useState(false);

  useEffect(() => {
    api
      .mfaMetodos()
      .then((m) => {
        setMetodos(m);
        // Método principal del usuario; si es el correo y no está operativo, se
        // ofrece directamente el código de recuperación.
        setVia(m.principal === "correo" ? (m.otp_correo ? "correo" : "recuperacion") : "totp");
      })
      .catch(() => {
        /* sin lista de métodos se mantiene el flujo clásico (TOTP / recuperación) */
      });
  }, []);

  const alternativas: Via[] = (["totp", "correo", "recuperacion"] as Via[]).filter((v) => {
    if (v === via) return false;
    if (!metodos) return v !== "correo";
    if (v === "totp") return metodos.totp;
    if (v === "correo") return metodos.otp_correo;
    return true;
  });

  function cambiarVia(v: Via) {
    setVia(v);
    setCodigoTexto("");
    setError("");
  }

  async function enviar(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    const codigo = via === "totp" ? digitos.join("") : codigoTexto.replace(/\s/g, "");
    if (via === "totp" && codigo.length < 6) {
      setError("Introduzca los 6 dígitos del código.");
      return;
    }
    if (via === "correo" && codigo.length < 8) {
      setError("Introduzca los 8 dígitos del código.");
      return;
    }
    setEnviando(true);
    try {
      const r = await api.mfaVerificar(codigo);
      await refrescar();
      if (r.aviso) toast.warning(r.aviso, { duration: 10000 });
      // Si la cuenta debe pasar a aplicación autenticadora, el servidor lo indica.
      router.replace(r.stage && r.stage !== "activa" && r.next ? r.next : consumirRetorno());
    } catch (err) {
      if (err instanceof ApiError && err.status === 423) {
        router.replace("/login?motivo=bloqueada");
        return;
      }
      setError(err instanceof ApiError ? err.message : "Código incorrecto.");
      setEnviando(false);
    }
  }

  const correoCaido = metodos?.principal === "correo" && !metodos.otp_correo;

  return (
    <div>
      <div className="mb-4 flex size-11 items-center justify-center rounded-lg bg-muted">
        <ShieldCheck className="size-[22px] text-foreground" />
      </div>
      <h2 className="text-[22px] font-semibold">Verificación en dos pasos</h2>
      <p className="mt-1.5 text-[13.5px] leading-normal text-muted-foreground">{DESCRIPCION[via]}</p>

      <form onSubmit={enviar} className="mt-6 flex flex-col gap-[18px]">
        {correoCaido && (
          <Alert>
            <AlertDescription>
              El envío de códigos por correo no está disponible en este momento. Use un código de
              recuperación o pida al administrador que reinicie su verificación en dos pasos.
            </AlertDescription>
          </Alert>
        )}
        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {via === "totp" && (
          <OtpInput
            valor={digitos}
            onChange={(d) => {
              setDigitos(d);
              setError("");
            }}
          />
        )}
        {via === "correo" && (
          <CodigoCorreo
            key="correo"
            enviar={api.mfaPedirCodigoCorreo}
            valor={codigoTexto}
            onChange={setCodigoTexto}
            destino={metodos?.destino}
            enviarAlMontar={metodos?.principal === "correo"}
            onError={setError}
          />
        )}
        {via === "recuperacion" && (
          <Input
            autoFocus
            autoComplete="one-time-code"
            placeholder="XXXXX-XXXXX"
            className="h-12 text-center font-mono text-base"
            value={codigoTexto}
            onChange={(e) => setCodigoTexto(e.target.value)}
          />
        )}

        <Button type="submit" className="h-10 w-full" disabled={enviando}>
          {enviando && <Loader2 className="animate-spin" />}
          Verificar
        </Button>
        <div className="flex flex-col items-center gap-1.5">
          {alternativas.map((v) => (
            <button
              key={v}
              type="button"
              onClick={() => cambiarVia(v)}
              className="text-center text-[12.5px] text-muted-foreground hover:text-foreground"
            >
              {ETIQUETA_VIA[v]}
            </button>
          ))}
        </div>
      </form>
    </div>
  );
}
