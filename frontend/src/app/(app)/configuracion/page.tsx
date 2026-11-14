"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  Bell,
  CheckCircle2,
  CircleSlash,
  Clock,
  Info,
  KeyRound,
  Link2Off,
  Loader2,
  Lock,
  Mail,
  PlugZap,
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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

// Valor editable de cada control: los enteros se guardan como texto (permiten un
// campo vacío durante la edición) y se convierten a número al enviar.
type Valor = string | boolean;

const ICONO_GRUPO: Record<string, React.ComponentType<{ className?: string }>> = {
  Sesión: Clock,
  "Cuentas y contraseñas": KeyRound,
  "Verificación en dos pasos": ShieldCheck,
  "Servidor de correo (SMTP)": Mail,
  Notificaciones: Bell,
  "Límites anti-abuso": Activity,
  "Inventario y auditoría": ServerCog,
};

const GRUPO_SMTP = "Servidor de correo (SMTP)";
const CLAVES_SMTP = ["smtp_host", "smtp_port", "smtp_security", "smtp_user", "smtp_password", "smtp_from"];

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

/** Valor nativo que se envía al backend; `undefined` = no enviar. */
function valorNativo(a: AjusteConfig, v: Valor | undefined): unknown {
  if (a.tipo === "booleano") return Boolean(v);
  if (a.tipo === "entero") {
    const s = String(v ?? "").trim();
    return s === "" ? undefined : Number(s);
  }
  if (a.tipo === "secreto") {
    const s = String(v ?? "");
    return s === "" ? undefined : s; // vacío = no cambiar
  }
  return String(v ?? "");
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

function Resultado({ r }: { r: { ok: boolean; mensaje: string } | null }) {
  if (!r) return null;
  return (
    <p className={cn("flex items-start gap-1.5 text-[13px]", r.ok ? "text-foreground" : "text-destructive")}>
      {r.ok ? <CheckCircle2 className="mt-0.5 size-4 shrink-0" /> : <TriangleAlert className="mt-0.5 size-4 shrink-0" />}
      {r.mensaje}
    </p>
  );
}

export default function ConfiguracionPage() {
  const { puede, usuario } = useSession();
  const [resp, setResp] = useState<ConfiguracionResp | null>(null);
  const [valores, setValores] = useState<Record<string, Valor>>({});
  const [iniciales, setIniciales] = useState<Record<string, Valor>>({});
  const [cargando, setCargando] = useState(true);
  const [guardando, setGuardando] = useState(false);
  const [destinatario, setDestinatario] = useState("");
  const [probando, setProbando] = useState<"conexion" | "correo" | null>(null);
  const [resultadoConexion, setResultadoConexion] = useState<{ ok: boolean; mensaje: string } | null>(null);
  const [resultadoCorreo, setResultadoCorreo] = useState<{ ok: boolean; mensaje: string } | null>(null);

  const cargar = useCallback(async () => {
    setCargando(true);
    try {
      const r = await api.configuracion();
      setResp(r);
      setValores(estadoInicial(r));
      setIniciales(estadoInicial(r));
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

  const todos = useMemo(() => (resp ? resp.grupos.flatMap((g) => g.ajustes) : []), [resp]);
  const porClave = useMemo(() => new Map(todos.map((a) => [a.clave, a])), [todos]);

  // Solo se envía lo que el administrador cambió en pantalla.
  const cambios = useMemo(() => {
    const c: Record<string, unknown> = {};
    for (const a of todos) {
      if (valores[a.clave] === iniciales[a.clave]) continue;
      const nativo = valorNativo(a, valores[a.clave]);
      if (nativo !== undefined) c[a.clave] = nativo;
    }
    return c;
  }, [todos, valores, iniciales]);
  const pendientes = Object.keys(cambios).length;

  /** ¿Está «activo» el ajuste del que otro depende, según lo que hay en pantalla? */
  function activo(clave: string): boolean {
    const a = porClave.get(clave);
    if (!a) return true;
    if (a.tipo === "booleano") return Boolean(valores[clave]);
    if (a.tipo === "secreto") return Boolean(valores[clave]) || Boolean(a.configurado);
    return String(valores[clave] ?? "").trim() !== "";
  }

  /** Dependencias sin cumplir de un ajuste (vacío = disponible). */
  function faltan(a: AjusteConfig): string[] {
    return a.depende_de.filter((d) => !activo(d.clave)).map((d) => d.etiqueta);
  }

  async function guardar() {
    if (!resp || pendientes === 0) return;
    setGuardando(true);
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

  async function probarConexion() {
    setProbando("conexion");
    setResultadoConexion(null);
    // Los valores del formulario, estén o no guardados.
    const v: Record<string, unknown> = {};
    for (const clave of CLAVES_SMTP) {
      const a = porClave.get(clave);
      if (!a) continue;
      const nativo = valorNativo(a, valores[clave]);
      if (nativo !== undefined) v[clave] = nativo;
    }
    try {
      const r = await api.probarConexionSmtp(v);
      setResultadoConexion({ ok: true, mensaje: r.detalle });
    } catch (err) {
      setResultadoConexion({
        ok: false,
        mensaje: err instanceof ApiError ? err.message : "No se pudo probar la conexión.",
      });
    } finally {
      setProbando(null);
    }
  }

  async function probarCorreo(e: React.FormEvent) {
    e.preventDefault();
    setProbando("correo");
    setResultadoCorreo(null);
    try {
      const r = await api.probarCorreo(destinatario.trim());
      const base = `Correo de prueba enviado a ${r.destinatarios} destinatario${
        r.destinatarios === 1 ? "" : "s"
      }.`;
      setResultadoCorreo({ ok: true, mensaje: r.aviso ? `${base} ${r.aviso}` : base });
    } catch (err) {
      setResultadoCorreo({
        ok: false,
        mensaje: err instanceof ApiError ? err.message : "No se pudo enviar el correo de prueba.",
      });
    } finally {
      setProbando(null);
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

  const smtpCambiado = CLAVES_SMTP.some((c) => c in cambios) || "smtp_enabled" in cambios;
  const sinCifrado = valores.smtp_security === "ninguna" && Boolean(valores.smtp_enabled);

  // Helpers (no componentes) para no crear componentes anidados en cada render.
  const botonRestablecer = (a: AjusteConfig) =>
    a.origen === "configurado" ? (
      <Button
        type="button"
        variant="ghost"
        size="sm"
        onClick={() => void restablecer(a)}
        disabled={guardando}
        title={
          a.tipo === "secreto"
            ? `Quitar la «${a.etiqueta}» guardada aquí`
            : `Restablecer «${a.etiqueta}» a su valor base`
        }
      >
        <RotateCcw /> {a.tipo === "secreto" ? "Quitar" : "Restablecer"}
      </Button>
    ) : null;

  const notaDependencia = (pendientesDe: string[]) =>
    pendientesDe.length > 0 ? (
      <p className="flex items-start gap-1.5 text-xs text-amber-600 dark:text-amber-500">
        <Link2Off className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
        Sin efecto hasta activar {pendientesDe.map((e) => `«${e}»`).join(" y ")}.
      </p>
    ) : null;

  const botonGuardar = (
    <Button onClick={() => void guardar()} disabled={guardando || pendientes === 0}>
      {guardando ? <Loader2 className="animate-spin" /> : <Save />}
      {pendientes > 0 ? `Guardar ${pendientes} cambio${pendientes === 1 ? "" : "s"}` : "Sin cambios"}
    </Button>
  );

  return (
    <>
      <PageHeader
        titulo="Configuración del sistema"
        descripcion="Ajustes operativos que se aplican al instante y sin reiniciar. Cada cambio queda registrado en la auditoría; los secretos se guardan cifrados y nunca se muestran."
        acciones={botonGuardar}
      />

      <div className="flex flex-col gap-4">
        {resp.grupos.map((g) => {
          const Icono = ICONO_GRUPO[g.grupo] ?? SlidersHorizontal;
          return (
            <div key={g.grupo} className="overflow-hidden rounded-xl border bg-card">
              <div className="border-b px-5 py-3.5">
                <SectionHeader icono={Icono} titulo={g.grupo} />
                <p className="mt-1 text-xs text-muted-foreground">{g.descripcion}</p>
              </div>
              <div className="grid gap-x-6 gap-y-5 p-5 sm:grid-cols-2">
                {g.ajustes.map((a) => {
                  const idc = `cfg-${a.clave}`;
                  const pendientesDe = faltan(a);
                  const inactivo = pendientesDe.length > 0;
                  if (a.tipo === "booleano") {
                    return (
                      <div
                        key={a.clave}
                        className={cn(
                          "flex items-start justify-between gap-4 rounded-lg border border-dashed p-4 sm:col-span-2",
                          inactivo && "bg-muted/30",
                        )}
                      >
                        <div className="space-y-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <Label htmlFor={idc}>{a.etiqueta}</Label>
                            <OrigenBadge origen={a.origen} />
                          </div>
                          <p className="text-xs text-muted-foreground">{a.ayuda}</p>
                          {notaDependencia(pendientesDe)}
                        </div>
                        <div className="flex shrink-0 items-center gap-1.5">
                          {botonRestablecer(a)}
                          <Switch
                            id={idc}
                            checked={Boolean(valores[a.clave])}
                            onCheckedChange={(x) => set(a.clave, x)}
                            disabled={inactivo}
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
                          <Label htmlFor={idc}>
                            {a.etiqueta}
                            {a.unidad && <span className="font-normal text-muted-foreground"> ({a.unidad})</span>}
                          </Label>
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
                          disabled={inactivo}
                          value={String(valores[a.clave] ?? "")}
                          onChange={(e) => set(a.clave, e.target.value)}
                        />
                      ) : a.tipo === "opcion" ? (
                        <Select
                          value={String(valores[a.clave] ?? "")}
                          onValueChange={(v) => set(a.clave, v)}
                          disabled={inactivo}
                        >
                          <SelectTrigger id={idc} className="w-full">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {a.opciones.map((o) => (
                              <SelectItem key={o.valor} value={o.valor}>
                                {o.etiqueta}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      ) : a.tipo === "secreto" ? (
                        <Input
                          id={idc}
                          type="password"
                          autoComplete="new-password"
                          disabled={inactivo}
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
                          disabled={inactivo}
                          value={String(valores[a.clave] ?? "")}
                          onChange={(e) => set(a.clave, e.target.value)}
                        />
                      )}
                      <p className="text-xs text-muted-foreground">{a.ayuda}</p>
                      {notaDependencia(pendientesDe)}
                      {a.clave === "smtp_security" && sinCifrado && (
                        <p className="flex items-start gap-1.5 text-xs text-destructive">
                          <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
                          Sin cifrado, los correos —incluidos los códigos de verificación y la
                          contraseña SMTP— viajan en claro. Úselo solo con un relé interno de confianza.
                        </p>
                      )}
                    </div>
                  );
                })}
              </div>

              {g.grupo === GRUPO_SMTP && (
                <div className="grid gap-6 border-t p-5 lg:grid-cols-2">
                  {/* Estado: qué depende del correo y si funciona */}
                  <div className="space-y-3">
                    <div className="flex items-center gap-2 text-sm font-semibold">
                      Estado del correo
                      <Badge variant={resp.correo.operativo ? "secondary" : "outline"}>
                        {resp.correo.operativo ? "operativo" : "no operativo"}
                      </Badge>
                    </div>
                    {smtpCambiado && (
                      <p className="text-xs text-muted-foreground">
                        Refleja la configuración guardada; guarde los cambios para actualizarlo.
                      </p>
                    )}
                    {resp.correo.avisos.map((av) => (
                      <p key={av} className="flex items-start gap-1.5 text-xs text-amber-600 dark:text-amber-500">
                        <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
                        {av}
                      </p>
                    ))}
                    <ul className="space-y-2">
                      {resp.correo.funciones.map((f) => (
                        <li key={f.nombre} className="flex items-start gap-2 text-[13px]">
                          {f.activa ? (
                            <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-600 dark:text-emerald-500" />
                          ) : (
                            <CircleSlash className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                          )}
                          <span>
                            <span className={cn("font-medium", !f.activa && "text-muted-foreground")}>
                              {f.nombre}
                            </span>
                            <span className="block text-xs text-muted-foreground">{f.detalle}</span>
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>

                  {/* Pruebas */}
                  <div className="space-y-4">
                    <div className="space-y-2">
                      <div className="text-sm font-semibold">Probar la conexión</div>
                      <p className="text-xs text-muted-foreground">
                        Conecta y se autentica con los valores de este formulario, aunque no estén
                        guardados. No envía ningún correo.
                      </p>
                      <Button
                        type="button"
                        variant="outline"
                        onClick={() => void probarConexion()}
                        disabled={probando !== null || !String(valores.smtp_host ?? "").trim()}
                      >
                        {probando === "conexion" ? <Loader2 className="animate-spin" /> : <PlugZap />}
                        Probar conexión
                      </Button>
                      <Resultado r={resultadoConexion} />
                    </div>
                    <form onSubmit={probarCorreo} className="space-y-2">
                      <div className="text-sm font-semibold">Enviar un correo de prueba</div>
                      <p className="text-xs text-muted-foreground">
                        Usa la configuración guardada{smtpCambiado ? " (tiene cambios sin guardar)" : ""}.
                        Si no indica destinatario se usan los de las alertas. No contiene secretos.
                      </p>
                      <div className="flex flex-wrap items-end gap-2">
                        <Input
                          type="email"
                          aria-label="Destinatario del correo de prueba"
                          placeholder="prueba@empresa.local"
                          className="min-w-52 flex-1"
                          value={destinatario}
                          onChange={(e) => setDestinatario(e.target.value)}
                        />
                        <Button type="submit" variant="outline" disabled={probando !== null}>
                          {probando === "correo" ? <Loader2 className="animate-spin" /> : <Send />}
                          Enviar prueba
                        </Button>
                      </div>
                      <Resultado r={resultadoCorreo} />
                    </form>
                  </div>
                </div>
              )}
            </div>
          );
        })}

        <div className="flex justify-end">{botonGuardar}</div>

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
