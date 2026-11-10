"use client";

import { useEffect, useRef, useState } from "react";
import { Loader2, ShieldAlert } from "lucide-react";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { estadoExpiracion, formatoCuentaAtras, type EstadoExpiracion } from "@/lib/expiracion";
import { useSession } from "@/lib/session";

/**
 * Vigila el vencimiento de la sesión mientras la aplicación está abierta.
 *
 * - Poco antes de que venza muestra un aviso con cuenta atrás: «Extender sesión»
 *   o «Cerrar sesión ahora».
 * - Si llega a cero, cierra la interfaz y lleva al inicio de sesión con un
 *   mensaje claro; nunca deja la aplicación "abierta" sin sesión.
 *
 * Antes de avisar o de cerrar se confirma el plazo real con el servidor (otra
 * pestaña puede haber mantenido viva la sesión).
 */
export function SessionGuard() {
  const { leerVencimientos, sincronizar, extender, cerrarInterfaz } = useSession();
  const [aviso, setAviso] = useState<EstadoExpiracion | null>(null);
  const [ocupado, setOcupado] = useState<"extender" | "cerrar" | null>(null);
  const sincronizando = useRef(false);
  const confirmado = useRef(false); // el aviso ya se contrastó con el servidor

  useEffect(() => {
    async function contrastar() {
      sincronizando.current = true;
      try {
        return await sincronizar();
      } finally {
        sincronizando.current = false;
      }
    }

    async function comprobar() {
      if (sincronizando.current) return;
      const v = leerVencimientos();
      if (!v) return;
      const e = estadoExpiracion(v, Date.now());

      if (e.fase === "ok") {
        confirmado.current = false;
        setAviso(null);
        return;
      }
      if (e.fase === "vencida") {
        // La estimación local es prudente: se pregunta al servidor antes de
        // cerrar. Sin respuesta (sin red) se cierra igualmente: lo seguro.
        if ((await contrastar()) !== "activa") cerrarInterfaz("expirada");
        return;
      }
      if (!confirmado.current) {
        confirmado.current = true;
        const r = await contrastar();
        if (r === "cerrada") cerrarInterfaz("expirada");
        if (r !== "error") return; // el siguiente tic usa el plazo real
      }
      setAviso(e);
    }

    const id = window.setInterval(() => void comprobar(), 1000);
    return () => window.clearInterval(id);
  }, [leerVencimientos, sincronizar, cerrarInterfaz]);

  async function alExtender() {
    setOcupado("extender");
    const ok = await extender();
    setOcupado(null);
    if (ok) {
      confirmado.current = false;
      setAviso(null);
    }
  }

  async function alCerrar() {
    setOcupado("cerrar");
    try {
      await api.logout();
    } catch {
      /* si falla, la interfaz se cierra igualmente */
    }
    cerrarInterfaz("cerrada");
  }

  if (!aviso) return null;

  return (
    <AlertDialog open>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle className="flex items-center gap-2">
            <ShieldAlert className="size-5 text-amber-500" aria-hidden="true" />
            Su sesión está a punto de cerrarse
          </AlertDialogTitle>
          <AlertDialogDescription>
            {aviso.extensible
              ? "Por seguridad, la sesión se cierra tras un periodo sin actividad. ¿Desea seguir trabajando?"
              : "Su sesión alcanzó la duración máxima permitida y no puede extenderse. Guarde su trabajo; después deberá iniciar sesión de nuevo."}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <p className="text-center font-mono text-3xl font-semibold tabular-nums" aria-live="polite">
          {formatoCuentaAtras(aviso.restanteMs)}
        </p>
        <AlertDialogFooter>
          <Button variant="outline" onClick={alCerrar} disabled={ocupado !== null}>
            {ocupado === "cerrar" && <Loader2 className="animate-spin" />}
            Cerrar sesión ahora
          </Button>
          {aviso.extensible && (
            <Button onClick={alExtender} disabled={ocupado !== null} autoFocus>
              {ocupado === "extender" && <Loader2 className="animate-spin" />}
              Extender sesión
            </Button>
          )}
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
