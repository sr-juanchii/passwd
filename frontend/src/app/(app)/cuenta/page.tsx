"use client";

import { useCallback, useEffect, useState } from "react";
import { KeyRound, LifeBuoy, Loader2, Mail, ShieldCheck, Smartphone } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import type { SeguridadCuenta } from "@/lib/types";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PageSkeleton } from "@/components/ui/page-skeleton";
import { SectionHeader } from "@/components/ui/section-header";
import { CodigoCorreo } from "@/components/mfa/codigo-correo";
import { CodigosRecuperacion } from "@/components/mfa/codigos-recuperacion";
import { QrTotp } from "@/components/mfa/qr-totp";

type Panel = null | "a-correo" | "a-totp" | "codigos";

function mensaje(err: unknown, porDefecto: string): string {
  return err instanceof ApiError ? err.message : porDefecto;
}

function CampoPassword({ valor, onChange }: { valor: string; onChange: (v: string) => void }) {
  return (
    <div className="flex flex-col gap-2">
      <Label htmlFor="seg-password">Contraseña actual</Label>
      <Input
        id="seg-password"
        type="password"
        autoComplete="current-password"
        required
        value={valor}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

export default function MiSeguridadPage() {
  const [estado, setEstado] = useState<SeguridadCuenta | null>(null);
  const [panel, setPanel] = useState<Panel>(null);
  const [password, setPassword] = useState("");
  const [codigo, setCodigo] = useState("");
  const [error, setError] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [totp, setTotp] = useState<{ qr_data_uri: string; secreto: string } | null>(null);
  const [codigosNuevos, setCodigosNuevos] = useState<string[] | null>(null);

  const cargar = useCallback(() => {
    api
      .seguridad()
      .then(setEstado)
      .catch((err) => toast.error(mensaje(err, "No se pudo cargar su configuración de seguridad.")));
  }, []);

  useEffect(() => {
    cargar();
  }, [cargar]);

  function abrir(p: Panel) {
    setPanel(p);
    setPassword("");
    setCodigo("");
    setError("");
    setTotp(null);
    setCodigosNuevos(null);
  }

  async function ejecutar(accion: () => Promise<void>, porDefecto: string) {
    setError("");
    setEnviando(true);
    try {
      await accion();
    } catch (err) {
      setError(mensaje(err, porDefecto));
    } finally {
      setEnviando(false);
    }
  }

  if (!estado) return <PageSkeleton />;

  const esTotp = estado.metodo === "totp";
  const codigoLimpio = codigo.replace(/\s/g, "");

  return (
    <>
      <PageHeader
        titulo="Mi seguridad"
        descripcion="Gestione cómo confirma su identidad al iniciar sesión. Cualquier cambio exige su contraseña y queda registrado en la auditoría."
      />

      <div className="flex flex-col gap-4">
        {/* --- Método de verificación --- */}
        <section className="overflow-hidden rounded-xl border bg-card">
          <div className="border-b px-5 py-3.5">
            <SectionHeader icono={ShieldCheck} titulo="Verificación en dos pasos" />
          </div>
          <div className="flex flex-col gap-4 p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <span className="flex size-10 items-center justify-center rounded-md bg-muted">
                  {esTotp ? <Smartphone className="size-5" /> : <Mail className="size-5" />}
                </span>
                <div>
                  <div className="flex items-center gap-2 text-sm font-semibold">
                    {esTotp ? "Aplicación autenticadora" : "Código por correo"}
                    <Badge variant="secondary">Método actual</Badge>
                  </div>
                  <p className="text-[12.5px] text-muted-foreground">
                    {esTotp
                      ? "Código de 6 dígitos generado en su teléfono."
                      : `Código de un solo uso enviado a ${estado.destino}.`}
                  </p>
                </div>
              </div>
              {panel === null &&
                (esTotp ? (
                  <Button variant="outline" disabled={!estado.puede_cambiar_a_correo} onClick={() => abrir("a-correo")}>
                    <Mail /> Cambiar a código por correo
                  </Button>
                ) : (
                  <Button variant="outline" onClick={() => abrir("a-totp")}>
                    <Smartphone /> Cambiar a aplicación autenticadora
                  </Button>
                ))}
            </div>

            {esTotp && !estado.puede_cambiar_a_correo && estado.motivo_correo && panel === null && (
              <p className="text-[12.5px] text-muted-foreground">
                El código por correo no está disponible: {estado.motivo_correo}
              </p>
            )}
            {!esTotp && !estado.correo_operativo && (
              <Alert>
                <AlertDescription>
                  El servicio de correo no está disponible ahora mismo. Hasta que se restablezca solo
                  podrá entrar con un código de recuperación: consérvelos a mano.
                </AlertDescription>
              </Alert>
            )}

            {panel === "a-correo" && (
              <form
                className="flex max-w-md flex-col gap-4 border-t pt-4"
                onSubmit={(e) => {
                  e.preventDefault();
                  void ejecutar(async () => {
                    setEstado(await api.seguridadActivarCorreo(password, codigoLimpio));
                    abrir(null);
                    toast.success("El código por correo es ahora su método de verificación.");
                  }, "No se pudo cambiar el método.");
                }}
              >
                <p className="text-[13px] leading-normal text-muted-foreground">
                  El código por correo es menos seguro que la aplicación autenticadora: quien acceda a
                  su buzón y conozca su contraseña podría entrar. Su aplicación dejará de servir para
                  esta cuenta.
                </p>
                {error && (
                  <Alert variant="destructive">
                    <AlertDescription>{error}</AlertDescription>
                  </Alert>
                )}
                <CampoPassword valor={password} onChange={setPassword} />
                <CodigoCorreo
                  enviar={api.seguridadEnviarCodigo}
                  valor={codigo}
                  onChange={setCodigo}
                  destino={estado.destino}
                  onError={setError}
                />
                <div className="flex gap-2">
                  <Button type="submit" disabled={enviando || !password || codigoLimpio.length < 8}>
                    {enviando && <Loader2 className="animate-spin" />}
                    Activar código por correo
                  </Button>
                  <Button type="button" variant="ghost" onClick={() => abrir(null)}>
                    Cancelar
                  </Button>
                </div>
              </form>
            )}

            {panel === "a-totp" && (
              <form
                className="flex max-w-md flex-col gap-4 border-t pt-4"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (!totp) {
                    void ejecutar(async () => {
                      setTotp(await api.seguridadIniciarTotp(password));
                    }, "No se pudo iniciar el cambio.");
                    return;
                  }
                  void ejecutar(async () => {
                    setEstado(await api.seguridadActivarTotp(codigoLimpio));
                    abrir(null);
                    toast.success("La aplicación autenticadora es ahora su método de verificación.");
                  }, "Código incorrecto.");
                }}
              >
                {error && (
                  <Alert variant="destructive">
                    <AlertDescription>{error}</AlertDescription>
                  </Alert>
                )}
                {!totp ? (
                  <CampoPassword valor={password} onChange={setPassword} />
                ) : (
                  <>
                    <p className="text-[13px] leading-normal text-muted-foreground">
                      Escanee el código QR con su aplicación de autenticación y confirme el código de 6
                      dígitos. Hasta que lo confirme, su método sigue siendo el correo.
                    </p>
                    <QrTotp qr={totp.qr_data_uri} secreto={totp.secreto} />
                    <div className="flex flex-col gap-2">
                      <Label htmlFor="seg-totp">Código de la aplicación</Label>
                      <Input
                        id="seg-totp"
                        inputMode="numeric"
                        autoComplete="one-time-code"
                        maxLength={7}
                        className="h-11 text-center font-mono text-lg tracking-[0.3em]"
                        value={codigo}
                        onChange={(e) => setCodigo(e.target.value.replace(/[^\d ]/g, ""))}
                      />
                    </div>
                  </>
                )}
                <div className="flex gap-2">
                  <Button type="submit" disabled={enviando || (!totp ? !password : codigoLimpio.length < 6)}>
                    {enviando && <Loader2 className="animate-spin" />}
                    {totp ? "Confirmar y activar" : "Continuar"}
                  </Button>
                  <Button type="button" variant="ghost" onClick={() => abrir(null)}>
                    Cancelar
                  </Button>
                </div>
              </form>
            )}
          </div>
        </section>

        {/* --- Códigos de recuperación --- */}
        <section className="overflow-hidden rounded-xl border bg-card">
          <div className="border-b px-5 py-3.5">
            <SectionHeader icono={LifeBuoy} titulo="Códigos de recuperación" />
          </div>
          <div className="flex flex-col gap-4 p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-sm">
                Le quedan{" "}
                <strong className={estado.codigos_restantes <= 2 ? "text-destructive" : undefined}>
                  {estado.codigos_restantes}
                </strong>{" "}
                códigos sin usar. Sirven para entrar si no puede usar su método habitual.
              </p>
              {panel === null && (
                <Button variant="outline" onClick={() => abrir("codigos")}>
                  <KeyRound /> Generar códigos nuevos
                </Button>
              )}
            </div>

            {panel === "codigos" && codigosNuevos && (
              <div className="max-w-md border-t pt-4">
                <CodigosRecuperacion
                  codigos={codigosNuevos}
                  textoContinuar="He guardado mis códigos"
                  onContinuar={() => abrir(null)}
                />
              </div>
            )}

            {panel === "codigos" && !codigosNuevos && (
              <form
                className="flex max-w-md flex-col gap-4 border-t pt-4"
                onSubmit={(e) => {
                  e.preventDefault();
                  void ejecutar(async () => {
                    const r = await api.seguridadRegenerarCodigos(password, codigoLimpio);
                    setCodigosNuevos(r.codigos_recuperacion);
                    cargar();
                  }, "No se pudieron generar los códigos.");
                }}
              >
                <p className="text-[13px] leading-normal text-muted-foreground">
                  Al generar códigos nuevos, los anteriores dejan de valer.
                </p>
                {error && (
                  <Alert variant="destructive">
                    <AlertDescription>{error}</AlertDescription>
                  </Alert>
                )}
                <CampoPassword valor={password} onChange={setPassword} />
                {esTotp ? (
                  <div className="flex flex-col gap-2">
                    <Label htmlFor="seg-codigo">Código de su aplicación autenticadora</Label>
                    <Input
                      id="seg-codigo"
                      inputMode="numeric"
                      autoComplete="one-time-code"
                      maxLength={7}
                      className="h-11 text-center font-mono text-lg tracking-[0.3em]"
                      value={codigo}
                      onChange={(e) => setCodigo(e.target.value.replace(/[^\d ]/g, ""))}
                    />
                  </div>
                ) : (
                  <CodigoCorreo
                    enviar={api.seguridadEnviarCodigo}
                    valor={codigo}
                    onChange={setCodigo}
                    destino={estado.destino}
                    onError={setError}
                  />
                )}
                <div className="flex gap-2">
                  <Button type="submit" disabled={enviando || !password || codigoLimpio.length < (esTotp ? 6 : 8)}>
                    {enviando && <Loader2 className="animate-spin" />}
                    Generar códigos
                  </Button>
                  <Button type="button" variant="ghost" onClick={() => abrir(null)}>
                    Cancelar
                  </Button>
                </div>
              </form>
            )}
          </div>
        </section>
      </div>
    </>
  );
}
