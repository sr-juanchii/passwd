"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  CheckCircle2,
  Clock,
  Info,
  Loader2,
  Lock,
  Mail,
  RotateCcw,
  Save,
  Send,
  ServerCog,
  ShieldCheck,
  SlidersHorizontal,
  TriangleAlert,
} from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { AjusteConfig, ConfiguracionResp, OrigenAjuste } from "@/lib/types";
import { useSession } from "@/lib/session";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Mono } from "@/components/ui/mono";
import { PageSkeleton } from "@/components/ui/page-skeleton";
import { SectionHeader } from "@/components/ui/section-header";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

// Valor editable de cada control: los enteros se guardan como texto (permiten un
// campo vacío durante la edición) y se convierten a número al enviar.
type Valor = string | boolean;

const ICONO_GRUPO: Record<string, React.ComponentType<{ className?: string }>> = {
  "Sesión y comportamiento": Clock,
  "Política de cuentas": ShieldCheck,
  "Límites de tasa (anti-abuso)": Activity,
  "Inventario y auditoría": ServerCog,
  "Notificaciones por correo": Mail,
};

function estadoInicial(resp: ConfiguracionResp): Record<string, Valor> {
  const m: Record<string, Valor> = {};
  for (const g of resp.grupos) {
    for (const a of g.ajustes) {
      if (a.tipo === "booleano") m[a.clave] = Boolean(a.valor);
      else if (a.tipo === "secreto") m[a.clave] = ""; // vacío = conservar
      else m[a.clave] = a.valor === undefined || a.valor === null ? "" : String(a.valor);
    }
  }
  return m;
}

function OrigenBadge({ origen }: { origen: OrigenAjuste }) {
  if (origen === "configurado") return <Badge variant="secondary">configurado aquí</Badge>;
  if (origen === "entorno") return <Badge variant="outline">por entorno</Badge>;
  return (
    <Badge variant="outline" className="text-muted-foreground">
      por defecto
    </Badge>
  );
}

