"use client";

import { useEffect, useState } from "react";
import { Loader2, Mail } from "lucide-react";
import { ApiError } from "@/lib/api";
import type { EnvioCodigoCorreo } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const ESPERA_REENVIO_S = 60;

/**
 * Campo del código de 8 dígitos enviado por correo, con el botón de envío y
 * reenvío (con espera, para no inundar el buzón). `enviar` hace la petición.
 */
export function CodigoCorreo({
  enviar,
  valor,
  onChange,
  destino,
  enviarAlMontar = false,
  onError,
}: {
  enviar: () => Promise<EnvioCodigoCorreo>;
  valor: string;
  onChange: (v: string) => void;
  /** Buzón enmascarado conocido de antemano (pista antes del primer envío). */
  destino?: string;
  enviarAlMontar?: boolean;
  onError: (mensaje: string) => void;
}) {
  const [envio, setEnvio] = useState<EnvioCodigoCorreo | null>(null);
  const [enviando, setEnviando] = useState(false);
  const [espera, setEspera] = useState(0);

  async function pedir() {
    setEnviando(true);
    onError("");
    try {
      setEnvio(await enviar());
      setEspera(ESPERA_REENVIO_S);
    } catch (err) {
      onError(err instanceof ApiError ? err.message : "No se pudo enviar el código.");
    } finally {
      setEnviando(false);
    }
  }

  useEffect(() => {
    if (enviarAlMontar) void pedir();
    // Solo al montar: el envío inicial no debe repetirse en cada render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (espera <= 0) return;
    const id = window.setTimeout(() => setEspera((s) => s - 1), 1000);
    return () => window.clearTimeout(id);
  }, [espera]);

  return (
    <div className="flex flex-col gap-3">
      <p className="flex items-start gap-2 rounded-lg border bg-muted/40 px-3.5 py-3 text-[13px] leading-normal text-muted-foreground">
        <Mail className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
        <span>
          {envio ? (
            <>
              Enviamos un código a <span className="font-mono text-foreground">{envio.destino}</span>.
              Caduca en {envio.vigencia_minutos} minutos y sirve una sola vez.
            </>
          ) : (
            <>
              Le enviaremos un código de 8 dígitos a{" "}
              <span className="font-mono text-foreground">{destino || "su correo registrado"}</span>.
            </>
          )}
        </span>
      </p>
      {envio && (
        <Input
          autoFocus
          inputMode="numeric"
          autoComplete="one-time-code"
          aria-label="Código recibido por correo"
          placeholder="00000000"
          maxLength={9}
          className="h-12 text-center font-mono text-lg tracking-[0.3em]"
          value={valor}
          onChange={(e) => onChange(e.target.value.replace(/[^\d ]/g, ""))}
        />
      )}
      <Button
        type="button"
        variant={envio ? "ghost" : "outline"}
        className={envio ? "h-8 text-[12.5px] text-muted-foreground" : "h-10"}
        disabled={enviando || espera > 0}
        onClick={() => void pedir()}
      >
        {enviando && <Loader2 className="animate-spin" />}
        {!envio ? "Enviar código a mi correo" : espera > 0 ? `Reenviar código (${espera} s)` : "Reenviar código"}
      </Button>
    </div>
  );
}
