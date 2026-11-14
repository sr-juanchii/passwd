"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { api, setCsrf, vigilarSesion } from "./api";
import { aVencimientos, trasActividad, type MotivoSalida, type Vencimientos } from "./expiracion";
import type { Permiso, SessionState } from "./types";

interface SessionCtx extends SessionState {
  cargando: boolean;
  refrescar: () => Promise<SessionState | null>;
  puede: (p: Permiso) => boolean;
  /** Por qué se cerró la sesión (para el mensaje del login); `null` si no aplica. */
  salida: MotivoSalida | null;
  /** Instantes locales en los que vence la sesión; `null` sin sesión activa. */
  leerVencimientos: () => Vencimientos | null;
  /**
   * Contrasta la sesión con el servidor sin contar como actividad. Un fallo de
   * red devuelve "error" y NO cierra la interfaz (a diferencia de `refrescar`).
   */
  sincronizar: () => Promise<"activa" | "cerrada" | "error">;
  /** Renueva la ventana de inactividad en el servidor («Extender sesión»). */
  extender: () => Promise<boolean>;
  /** Cierra la interfaz (sin llamar al servidor) y marca el motivo de salida. */
  cerrarInterfaz: (motivo: MotivoSalida) => void;
}

const Ctx = createContext<SessionCtx | null>(null);

const VACIO: SessionState = { authenticated: false, stage: null, csrf_token: "" };

// Canal entre pestañas: si la sesión se cierra en una, las demás se cierran
// también en vez de quedarse "abiertas" sin sesión.
const CANAL = "passwd-sesion";

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [estado, setEstado] = useState<SessionState>(VACIO);
  const [cargando, setCargando] = useState(true);
  const [salida, setSalida] = useState<MotivoSalida | null>(null);
  const vencimientos = useRef<Vencimientos | null>(null);
  const autenticado = useRef(false);
  const canal = useRef<BroadcastChannel | null>(null);

  const aplicar = useCallback((s: SessionState) => {
    setCsrf(s.csrf_token ?? "");
    autenticado.current = s.authenticated;
    vencimientos.current = s.authenticated && s.sesion ? aVencimientos(s.sesion, Date.now()) : null;
    if (s.authenticated) setSalida(null);
    setEstado(s);
  }, []);

  const refrescar = useCallback(async () => {
    try {
      const s = await api.session();
      aplicar(s);
      return s;
    } catch {
      aplicar(VACIO);
      return null;
    } finally {
      setCargando(false);
    }
  }, [aplicar]);

  const cerrarLocal = useCallback(
    (motivo: MotivoSalida) => {
      if (!autenticado.current) return;
      setSalida(motivo);
      aplicar(VACIO);
    },
    [aplicar],
  );

  const cerrarInterfaz = useCallback(
    (motivo: MotivoSalida) => {
      if (!autenticado.current) return;
      cerrarLocal(motivo);
      try {
        canal.current?.postMessage({ tipo: "cerrada", motivo });
      } catch {
        /* canal no disponible */
      }
    },
    [cerrarLocal],
  );

  const sincronizar = useCallback(async () => {
    try {
      const s = await api.session();
      if (!autenticado.current) return "cerrada" as const;
      if (s.authenticated) {
        aplicar(s);
        return "activa" as const;
      }
      return "cerrada" as const;
    } catch {
      return "error" as const;
    }
  }, [aplicar]);

  const extender = useCallback(async () => {
    try {
      const r = await api.extenderSesion();
      vencimientos.current = aVencimientos(r.sesion, Date.now());
      return true;
    } catch {
      return false;
    }
  }, []);

  // Carga inicial + vigilancia de las respuestas de la API.
  useEffect(() => {
    vigilarSesion({
      alExpirar: () => cerrarInterfaz("expirada"),
      alHaberActividad: () => {
        if (vencimientos.current) vencimientos.current = trasActividad(vencimientos.current, Date.now());
      },
    });
    void refrescar();
    return () => vigilarSesion(null);
  }, [refrescar, cerrarInterfaz]);

  // Otras pestañas y vuelta a la pestaña: se revalida contra el servidor.
  useEffect(() => {
    if (typeof BroadcastChannel !== "undefined") {
      const c = new BroadcastChannel(CANAL);
      canal.current = c;
      c.onmessage = (e: MessageEvent) => {
        if (e.data?.tipo === "cerrada") cerrarLocal(e.data.motivo === "cerrada" ? "cerrada" : "expirada");
      };
    }
    const revalidar = () => {
      if (document.visibilityState !== "visible" || !autenticado.current) return;
      void sincronizar().then((r) => {
        if (r === "cerrada") cerrarInterfaz("expirada");
      });
    };
    document.addEventListener("visibilitychange", revalidar);
    window.addEventListener("focus", revalidar);
    return () => {
      document.removeEventListener("visibilitychange", revalidar);
      window.removeEventListener("focus", revalidar);
      canal.current?.close();
      canal.current = null;
    };
  }, [sincronizar, cerrarInterfaz, cerrarLocal]);

  const puede = useCallback(
    (p: Permiso) => Boolean(estado.permisos?.[p]),
    [estado.permisos],
  );

  const leerVencimientos = useCallback(() => vencimientos.current, []);

  return (
    <Ctx.Provider
      value={{ ...estado, cargando, refrescar, puede, salida, leerVencimientos, sincronizar, extender, cerrarInterfaz }}
    >
      {children}
    </Ctx.Provider>
  );
}

export function useSession(): SessionCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useSession debe usarse dentro de <SessionProvider>");
  return ctx;
}
