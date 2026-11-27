"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Bot, History, Loader2, RotateCw, Send, ShieldCheck } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { RotacionAsiento, RotacionDeCredencial, TipoRotacion } from "@/lib/types";
import { ETIQUETA_ESTADO, ETIQUETA_TIPO, ETIQUETA_VERIFICACION, fecha, textoDesvio } from "@/lib/rotacion";
import { useSession } from "@/lib/session";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { DialogoAutorizar } from "./dialogo-autorizar";
import { toast } from "sonner";
import { instante } from "@/lib/fechas";

function Asiento({ a }: { a: RotacionAsiento }) {
  return (
    <div className="border-b py-3 text-sm last:border-0">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={a.estado === "cerrada" ? "secondary" : "outline"}>
          {ETIQUETA_ESTADO[a.estado]}
        </Badge>
        <Badge variant="outline">{ETIQUETA_TIPO[a.tipo]}</Badge>
        {a.temprana && <Badge variant="destructive">Temprana</Badge>}
        {a.emergencia_sin_segundo_par && (
          <Badge variant="destructive">Emergencia sin segundo par</Badge>
        )}
        {a.revision_pendiente && <Badge variant="destructive">Revisión pendiente</Badge>}
        <span className="ml-auto text-xs text-muted-foreground">{fecha(a.solicitado_en)}</span>
      </div>
      <p className="mt-1.5">{a.motivo}</p>
      <p className="mt-1 text-xs text-muted-foreground">
        Solicitada por {a.solicitado_por}
        {a.autorizado_por && ` · autorizada por ${a.autorizado_por}`}
        {a.confirmado_en && ` · aplicada el ${fecha(a.confirmado_en)}`}
      </p>
      {a.agente_nombre && (
        <p className="mt-1 flex items-center gap-1 text-xs text-muted-foreground">
          <Bot className="size-3" /> {a.estado === "cerrada" ? "Ejecutada por el agente" : "En manos del agente"} {a.agente_nombre}
          {a.estado === "cerrada" && ` · ${ETIQUETA_VERIFICACION[a.verificacion]}`}
        </p>
      )}
      {a.verificacion === "local" && (
        <p className="mt-1 text-xs text-muted-foreground">
          Verificación local: la contraseña nueva autentica la cuenta en el sistema operativo. No
          se ha comprobado contra el servicio declarado (SSH, RDP…), que puede tener sus propias
          restricciones.
        </p>
      )}
      {a.estado === "cerrada" && a.detalle_error && (
        <p className="mt-1 text-xs text-muted-foreground">{a.detalle_error}</p>
      )}
      {textoDesvio(a) && <p className="mt-1 text-xs text-muted-foreground">{textoDesvio(a)}</p>}
      {a.motivo_rechazo && (
        <p className="mt-1 text-xs text-destructive">Rechazo: {a.motivo_rechazo}</p>
      )}
    </div>
  );
}

