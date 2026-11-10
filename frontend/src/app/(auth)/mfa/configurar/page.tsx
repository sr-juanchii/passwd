"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, Loader2, Mail, ShieldCheck, Smartphone } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { consumirRetorno } from "@/lib/expiracion";
import { useSession } from "@/lib/session";
import type { MetodoMfa, MetodosAltaMfa } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { OtpInput } from "@/components/ui/otp-input";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { CodigoCorreo } from "@/components/mfa/codigo-correo";
import { CodigosRecuperacion } from "@/components/mfa/codigos-recuperacion";
import { QrTotp } from "@/components/mfa/qr-totp";

function Cabecera({ titulo, children }: { titulo: string; children: React.ReactNode }) {
  return (
    <>
      <div className="mb-4 flex size-11 items-center justify-center rounded-lg bg-muted">
        <ShieldCheck className="size-[22px] text-foreground" />
      </div>
      <h2 className="text-[22px] font-semibold">{titulo}</h2>
      <p className="mt-1.5 text-[13.5px] leading-normal text-muted-foreground">{children}</p>
    </>
  );
}

function OpcionMetodo({
  icono,
  titulo,
  descripcion,
  nota,
  deshabilitada,
  onClick,
}: {
  icono: React.ReactNode;
  titulo: string;
  descripcion: string;
  nota?: string;
  deshabilitada?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      disabled={deshabilitada}
      onClick={onClick}
      className="flex w-full items-start gap-3 rounded-lg border bg-card px-4 py-3.5 text-left transition-[background-color,box-shadow] outline-none hover:bg-muted focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:bg-card"
    >
      <span className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-md bg-muted">{icono}</span>
      <span className="flex flex-col gap-0.5">
        <span className="text-sm font-semibold">{titulo}</span>
        <span className="text-[12.5px] leading-normal text-muted-foreground">{descripcion}</span>
        {nota && <span className="text-[12px] leading-normal text-amber-600 dark:text-amber-500">{nota}</span>}
      </span>
    </button>
  );
}

