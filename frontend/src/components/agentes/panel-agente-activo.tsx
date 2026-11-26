"use client";

import { useCallback, useEffect, useState } from "react";
import { Bot, Loader2, RefreshCw, ShieldOff } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { CoberturaActivo, TipoActivoAgente, TokenInstalacion } from "@/lib/types";
import { AYUDA_COBERTURA, haceCuanto } from "@/lib/agentes";
import { useSession } from "@/lib/session";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { BotonEliminar } from "@/components/boton-eliminar";
import { DialogoAutorizar } from "@/components/rotacion/dialogo-autorizar";
import { CoberturaBadge } from "./cobertura-badge";
import { TokenUnaVez } from "./token-una-vez";
import { toast } from "sonner";

/**
 * El agente de un activo, en su ficha: cobertura, último latido y, para quien
 * los gestiona, alta, reinstalación y revocación.
 *
 * Dar de alta o reemitir el token pide reautenticación: crea una identidad de
 * máquina que podrá recibir contraseñas de este servidor, y una sesión robada no
 * debe bastar para plantarla. Revocar no la pide: protege.
 */
export function PanelAgenteActivo({ tipo, activoId, nombreActivo, cuentas }: {
  tipo: TipoActivoAgente;
  activoId: number;
  nombreActivo: string;
  /** Cuentas de las credenciales del activo: van en la orden de instalación. */
  cuentas: string[];
}) {
  const { puede } = useSession();
  const [datos, setDatos] = useState<CoberturaActivo | null>(null);
  const [nombre, setNombre] = useState(`agente-${nombreActivo}`.toLowerCase().replace(/[^a-z0-9_.-]/g, "-"));
  const [token, setToken] = useState<TokenInstalacion | null>(null);

  const cargar = useCallback(() => {
    api
      .coberturaActivo(tipo, activoId)
      .then(setDatos)
      .catch((e) => toast.error(e instanceof ApiError ? e.message : "No se pudo cargar el agente."));
  }, [tipo, activoId]);

  useEffect(cargar, [cargar]);

  if (!puede("agentes.ver")) return null;
  if (!datos) {
    return (
      <Card>
        <CardContent className="flex justify-center py-8">
          <Loader2 className="size-5 animate-spin text-muted-foreground" />
        </CardContent>
      </Card>
    );
  }

  const agente = datos.agente;
  const gestiona = puede("agentes.gestionar");

  async function revocar() {
    if (!agente) return;
    try {
      await api.revocarAgente(agente.id);
      toast.success("Agente revocado: las credenciales de este activo vuelven a rotarse a mano.");
      setToken(null);
      cargar();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "No se pudo revocar.");
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Bot className="size-4" /> Agente de rotación
          <span className="ml-auto">
            <CoberturaBadge cobertura={datos.cobertura} />
          </span>
        </CardTitle>
        <CardDescription>
          {AYUDA_COBERTURA[datos.cobertura]} El agente solo aplica rotaciones que ya autorizaron
          dos personas.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {token && <TokenUnaVez datos={token} cuentas={cuentas} onCerrar={() => setToken(null)} />}

        {agente && (
          <dl className="grid gap-x-6 gap-y-1.5 text-sm sm:grid-cols-2">
            <div><dt className="inline text-muted-foreground">Nombre: </dt><dd className="inline">{agente.nombre}</dd></div>
            <div><dt className="inline text-muted-foreground">Host: </dt><dd className="inline">{agente.nombre_host || "—"}</dd></div>
            <div>
              <dt className="inline text-muted-foreground">Versión: </dt>
              <dd className="inline">
                {agente.version_agente || "—"}
                {!agente.version_admitida && <span className="text-destructive"> (por debajo de la mínima)</span>}
                {agente.version_en_gracia && <span className="text-amber-600"> (en periodo de gracia)</span>}
              </dd>
            </div>
            <div><dt className="inline text-muted-foreground">Último latido: </dt><dd className="inline">{haceCuanto(agente.ultimo_contacto_en)}</dd></div>
            {agente.token_expira_en && (
              <div><dt className="inline text-muted-foreground">Identidad válida hasta: </dt><dd className="inline">{new Date(agente.token_expira_en).toLocaleString()}</dd></div>
            )}
            {agente.clave_huella && (
              <div><dt className="inline text-muted-foreground">Huella de la clave: </dt><dd className="inline font-mono text-xs">{agente.clave_huella.slice(0, 16)}…</dd></div>
            )}
          </dl>
        )}

        {gestiona && !agente && datos.admite_agente && (
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-2">
              <Label htmlFor="nombre-agente">Nombre del agente</Label>
              <Input id="nombre-agente" className="w-72" value={nombre} onChange={(e) => setNombre(e.target.value)} />
            </div>
            <DialogoAutorizar
              titulo="Dar de alta un agente"
              descripcion="Confirme su identidad: el agente podrá recibir las contraseñas nuevas de este servidor, siempre tras una rotación autorizada por dos personas."
              textoBoton="Dar de alta"
              disparador={<Button><Bot className="size-4" /> Dar de alta un agente</Button>}
              onConfirmar={async (password, codigo) => {
                try {
                  setToken(await api.altaAgente({ tipo_activo: tipo, activo_id: activoId, nombre, password, codigo }));
                  cargar();
                } catch (e) {
                  toast.error(e instanceof ApiError ? e.message : "No se pudo dar de alta el agente.");
                  throw e;
                }
              }}
            />
          </div>
        )}

        {gestiona && agente && (
          <div className="flex flex-wrap gap-2">
            <DialogoAutorizar
              titulo="Emitir un token de instalación nuevo"
              descripcion="La identidad actual del agente quedará anulada hasta que se reinstale con el token nuevo."
              textoBoton="Emitir token"
              disparador={<Button variant="outline"><RefreshCw className="size-4" /> Reinstalar</Button>}
              onConfirmar={async (password, codigo) => {
                try {
                  setToken(await api.reemitirInstalacion(agente.id, { password, codigo }));
                  cargar();
                } catch (e) {
                  toast.error(e instanceof ApiError ? e.message : "No se pudo emitir el token.");
                  throw e;
                }
              }}
            />
            <BotonEliminar
              etiqueta="Revocar"
              titulo={`¿Revocar el agente «${agente.nombre}»?`}
              descripcion="Pierde su identidad al momento y no recibirá más trabajos. Las credenciales de este activo vuelven a rotarse a mano."
              onConfirmar={revocar}
            />
          </div>
        )}

        {!datos.admite_agente && (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <ShieldOff className="size-4" /> Este tipo de activo no admite agente.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