export function PanelRotacionCredencial({ credencialId }: { credencialId: number }) {
  const { puede, usuario } = useSession();
  const [data, setData] = useState<RotacionDeCredencial | null>(null);
  const [motivo, setMotivo] = useState("");
  const [tipo, setTipo] = useState<TipoRotacion>("manual");
  const [passwordAplicada, setPasswordAplicada] = useState("");
  const [ocupado, setOcupado] = useState(false);

  const cargar = useCallback(() => {
    api
      .rotacionDeCredencial(credencialId)
      .then(setData)
      .catch((e) => toast.error(e instanceof ApiError ? e.message : "No se pudo cargar la rotación."));
  }, [credencialId]);

  useEffect(cargar, [cargar]);

  async function ejecutar(accion: () => Promise<unknown>, exito: string) {
    setOcupado(true);
    try {
      await accion();
      toast.success(exito);
      setMotivo("");
      setPasswordAplicada("");
      cargar();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "La operación no se pudo completar.");
    } finally {
      setOcupado(false);
    }
  }

  if (!data) {
    return (
      <Card className="mt-6">
        <CardContent className="flex justify-center py-10">
          <Loader2 className="size-5 animate-spin text-muted-foreground" />
        </CardContent>
      </Card>
    );
  }

  const abierta = data.solicitud_abierta;
  const esSolicitante = abierta?.solicitado_por === usuario?.username;
  const porAgente = data.via_rotacion === "agente";
  const trabajo = data.trabajo_en_curso;

  return (
    <Card className="mt-6">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <RotateCw className="size-4" /> Rotación de la contraseña
        </CardTitle>
        <CardDescription>
          Cambiar esta contraseña exige una solicitud con motivo y la autorización de otro
          administrador. Todo el ciclo queda en el libro mayor, con la antigüedad de la
          contraseña al solicitar, al autorizar y al rotar.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="grid gap-2 text-sm sm:grid-cols-2">
          <p>
            <span className="text-muted-foreground">Antigüedad actual: </span>
            {data.dias_sin_rotar} día(s)
          </p>
          <p>
            <span className="text-muted-foreground">Fecha de política: </span>
            {fecha(data.fecha_programada)}
          </p>
          {data.usada_por && (
            <p className="sm:col-span-2">
              <span className="text-muted-foreground">Usada por: </span>
              {data.usada_por}
            </p>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-muted-foreground">Vía de rotación:</span>
          <Badge variant="outline">
            {porAgente ? (
              <>
                <Bot className="size-3" /> Agente del activo
              </>
            ) : (
              "Manual"
            )}
          </Badge>
          {puede("agentes.gestionar") && !abierta && (
            <Button
              size="sm"
              variant="ghost"
              disabled={ocupado}
              onClick={() =>
                ejecutar(
                  () => api.cambiarViaRotacion(credencialId, porAgente ? "manual" : "agente"),
                  porAgente
                    ? "La credencial se rotará a mano."
                    : "La credencial se rotará con el agente de su activo.",
                )
              }
            >
              {porAgente ? "Rotar a mano" : "Rotar con el agente"}
            </Button>
          )}
        </div>

        {data.usada_por && (
          <p className="flex items-start gap-2 rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
            <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
            Antes de rotar, compruebe lo que depende de esta cuenta: un cambio de contraseña
            puede dejar sin servicio a los automatismos que la usan, o bloquear la cuenta por
            intentos fallidos.
          </p>
        )}

        {!abierta && puede("rotacion.solicitar") && (
          <div className="space-y-3 rounded-lg border p-3">
            <p className="text-sm font-medium">{porAgente ? "Rotar ahora" : "Solicitar rotación"}</p>
            {porAgente && (
              <p className="text-xs text-muted-foreground">
                El agente del activo la aplicará en cuanto otro administrador la autorice. Hasta
                entonces no se toca nada.
              </p>
            )}
            {data.temprana_si_se_rota_ahora && (
              <p className="text-xs text-destructive">
                Sería una rotación temprana: la contraseña está muy por debajo de su vigencia,
                así que el motivo debe explicar qué la hace necesaria ahora.
              </p>
            )}
            <div className="grid gap-3 sm:grid-cols-[1fr_auto]">
              <div className="space-y-2">
                <Label htmlFor="motivo-rotacion">Motivo</Label>
                <Textarea
                  id="motivo-rotacion"
                  rows={2}
                  value={motivo}
                  placeholder="Por qué hay que cambiar esta contraseña ahora"
                  onChange={(e) => setMotivo(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label>Tipo</Label>
                <Select value={tipo} onValueChange={(x) => setTipo(x as TipoRotacion)}>
                  <SelectTrigger className="w-44">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="manual">Manual</SelectItem>
                    <SelectItem value="programada">Programada</SelectItem>
                    <SelectItem value="emergencia">Emergencia</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <Button
              disabled={ocupado}
              onClick={() =>
                ejecutar(
                  () => api.rotacionSolicitar({ credencial_id: credencialId, motivo, tipo }),
                  "Solicitud creada. Otro administrador debe autorizarla.",
                )
              }
            >
              {ocupado && <Loader2 className="size-4 animate-spin" />}
              {porAgente ? "Rotar ahora" : "Solicitar rotación"}
            </Button>
          </div>
        )}

        {abierta && (
          <div className="space-y-3 rounded-lg border p-3">
            <Asiento a={abierta} />

            {abierta.estado === "solicitada" && puede("rotacion.autorizar") && (
              <div className="flex flex-wrap gap-2">
                <DialogoAutorizar
                  titulo="Autorizar la rotación"
                  descripcion="Confirme su identidad para dejar constancia de quién autoriza este cambio."
                  textoBoton="Autorizar"
                  disparador={
                    <Button size="sm">
                      <ShieldCheck className="size-4" /> Autorizar
                    </Button>
                  }
                  onConfirmar={async (password, codigo) => {
                    await ejecutar(
                      () => api.rotacionAutorizar(abierta.id, { password, codigo }),
                      "Rotación autorizada.",
                    );
                  }}
                />
                <Button
                  size="sm"
                  variant="outline"
                  disabled={ocupado || motivo.trim().length < 10}
                  onClick={() =>
                    ejecutar(() => api.rotacionRechazar(abierta.id, motivo), "Solicitud rechazada.")
                  }
                >
                  Rechazar
                </Button>
                <Textarea
                  rows={1}
                  className="w-full"
                  placeholder="Motivo del rechazo (mínimo 10 caracteres)"
                  value={motivo}
                  onChange={(e) => setMotivo(e.target.value)}
                />
              </div>
            )}

            {abierta.estado === "solicitada" && (esSolicitante || puede("rotacion.autorizar")) && (
              <Button
                size="sm"
                variant="ghost"
                disabled={ocupado}
                onClick={() =>
                  ejecutar(() => api.rotacionCancelar(abierta.id), "Solicitud cancelada.")
                }
              >
                Cancelar la solicitud
              </Button>
            )}

            {abierta.estado === "autorizada" && porAgente && puede("rotacion.solicitar") && (
              <div className="space-y-2 rounded-md bg-muted/50 p-3">
                <p className="text-xs text-muted-foreground">
                  Autorizada, pero el agente aún no la tiene
                  {data.motivo_no_despacho ? <>: <strong className="text-foreground">{data.motivo_no_despacho}</strong></> : "."}{" "}
                  Puede volver a enviársela cuando se resuelva, o cambiarla a mano y registrarla abajo.
                </p>
                <Button
                  size="sm"
                  disabled={ocupado}
                  onClick={() => ejecutar(() => api.rotacionDespachar(abierta.id), "Enviada al agente.")}
                >
                  <Send className="size-4" /> Enviar al agente
                </Button>
              </div>
            )}

            {abierta.estado === "despachada" && trabajo && !trabajo.sin_confirmar && (
              <p className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="size-4 animate-spin" />
                En manos del agente {trabajo.agente}
                {trabajo.estado === "pendiente"
                  ? ` · debe recogerla antes de las ${instante(trabajo.ventana_expira_en).toLocaleTimeString()}`
                  : " · recogida, esperando su resultado"}
              </p>
            )}

            {abierta.estado === "despachada" && trabajo?.sin_confirmar && (
              <div className="space-y-2 rounded-md border border-destructive/40 p-3">
                <p className="flex items-center gap-2 text-sm font-medium text-destructive">
                  <AlertTriangle className="size-4" /> Sin confirmar
                </p>
                <p className="text-xs text-muted-foreground">
                  El agente {trabajo.agente} recogió la rotación y no informó del resultado: la
                  contraseña pudo cambiar en el activo o no. Compruébelo en el servidor y diga qué
                  quedó. Hasta entonces esta credencial no admite otra rotación.
                </p>
                {puede("rotacion.autorizar") && (
                  <div className="flex flex-wrap gap-2">
                    <DialogoAutorizar
                      titulo="La contraseña nueva SÍ quedó aplicada"
                      descripcion="Se registrará la contraseña nueva en el inventario. Confirme su identidad."
                      textoBoton="Confirmar"
                      disparador={<Button size="sm">Sí, quedó la nueva</Button>}
                      onConfirmar={async (password, codigo) => {
                        await ejecutar(
                          () => api.rotacionResolverTrabajo(trabajo.id, { aplicada: true, password, codigo }),
                          "Registrada la contraseña nueva.",
                        );
                      }}
                    />
                    <DialogoAutorizar
                      titulo="La contraseña nueva NO quedó aplicada"
                      descripcion="El inventario conserva la contraseña anterior y la rotación se cierra como fallida. Confirme su identidad."
                      textoBoton="Confirmar"
                      disparador={<Button size="sm" variant="outline">No, sigue la anterior</Button>}
                      onConfirmar={async (password, codigo) => {
                        await ejecutar(
                          () => api.rotacionResolverTrabajo(trabajo.id, { aplicada: false, password, codigo }),
                          "Rotación cerrada como fallida; el inventario conserva la anterior.",
                        );
                      }}
                    />
                  </div>
                )}
              </div>
            )}

            {abierta.estado === "autorizada" && puede("rotacion.solicitar") && (
              <div className="space-y-2">
                <Label htmlFor="password-aplicada">
                  Contraseña que quedó aplicada en el activo
                </Label>
                <Input
                  id="password-aplicada"
                  type="password"
                  autoComplete="off"
                  value={passwordAplicada}
                  onChange={(e) => setPasswordAplicada(e.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  Cámbiela primero en el servidor y regístrela aquí. La anterior pasa al historial
                  cifrado y el ciclo se cierra con la antigüedad real y su desviación.
                </p>
                <Button
                  disabled={ocupado || !passwordAplicada}
                  onClick={() =>
                    ejecutar(
                      () => api.rotacionAplicarManual(abierta.id, passwordAplicada),
                      "Rotación registrada.",
                    )
                  }
                >
                  {ocupado && <Loader2 className="size-4 animate-spin" />}
                  Registrar la rotación
                </Button>
              </div>
            )}
          </div>
        )}

        <div>
          <p className="mb-1 flex items-center gap-2 text-sm font-medium">
            <History className="size-4" /> Línea de tiempo
          </p>
          {data.historial.length === 0 ? (
            <EmptyState
              icono={History}
              compacto
              titulo="Sin rotaciones registradas"
              descripcion="Todavía no se ha pedido ninguna rotación de esta credencial."
            />
          ) : (
            data.historial.map((a) => <Asiento key={a.id} a={a} />)
          )}
        </div>
      </CardContent>
    </Card>
  );
}
