"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, ShieldCheck } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useSession } from "@/lib/session";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { toast } from "sonner";

export default function MfaVerificarPage() {
  const router = useRouter();
  const { refrescar } = useSession();
  const [digitos, setDigitos] = useState(["", "", "", "", "", ""]);
  const [recuperacion, setRecuperacion] = useState(false);
  const [codigoRec, setCodigoRec] = useState("");
  const [error, setError] = useState("");
  const [enviando, setEnviando] = useState(false);
  const refs = useRef<(HTMLInputElement | null)[]>([]);

  function setDig(i: number, v: string) {
    const limpio = v.replace(/\D/g, "").slice(-1);
    const next = [...digitos];
    next[i] = limpio;
    setDigitos(next);
    setError("");
    if (limpio && i < 5) refs.current[i + 1]?.focus();
  }

  function onKey(i: number, e: React.KeyboardEvent) {
    if (e.key === "Backspace" && !digitos[i] && i > 0) refs.current[i - 1]?.focus();
  }

  function onPaste(e: React.ClipboardEvent) {
    const txt = (e.clipboardData.getData("text") || "").replace(/\D/g, "").slice(0, 6);
    if (!txt) return;
    e.preventDefault();
    const next = txt.split("");
    while (next.length < 6) next.push("");
    setDigitos(next);
    refs.current[Math.min(txt.length, 5)]?.focus();
  }

  async function enviar(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    const codigo = recuperacion ? codigoRec.trim() : digitos.join("");
    if (!recuperacion && codigo.length < 6) {
      setError("Introduzca los 6 dígitos del código.");
      return;
    }
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
    <div>
      <div className="mb-4 flex size-11 items-center justify-center rounded-[11px] bg-muted">
        <ShieldCheck className="size-[22px] text-foreground" />
      </div>
      <h2 className="text-[22px] font-semibold">Verificación en dos pasos</h2>
      <p className="mt-1.5 text-[13.5px] leading-normal text-muted-foreground">
        {recuperacion
          ? "Introduzca uno de sus códigos de recuperación."
          : "Introduzca el código de 6 dígitos de su aplicación de autenticación."}
      </p>

      <form onSubmit={enviar} className="mt-6 flex flex-col gap-[18px]">
        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {recuperacion ? (
          <Input
            autoFocus
            autoComplete="one-time-code"
            placeholder="XXXXX-XXXXX"
            className="h-12 text-center font-mono text-base"
            value={codigoRec}
            onChange={(e) => setCodigoRec(e.target.value)}
          />
        ) : (
          <div className="flex gap-2.5" onPaste={onPaste}>
            {digitos.map((v, i) => (
              <input
                key={i}
                ref={(el) => {
                  refs.current[i] = el;
                }}
                value={v}
                inputMode="numeric"
                maxLength={1}
                autoFocus={i === 0}
                aria-label={`Dígito ${i + 1}`}
                onChange={(e) => setDig(i, e.target.value)}
                onKeyDown={(e) => onKey(i, e)}
                className="h-[52px] w-full rounded-[10px] border bg-card text-center font-mono text-[22px] font-semibold text-foreground outline-none transition-colors focus:border-foreground aria-[invalid]:border-destructive data-[filled=true]:border-foreground"
                data-filled={v ? "true" : "false"}
              />
            ))}
          </div>
        )}

        <Button type="submit" className="h-10 w-full" disabled={enviando}>
          {enviando && <Loader2 className="animate-spin" />}
          Verificar
        </Button>
        <button
          type="button"
          onClick={() => {
            setRecuperacion((v) => !v);
            setError("");
          }}
          className="text-center text-[12.5px] text-muted-foreground hover:text-foreground"
        >
          {recuperacion ? "Usar el código de la aplicación" : "Usar un código de recuperación"}
        </button>
      </form>
    </div>
  );
}