export default function MfaConfigurarPage() {
  const router = useRouter();
  const { refrescar } = useSession();
  const [opciones, setOpciones] = useState<MetodosAltaMfa | null>(null);
  const [metodo, setMetodo] = useState<MetodoMfa | null>(null);
  const [qr, setQr] = useState("");
  const [secreto, setSecreto] = useState("");
  const [digitos, setDigitos] = useState(["", "", "", "", "", ""]);
  const [codigoCorreo, setCodigoCorreo] = useState("");
  const [error, setError] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [codigosRecuperacion, setCodigosRecuperacion] = useState<string[] | null>(null);

  useEffect(() => {
    api
      .mfaMetodosAlta()
      .then((r) => {
        setOpciones(r);
        // Sin alternativa real se va directo a la aplicación autenticadora.
        if (!r.correo.disponible && !r.correo.motivo) setMetodo("totp");
      })
      .catch((err) =>
        setError(err instanceof ApiError ? err.message : "No se pudo iniciar la configuración."),
      );
  }, []);

  useEffect(() => {
    if (metodo !== "totp" || secreto) return;
    api
      .mfaConfigurar()
      .then((r) => {
        setQr(r.qr_data_uri);
        setSecreto(r.secreto);
      })
      .catch((err) =>
        setError(err instanceof ApiError ? err.message : "No se pudo iniciar el enrolamiento."),
      );
  }, [metodo, secreto]);

  function alFallar(err: unknown, porDefecto: string) {
    if (err instanceof ApiError && err.status === 423) {
      router.replace("/login?motivo=bloqueada");
      return;
    }
    setError(err instanceof ApiError ? err.message : porDefecto);
    setEnviando(false);
  }

  async function confirmar(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    const codigo = metodo === "correo" ? codigoCorreo.replace(/\s/g, "") : digitos.join("");
    const largo = metodo === "correo" ? 8 : 6;
    if (codigo.length < largo) {
      setError(`Introduzca los ${largo} dígitos del código.`);
      return;
    }
    setEnviando(true);
    try {
      const r = metodo === "correo" ? await api.mfaAltaCorreoConfirmar(codigo) : await api.mfaConfirmar(codigo);
      await refrescar();
      setCodigosRecuperacion(r.codigos_recuperacion);
    } catch (err) {
      alFallar(err, "Código incorrecto.");
    }
  }

  if (codigosRecuperacion) {
    return (
      <div>
        <Cabecera titulo="Códigos de recuperación">Verificación en dos pasos activada.</Cabecera>
        <div className="mt-4">
          <CodigosRecuperacion
            codigos={codigosRecuperacion}
            textoContinuar="He guardado mis códigos, continuar"
            onContinuar={() => router.replace(consumirRetorno())}
          />
        </div>
      </div>
    );
  }

  // Paso 1: elegir método.
  if (!metodo) {
    return (
      <div>
        <Cabecera titulo="Verificación en dos pasos">
          {opciones?.obligado_totp
            ? "Su cuenta debe usar ahora una aplicación autenticadora. Configúrela para continuar."
            : "Elija cómo quiere confirmar su identidad cada vez que inicie sesión."}
        </Cabecera>
        <div className="mt-6 flex flex-col gap-3">
          {error && (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          {!opciones && !error && (
            <Loader2 className="mx-auto size-5 animate-spin text-muted-foreground" aria-label="Cargando" />
          )}
          {opciones && (
            <>
              <OpcionMetodo
                icono={<Smartphone className="size-[18px]" />}
                titulo="Aplicación autenticadora"
                descripcion="Código de 6 dígitos generado en su teléfono (Google o Microsoft Authenticator, Aegis…). Es la opción más segura y funciona sin conexión."
                onClick={() => {
                  setError("");
                  setMetodo("totp");
                }}
              />
              <OpcionMetodo
                icono={<Mail className="size-[18px]" />}
                titulo="Código por correo"
                descripcion={
                  opciones.correo.disponible
                    ? `Recibirá un código de un solo uso en ${opciones.correo.destino} cada vez que inicie sesión.`
                    : "Recibirá un código de un solo uso en su correo cada vez que inicie sesión."
                }
                nota={opciones.correo.disponible ? undefined : opciones.correo.motivo}
                deshabilitada={!opciones.correo.disponible}
                onClick={() => {
                  setError("");
                  setMetodo("correo");
                }}
              />
            </>
          )}
        </div>
      </div>
    );
  }

  const puedeVolver = Boolean(opciones && (opciones.correo.disponible || opciones.correo.motivo));

  return (
    <div>
      <Cabecera titulo={metodo === "totp" ? "Aplicación autenticadora" : "Código por correo"}>
        {metodo === "totp"
          ? "Escanee el código QR con su aplicación de autenticación y confirme el código de 6 dígitos."
          : "Confirme que tiene acceso a su correo introduciendo el código que le enviamos."}
      </Cabecera>

      <form onSubmit={confirmar} className="mt-6 flex flex-col gap-4">
        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        {metodo === "totp" ? (
          <>
            <QrTotp qr={qr} secreto={secreto} />
            <div className="flex flex-col gap-2">
              <Label>Código de verificación</Label>
              <OtpInput valor={digitos} onChange={setDigitos} autoFocus={false} />
            </div>
          </>
        ) : (
          <CodigoCorreo
            enviar={api.mfaAltaCorreoEnviar}
            valor={codigoCorreo}
            onChange={setCodigoCorreo}
            destino={opciones?.correo.destino}
            onError={setError}
          />
        )}
        <Button
          type="submit"
          className="h-10 w-full"
          disabled={enviando || (metodo === "totp" ? !secreto : codigoCorreo.replace(/\s/g, "").length < 8)}
        >
          {enviando && <Loader2 className="animate-spin" />}
          Confirmar y activar
        </Button>
        {puedeVolver && (
          <button
            type="button"
            onClick={() => {
              setMetodo(null);
              setError("");
            }}
            className="flex items-center justify-center gap-1.5 text-[12.5px] text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="size-3.5" /> Elegir otro método
          </button>
        )}
      </form>
    </div>
  );
}
