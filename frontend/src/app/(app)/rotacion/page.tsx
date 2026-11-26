"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  CheckCheck,
  ClipboardCheck,
  Eye,
  Loader2,
  RotateCw,
  ShieldCheck,
} from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { PanelRotacion, RotacionAsiento, SenalPatron } from "@/lib/types";
import { ETIQUETA_ESTADO, ETIQUETA_TIPO, fecha, textoDesvio } from "@/lib/rotacion";
import { useSession } from "@/lib/session";
import { PageHeader } from "@/components/page-header";
import { DialogoAutorizar } from "@/components/rotacion/dialogo-autorizar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { EmptyState } from "@/components/ui/empty-state";
import { PageSkeleton } from "@/components/ui/page-skeleton";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";

function Identidad({ a }: { a: RotacionAsiento }) {
  const cuerpo = (
    <>
      <span className="font-medium">{a.activo_nombre}</span>
      <span className="text-muted-foreground"> · {a.usuario_acceso}</span>
      <span className="text-muted-foreground"> ({a.servicio})</span>
    </>
  );
  return a.credencial_id ? (
    <Link href={`/credenciales/${a.credencial_id}/editar`} className="hover:underline">
      {cuerpo}
    </Link>
  ) : (
    <span>{cuerpo}</span>
  );
}

function SenalPatronFila({ s }: { s: SenalPatron }) {
  return (
    <div className="flex items-start gap-2 border-b py-2 text-sm last:border-0">
      <AlertTriangle
        className={
          s.severidad === "grave"
            ? "mt-0.5 size-4 shrink-0 text-destructive"
            : "mt-0.5 size-4 shrink-0 text-muted-foreground"
        }
      />
      <div>
        <p className="font-medium">{s.etiqueta}</p>
        <p className="text-xs text-muted-foreground">{s.descripcion}</p>
      </div>
    </div>
  );
}