export default function ConfiguracionPage() {
  const { puede, usuario } = useSession();
  const [resp, setResp] = useState<ConfiguracionResp | null>(null);
  const [valores, setValores] = useState<Record<string, Valor>>({});
  const [cargando, setCargando] = useState(true);
  const [guardando, setGuardando] = useState(false);
  const [destinatario, setDestinatario] = useState("");
  const [probando, setProbando] = useState(false);
  const [resultadoCorreo, setResultadoCorreo] = useState<{ ok: boolean; mensaje: string } | null>(
    null,
  );

  const cargar = useCallback(async () => {
    setCargando(true);
    try {
      const r = await api.configuracion();
      setResp(r);
      setValores(estadoInicial(r));
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "No se pudo cargar la configuración.");
    } finally {
      setCargando(false);
    }
  }, []);

  useEffect(() => {
    void cargar();
  }, [cargar]);

  const set = (clave: string, v: Valor) => setValores((prev) => ({ ...prev, [clave]: v }));

  async function guardar() {
    if (!resp) return;
    setGuardando(true);
    // Lote de valores nativos. El backend solo persiste (y cuenta) las
    // desviaciones reales respecto al valor base, así que reenviar todo es seguro.
    const cambios: Record<string, unknown> = {};
    for (const g of resp.grupos) {
      for (const a of g.ajustes) {
        const v = valores[a.clave];
        if (a.tipo === "booleano") {
          cambios[a.clave] = Boolean(v);
        } else if (a.tipo === "entero") {
          const s = String(v ?? "").trim();
          if (s !== "") cambios[a.clave] = Number(s);
        } else if (a.tipo === "secreto") {
          const s = String(v ?? "");
          if (s !== "") cambios[a.clave] = s; // vacío = no cambiar
        } else {
          cambios[a.clave] = String(v ?? "");
        }
      }
    }
    try {
      const r = await api.guardarConfiguracion(cambios);
      const n = r.modificadas.length;
      toast.success(
        n === 0
          ? "No había cambios que guardar."
          : `${n} ajuste${n === 1 ? "" : "s"} modificado${n === 1 ? "" : "s"}.`,
      );
      await cargar();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "No se pudo guardar la configuración.");
    } finally {
      setGuardando(false);
    }
  }

  async function restablecer(a: AjusteConfig) {
    try {
      await api.restablecerAjuste(a.clave);
      toast.success(`«${a.etiqueta}» restablecido a su valor base.`);
      await cargar();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "No se pudo restablecer el ajuste.");
    }
  }

  async function probar(e: React.FormEvent) {
    e.preventDefault();
    setProbando(true);
    setResultadoCorreo(null);
    try {
      const r = await api.probarCorreo(destinatario.trim());
      const mensaje = `Correo de prueba enviado a ${r.destinatarios} destinatario${
        r.destinatarios === 1 ? "" : "s"
      }.`;
      toast.success(mensaje);
      setResultadoCorreo({ ok: true, mensaje });
    } catch (err) {
      const mensaje =
        err instanceof ApiError ? err.message : "No se pudo enviar el correo de prueba.";
      toast.error(mensaje);
      setResultadoCorreo({ ok: false, mensaje });
    } finally {
      setProbando(false);
    }
  }

  // Acceso restringido a administradores (el backend responde 403 igualmente).
  const permitido = puede("configuracion.gestionar") || usuario?.rol === "admin";
  if (!permitido) {
    return (
      <>
        <PageHeader titulo="Configuración del sistema" />
        <EmptyState
          icono={Lock}
          titulo="Acceso restringido"
          descripcion="Solo los administradores pueden ver y modificar la configuración del sistema."
        />
      </>
    );
  }

  if (cargando || !resp) {
    return (
      <>
        <PageHeader titulo="Configuración del sistema" />
        <PageSkeleton variante="formulario" cabecera={false} />
      </>
    );
  }

  // Helper (no componente) para no crear componentes anidados en cada render.
  const botonRestablecer = (a: AjusteConfig) =>
    a.origen === "configurado" ? (
      <Button
        type="button"
        variant="ghost"
        size="sm"
        onClick={() => void restablecer(a)}
        disabled={guardando}
        title={`Restablecer «${a.etiqueta}» a su valor base`}
      >
        <RotateCcw /> Restablecer
      </Button>
    ) : null;

  return (
    <>
      <PageHeader
        titulo="Configuración del sistema"
        descripcion="Ajustes operativos que se aplican al instante y sin reiniciar. Cada cambio queda registrado en la auditoría; los secretos se guardan cifrados y nunca se muestran."
        acciones={
          <Button onClick={() => void guardar()} disabled={guardando}>
            {guardando ? <Loader2 className="animate-spin" /> : <Save />}
            Guardar cambios
          </Button>
        }
      />

      <div className="flex flex-col gap-4">
        {resp.grupos.map((g) => {
          const Icono = ICONO_GRUPO[g.grupo] ?? SlidersHorizontal;
          return (
            <div key={g.grupo} className="overflow-hidden rounded-xl border bg-card">
              <div className="border-b px-5 py-3.5">
                <SectionHeader icono={Icono} titulo={g.grupo} contador={g.ajustes.length} />
              </div>
              <div className="grid gap-x-6 gap-y-5 p-5 sm:grid-cols-2">
                {g.ajustes.map((a) => {
                  const idc = `cfg-${a.clave}`;
                  if (a.tipo === "booleano") {
                    return (
                      <div
                        key={a.clave}
                        className="flex items-start justify-between gap-4 rounded-lg border border-dashed p-4 sm:col-span-2"
                      >
                        <div className="space-y-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <Label htmlFor={idc}>{a.etiqueta}</Label>
                            <OrigenBadge origen={a.origen} />
                          </div>
                          <p className="text-xs text-muted-foreground">{a.ayuda}</p>
                        </div>
                        <div className="flex shrink-0 items-center gap-1.5">
                          {botonRestablecer(a)}
                          <Switch
                            id={idc}
                            checked={Boolean(valores[a.clave])}
                            onCheckedChange={(x) => set(a.clave, x)}
                            aria-label={a.etiqueta}
                          />
                        </div>
                      </div>
                    );
                  }
                  return (
                    <div
                      key={a.clave}
                      className={cn("space-y-2", a.tipo === "secreto" && "sm:col-span-2")}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <Label htmlFor={idc}>{a.etiqueta}</Label>
                          <OrigenBadge origen={a.origen} />
                        </div>
                        {botonRestablecer(a)}
                      </div>
                      {a.tipo === "entero" ? (
                        <Input
                          id={idc}
                          type="number"
                          min={a.minimo ?? undefined}
                          max={a.maximo ?? undefined}
                          value={String(valores[a.clave] ?? "")}
                          onChange={(e) => set(a.clave, e.target.value)}
                        />
                      ) : a.tipo === "secreto" ? (
                        <Input
                          id={idc}
                          type="password"
                          autoComplete="new-password"
                          placeholder={
                            a.configurado
                              ? "configurada — dejar vacío para conservar"
                              : "sin configurar"
                          }
                          value={String(valores[a.clave] ?? "")}
                          onChange={(e) => set(a.clave, e.target.value)}
                        />
                      ) : (
                        <Input
                          id={idc}
                          type="text"
                          maxLength={255}
                          value={String(valores[a.clave] ?? "")}
                          onChange={(e) => set(a.clave, e.target.value)}
                        />
                      )}
                      <p className="text-xs text-muted-foreground">{a.ayuda}</p>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}

        <div className="flex justify-end">
          <Button onClick={() => void guardar()} disabled={guardando}>
            {guardando ? <Loader2 className="animate-spin" /> : <Save />}
            Guardar cambios
          </Button>
        </div>

        {/* Probar el correo */}
        <div className="overflow-hidden rounded-xl border bg-card">
          <div className="border-b px-5 py-3.5">
            <SectionHeader icono={Mail} titulo="Probar el correo" />
          </div>
          <form onSubmit={probar} className="space-y-3 p-5">
            <p className="text-xs text-muted-foreground">
              Envía un mensaje de prueba con la configuración SMTP guardada (guarde primero los
              cambios). El correo no contiene ningún secreto.
            </p>
            <div className="flex flex-wrap items-end gap-3">
              <div className="min-w-60 flex-1 space-y-2">
                <Label htmlFor="destinatario">
                  Destinatario (opcional; si se omite, usa la lista configurada)
                </Label>
                <Input
                  id="destinatario"
                  type="email"
                  placeholder="prueba@empresa.local"
                  value={destinatario}
                  onChange={(e) => setDestinatario(e.target.value)}
                />
              </div>
              <Button type="submit" variant="outline" disabled={probando}>
                {probando ? <Loader2 className="animate-spin" /> : <Send />}
                Enviar correo de prueba
              </Button>
            </div>
            {resultadoCorreo && (
              <p
                className={cn(
                  "flex items-center gap-1.5 text-[13px]",
                  resultadoCorreo.ok ? "text-foreground" : "text-destructive",
                )}
              >
                {resultadoCorreo.ok ? (
                  <CheckCircle2 className="size-4" />
                ) : (
                  <TriangleAlert className="size-4" />
                )}
                {resultadoCorreo.mensaje}
              </p>
            )}
          </form>
        </div>

        {/* Información del sistema (solo lectura) */}
        <div className="overflow-hidden rounded-xl border bg-card">
          <div className="border-b px-5 py-3.5">
            <SectionHeader icono={Info} titulo="Información del sistema (solo lectura)" />
          </div>
          <div className="p-5">
            <p className="mb-4 text-xs text-muted-foreground">
              Definido por entorno o requiere reinicio; no editable aquí.
            </p>
            <dl className="grid gap-x-8 gap-y-2.5 sm:grid-cols-2">
              {resp.info_sistema.map((i) => (
                <div
                  key={i.etiqueta}
                  className="flex items-baseline justify-between gap-3 border-b border-dashed pb-2.5"
                >
                  <dt className="text-[13px] text-muted-foreground">{i.etiqueta}</dt>
                  <dd className="text-right">
                    <Mono className="text-[13px] font-medium">{String(i.valor)}</Mono>
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        </div>
      </div>
    </>
  );
}
