"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { KeyRound, Loader2, Lock, ShieldCheck } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { OtpInput } from "@/components/ui/otp-input";
import { CampoPassword } from "@/components/forms/campo-password";

type Paso = "identidad" | "verificar" | "cambiar";

export default function RecuperarPage() {
  const router = useRouter();
  const [paso, setPaso] = useState<Paso>("identidad");
  const [error, setError] = useState("");
  const [enviando, setEnviando] = useState(false);

  // Paso 1 — identidad
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [csrfLogin, setCsrfLogin] = useState("");
  // CSRF del desafío emitido en el paso 1, reutilizado en verificar/cambiar.
  const [csrfDesafio, setCsrfDesafio] = useState("");

  // Paso 2 — verificación
  const [digitos, setDigitos] = useState<string[]>(["", "", "", "", "", ""]);
  const [modoRecuperacion, setModoRecuperacion] = useState(false);
  const [codigoRec, setCodigoRec] = useState("");

  // Paso 3 — nueva contraseña
  const [password, setPassword] = useState("");
  const [confirmacion, setConfirmacion] = useState("");

  useEffect(() => {
    api
      .csrfLogin()
      .then((r) => setCsrfLogin(r.csrf_login))
      .catch(() => setError("No se pudo contactar al servidor."));
  }, []);

  async function enviarIdentidad(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setEnviando(true);
    try {
      // Respuesta anti-enumeración: siempre avanza; el paso 2 fallará si la
      // identidad no correspondía a una cuenta con MFA activo.
      const r = await api.recuperarIniciar(username, email, csrfLogin);
      setCsrfDesafio(r.csrf);
      setPaso("verificar");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo iniciar la recuperación.");
      api.csrfLogin().then((c) => setCsrfLogin(c.csrf_login)).catch(() => {});
    } finally {
      setEnviando(false);
    }
  }

  async function enviarVerificacion(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    const codigo = modoRecuperacion ? codigoRec.trim() : digitos.join("");
    if (!modoRecuperacion && codigo.length < 6) {
      setError("Introduzca los 6 dígitos del código.");
      return;
    }
    setEnviando(true);
    try {
      await api.recuperarVerificar(codigo, csrfDesafio);
      setPaso("cambiar");
    } catch (err) {
      const e2 = err instanceof ApiError ? err : null;
      // 400 = desafío inválido/caducado/agotado → reiniciar el flujo.
      if (e2?.status === 400) {
        setError("La solicitud caducó o se agotaron los intentos. Empiece de nuevo.");
        setPaso("identidad");
        setDigitos(["", "", "", "", "", ""]);
        setCodigoRec("");
      } else {
        setError(e2 ? e2.message : "Código incorrecto.");
      }
    } finally {
      setEnviando(false);
    }
  }

  async function enviarCambio(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (password !== confirmacion) {
      setError("La confirmación no coincide.");
      return;
    }
    setEnviando(true);
    try {
      await api.recuperarCambiar(password, confirmacion, csrfDesafio);
      router.replace("/login?msg=" + encodeURIComponent("Contraseña restablecida. Inicie sesión."));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo cambiar la contraseña.");
      setEnviando(false);
    }
  }

  return (
    <div>
      <div className="mb-4 flex size-11 items-center justify-center rounded-lg bg-muted">
        {paso === "cambiar" ? (
          <KeyRound className="size-[22px] text-foreground" />
        ) : paso === "verificar" ? (
          <ShieldCheck className="size-[22px] text-foreground" />
        ) : (
          <Lock className="size-[22px] text-foreground" />
        )}
      </div>

      {error && (
        <Alert variant="destructive" className="mb-4">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {paso === "identidad" && (
        <>
          <h2 className="text-[22px] font-semibold">Recuperar contraseña</h2>
          <p className="mt-1.5 text-[13.5px] leading-normal text-muted-foreground">
            Identifique su cuenta. Después verificará su identidad con su segundo factor.
          </p>
          <form onSubmit={enviarIdentidad} className="mt-6 flex flex-col gap-4">
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
              <Label htmlFor="email">Email registrado</Label>
              <Input
                id="email"
                type="email"
                autoComplete="email"
                required
                className="font-mono"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            <Button type="submit" className="h-10 w-full" disabled={enviando || !csrfLogin}>
              {enviando && <Loader2 className="animate-spin" />}
              Continuar
            </Button>
          </form>
        </>
      )}

      {paso === "verificar" && (
        <>
          <h2 className="text-[22px] font-semibold">Verifique su identidad</h2>
          <p className="mt-1.5 text-[13.5px] leading-normal text-muted-foreground">
            {modoRecuperacion
              ? "Introduzca uno de sus códigos de recuperación."
              : "Introduzca el código de 6 dígitos de su aplicación autenticadora."}
          </p>
          <form onSubmit={enviarVerificacion} className="mt-6 flex flex-col gap-[18px]">
            {modoRecuperacion ? (
              <Input
                autoFocus
                autoComplete="one-time-code"
                placeholder="XXXXX-XXXXX"
                className="h-12 text-center font-mono text-base"
                value={codigoRec}
                onChange={(e) => setCodigoRec(e.target.value)}
              />
            ) : (
              <OtpInput valor={digitos} onChange={(d) => { setDigitos(d); setError(""); }} />
            )}
            <Button type="submit" className="h-10 w-full" disabled={enviando}>
              {enviando && <Loader2 className="animate-spin" />}
              Verificar
            </Button>
            <button
              type="button"
              onClick={() => { setModoRecuperacion((v) => !v); setError(""); }}
              className="text-center text-[12.5px] text-muted-foreground hover:text-foreground"
            >
              {modoRecuperacion ? "Usar el código de la aplicación" : "Usar un código de recuperación"}
            </button>
          </form>
        </>
      )}

      {paso === "cambiar" && (
        <>
          <h2 className="text-[22px] font-semibold">Nueva contraseña</h2>
          <p className="mt-1.5 text-[13.5px] leading-normal text-muted-foreground">
            Al guardar se cerrarán todas sus sesiones y deberá iniciar sesión de nuevo.
          </p>
          <form onSubmit={enviarCambio} className="mt-6 flex flex-col gap-4">
            <CampoPassword
              id="password-nueva"
              value={password}
              onChange={setPassword}
              autoComplete="new-password"
            />
            <div className="flex flex-col gap-2">
              <Label htmlFor="confirmacion">Confirmar contraseña</Label>
              <Input
                id="confirmacion"
                type="password"
                autoComplete="new-password"
                required
                className="font-mono"
                value={confirmacion}
                onChange={(e) => setConfirmacion(e.target.value)}
              />
            </div>
            <Button type="submit" className="h-10 w-full" disabled={enviando}>
              {enviando && <Loader2 className="animate-spin" />}
              Guardar y volver a iniciar sesión
            </Button>
          </form>
        </>
      )}

      <p className="mt-6 text-center">
        <Link href="/login" className="text-[12.5px] text-muted-foreground hover:text-foreground">
          Volver a iniciar sesión
        </Link>
      </p>
    </div>
  );
}