export default function RotacionPage() {
  const { puede } = useSession();
  const [data, setData] = useState<PanelRotacion | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [seleccion, setSeleccion] = useState<number[]>([]);
  const [motivoRechazo, setMotivoRechazo] = useState("");
  const [ocupado, setOcupado] = useState(false);

  const cargar = useCallback(() => {
    api
      .rotacionPanel()
      .then((d) => {
        setData(d);
        setSeleccion([]);
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : "No se pudo cargar el panel."));
  }, []);

  useEffect(cargar, [cargar]);

  async function ejecutar(accion: () => Promise<unknown>, exito: string) {
    setOcupado(true);
    try {
      await accion();
      toast.success(exito);
      setMotivoRechazo("");
      cargar();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "La operación no se pudo completar.");
    } finally {
      setOcupado(false);
    }
  }

  if (error) return <EmptyState icono={RotateCw} titulo="Rotación no disponible" descripcion={error} />;
  if (!data) return <PageSkeleton />;

  const alternar = (id: number) =>
    setSeleccion((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));

  return (
    <>
      <PageHeader
        titulo="Rotación de contraseñas"
        descripcion={`Cada rotación se solicita con motivo y la autoriza otra persona. Vigencia de política: ${data.politica.intervalo_dias} días; por debajo de ${data.politica.umbral_temprana_dias} se considera temprana.`}
      />

      {!data.gobernanza.dos_pares_posible && (
        <Card className="mb-6 border-destructive/40">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base text-destructive">
              <AlertTriangle className="size-4" /> Falta el segundo administrador
            </CardTitle>
            <CardDescription>
              Hay {data.gobernanza.administradores_activos} administrador(es) activo(s) y la regla
              de dos personas necesita al menos {data.gobernanza.minimo_administradores}. Mientras
              siga así, toda rotación caerá por la vía de emergencia: quedará marcada y pendiente de
              una revisión que tampoco podrá hacer nadie más. Cree un segundo administrador.
            </CardDescription>
          </CardHeader>
        </Card>
      )}

      {data.sin_confirmar.length > 0 && (
        <Card className="mb-6 border-destructive/40">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base text-destructive">
              <AlertTriangle className="size-4" /> Rotaciones sin confirmar
            </CardTitle>
            <CardDescription>
              Un agente recogió estas rotaciones y no informó del resultado: la contraseña pudo
              cambiar en el activo o no. Compruebe cada servidor y resuélvalo desde su credencial;
              mientras tanto, esas credenciales no admiten otra rotación.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {data.sin_confirmar.map((t) => (
              <div key={t.id} className="flex flex-wrap items-center gap-2 border-b py-2 text-sm last:border-0">
                <Link href={`/credenciales/${t.credencial_id}/editar`} className="font-medium hover:underline">
                  {t.usuario_acceso}@{t.activo_nombre}
                </Link>
                <Badge variant="outline">Agente {t.agente}</Badge>
                {t.entregado_en && (
                  <span className="ml-auto text-xs text-muted-foreground">
                    Recogida el {fecha(t.entregado_en)}
                  </span>
                )}
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {data.revisiones_pendientes.length > 0 && (
        <Card className="mb-6 border-destructive/40">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base text-destructive">
              <AlertTriangle className="size-4" /> Emergencias pendientes de revisión
            </CardTitle>
            <CardDescription>
              Se autorizaron sin segundo par: el mismo administrador que las pidió las autorizó.
              Es una vía legítima y acotada, pero solo se sostiene si alguien distinto la revisa
              después.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {data.revisiones_pendientes.map((a) => (
              <div key={a.id} className="border-b py-3 text-sm last:border-0">
                <Identidad a={a} />
                <p className="mt-1 text-xs text-muted-foreground">
                  Autorizada por {a.autorizado_por} el {fecha(a.autorizado_en)} · {a.motivo}
                </p>
                {puede("rotacion.revisar") && (
                  <Button
                    size="sm"
                    variant="outline"
                    className="mt-2"
                    disabled={ocupado}
                    onClick={() =>
                      ejecutar(
                        () => api.rotacionRevisar(a.id, "Revisada desde el panel de rotación."),
                        "Emergencia revisada.",
                      )
                    }
                  >
                    <Eye className="size-4" /> Marcar como revisada
                  </Button>
                )}
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      <Card className="mb-6">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <ClipboardCheck className="size-4" /> Pendientes de autorización
          </CardTitle>
          <CardDescription>
            Nadie puede autorizar lo que pidió. Autorizar exige confirmar la contraseña y un
            código de la aplicación autenticadora.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {data.pendientes_de_autorizar.length === 0 ? (
            <EmptyState
              icono={CheckCheck}
              compacto
              titulo="Nada esperando decisión"
              descripcion="No hay solicitudes de rotación pendientes."
            />
          ) : (
            <>
              {data.pendientes_de_autorizar.map((a) => (
                <div key={a.id} className="flex items-start gap-3 border-b py-3 text-sm last:border-0">
                  {puede("rotacion.autorizar") && (
                    <Checkbox
                      className="mt-1"
                      checked={seleccion.includes(a.id)}
                      onCheckedChange={() => alternar(a.id)}
                      aria-label={`Seleccionar la solicitud de ${a.activo_nombre}`}
                    />
                  )}
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <Identidad a={a} />
                      <Badge variant="outline">{ETIQUETA_TIPO[a.tipo]}</Badge>
                      {a.temprana && <Badge variant="destructive">Temprana</Badge>}
                      <span className="ml-auto text-xs text-muted-foreground">
                        {a.dias_al_solicitar} día(s) sin rotar
                      </span>
                    </div>
                    <p className="mt-1">{a.motivo}</p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      Solicitada por {a.solicitado_por} el {fecha(a.solicitado_en)}
                    </p>
                    {puede("rotacion.autorizar") && (
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        <DialogoAutorizar
                          titulo="Autorizar la rotación"
                          descripcion={`${a.activo_nombre} · ${a.usuario_acceso}`}
                          textoBoton="Autorizar"
                          disparador={
                            <Button size="sm">
                              <ShieldCheck className="size-4" /> Autorizar
                            </Button>
                          }
                          onConfirmar={async (password, codigo) => {
                            await ejecutar(
                              () => api.rotacionAutorizar(a.id, { password, codigo }),
                              "Rotación autorizada.",
                            );
                          }}
                        />
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={ocupado || motivoRechazo.trim().length < 10}
                          onClick={() =>
                            ejecutar(
                              () => api.rotacionRechazar(a.id, motivoRechazo),
                              "Solicitud rechazada.",
                            )
                          }
                        >
                          Rechazar
                        </Button>
                      </div>
                    )}
                  </div>
                </div>
              ))}

              {puede("rotacion.autorizar") && (
                <div className="mt-4 space-y-3 border-t pt-4">
                  <Textarea
                    rows={1}
                    placeholder="Motivo del rechazo (mínimo 10 caracteres), para el botón «Rechazar»"
                    value={motivoRechazo}
                    onChange={(e) => setMotivoRechazo(e.target.value)}
                  />
                  <DialogoAutorizar
                    titulo={`Autorizar ${seleccion.length} solicitud(es)`}
                    descripcion="Una sola confirmación de identidad; cada solicitud se autoriza por separado y deja su propio asiento."
                    textoBoton="Autorizar el lote"
                    disparador={
                      <Button disabled={seleccion.length === 0 || ocupado}>
                        <ShieldCheck className="size-4" />
                        Autorizar seleccionadas ({seleccion.length})
                      </Button>
                    }
                    onConfirmar={async (password, codigo) => {
                      setOcupado(true);
                      try {
                        const r = await api.rotacionAutorizarLote({
                          ids: seleccion,
                          password,
                          codigo,
                        });
                        if (r.autorizadas.length > 0) {
                          toast.success(`${r.autorizadas.length} rotación(es) autorizadas.`);
                        }
                        for (const fallo of r.rechazadas) toast.error(fallo.motivo);
                        cargar();
                      } catch (e) {
                        toast.error(
                          e instanceof ApiError ? e.message : "No se pudo autorizar el lote.",
                        );
                      } finally {
                        setOcupado(false);
                      }
                    }}
                  />
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>

      <Card className="mb-6">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <RotateCw className="size-4" /> Autorizadas, pendientes de aplicar
          </CardTitle>
          <CardDescription>
            Cambie la contraseña en el activo y regístrela desde la credencial para cerrar el ciclo.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {data.pendientes_de_ejecutar.length === 0 ? (
            <EmptyState
              icono={CheckCheck}
              compacto
              titulo="Nada pendiente de aplicar"
              descripcion="No hay rotaciones autorizadas esperando ejecución."
            />
          ) : (
            data.pendientes_de_ejecutar.map((a) => (
              <div key={a.id} className="border-b py-3 text-sm last:border-0">
                <div className="flex flex-wrap items-center gap-2">
                  <Identidad a={a} />
                  <Badge variant="outline">{ETIQUETA_ESTADO[a.estado]}</Badge>
                  {a.emergencia_sin_segundo_par && (
                    <Badge variant="destructive">Emergencia sin segundo par</Badge>
                  )}
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  Autorizada por {a.autorizado_por} el {fecha(a.autorizado_en)}
                </p>
                {textoDesvio(a) && (
                  <p className="mt-1 text-xs text-muted-foreground">{textoDesvio(a)}</p>
                )}
              </div>
            ))
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <AlertTriangle className="size-4" /> Señales de patrón
          </CardTitle>
          <CardDescription>
            Reglas simples sobre los últimos {data.patrones.ventana_dias} días.
            {data.patrones.modo_observacion
              ? " En modo observación: se evalúan y se ven aquí, pero todavía no envían avisos, hasta calibrar los umbrales con los datos reales de esta instalación."
              : " Activas: cada señal dispara también un aviso por correo."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {data.patrones.senales.length === 0 ? (
            <EmptyState
              icono={CheckCheck}
              compacto
              titulo="Sin señales"
              descripcion="Ninguna regla de patrón ha saltado en la ventana analizada."
            />
          ) : (
            data.patrones.senales.map((s) => <SenalPatronFila key={s.regla} s={s} />)
          )}
        </CardContent>
      </Card>

      {ocupado && (
        <p className="mt-4 flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" /> Procesando…
        </p>
      )}
    </>
  );
}
