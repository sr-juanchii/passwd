"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, History, Loader2, RotateCw, ShieldCheck } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { RotacionAsiento, RotacionDeCredencial, TipoRotacion } from "@/lib/types";
import { ETIQUETA_ESTADO, ETIQUETA_TIPO, fecha, textoDesvio } from "@/lib/rotacion";
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
            <p className="text-sm font-medium">Solicitar rotación</p>
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
              Solicitar rotación
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
