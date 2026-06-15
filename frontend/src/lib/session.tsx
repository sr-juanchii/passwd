"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, setCsrf } from "./api";
import type { Permiso, SessionState } from "./types";

interface SessionCtx extends SessionState {
  cargando: boolean;
  refrescar: () => Promise<SessionState | null>;
  puede: (p: Permiso) => boolean;
}

const Ctx = createContext<SessionCtx | null>(null);

const VACIO: SessionState = { authenticated: false, stage: null, csrf_token: "" };

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [estado, setEstado] = useState<SessionState>(VACIO);
  const [cargando, setCargando] = useState(true);

  const refrescar = useCallback(async () => {
    try {
      const s = await api.session();
      setCsrf(s.csrf_token);
      setEstado(s);
      return s;
    } catch {
      setEstado(VACIO);
      return null;
    } finally {
      setCargando(false);
    }
  }, []);

  useEffect(() => {
    void refrescar();
  }, [refrescar]);

  const puede = useCallback(
    (p: Permiso) => Boolean(estado.permisos?.[p]),
    [estado.permisos],
  );

  return (
    <Ctx.Provider value={{ ...estado, cargando, refrescar, puede }}>{children}</Ctx.Provider>
  );
}

export function useSession(): SessionCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useSession debe usarse dentro de <SessionProvider>");
  return ctx;
}
