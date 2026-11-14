import { describe, expect, it } from "vitest";
import {
  aVencimientos,
  antelacionAvisoMs,
  estadoExpiracion,
  formatoCuentaAtras,
  rutaLogin,
  rutaRetornoSegura,
  trasActividad,
} from "./expiracion";

const AHORA = 1_000_000;
const plazos = (idle: number, abs: number, timeout = 900, margin = 60) => ({
  idle_expires_in: idle,
  absolute_expires_in: abs,
  idle_timeout: timeout,
  margin,
});

describe("estadoExpiracion", () => {
  it("está en fase ok lejos del vencimiento", () => {
    const e = estadoExpiracion(aVencimientos(plazos(900, 28800), AHORA), AHORA);
    expect(e.fase).toBe("ok");
    expect(e.motivo).toBe("inactividad");
  });

  it("avisa 2 minutos antes y permite extender si vence por inactividad", () => {
    const v = aVencimientos(plazos(900, 28800), AHORA);
    expect(estadoExpiracion(v, AHORA + 779_000).fase).toBe("ok");
    const e = estadoExpiracion(v, AHORA + 781_000);
    expect(e.fase).toBe("aviso");
    expect(e.extensible).toBe(true);
    expect(e.restanteMs).toBe(119_000);
  });

  it("no ofrece extender cuando vence la vida máxima", () => {
    const e = estadoExpiracion(aVencimientos(plazos(900, 60), AHORA), AHORA);
    expect(e.fase).toBe("aviso");
    expect(e.motivo).toBe("vida_maxima");
    expect(e.extensible).toBe(false);
  });

  it("marca vencida al llegar a cero", () => {
    const v = aVencimientos(plazos(10, 28800), AHORA);
    expect(estadoExpiracion(v, AHORA + 10_000).fase).toBe("vencida");
    expect(estadoExpiracion(v, AHORA + 99_000).restanteMs).toBe(0);
  });

  it("con ventanas cortas avisa a mitad de la ventana", () => {
    const v = aVencimientos(plazos(120, 28800, 120, 60), AHORA);
    expect(antelacionAvisoMs(v)).toBe(60_000);
  });
});

describe("trasActividad", () => {
  it("renueva la ventana descontando el margen del servidor", () => {
    const v = aVencimientos(plazos(100, 28800), AHORA);
    const r = trasActividad(v, AHORA + 50_000);
    expect(r.inactividadEn).toBe(AHORA + 50_000 + 900_000 - 60_000);
    expect(r.absolutaEn).toBe(v.absolutaEn);
  });

  it("nunca acorta el plazo ya conocido", () => {
    const v = aVencimientos(plazos(900, 28800), AHORA);
    expect(trasActividad(v, AHORA).inactividadEn).toBe(v.inactividadEn);
  });
});

describe("formatoCuentaAtras", () => {
  it("formatea minutos y segundos", () => {
    expect(formatoCuentaAtras(95_000)).toBe("1:35");
    expect(formatoCuentaAtras(4_200)).toBe("0:05");
    expect(formatoCuentaAtras(0)).toBe("0:00");
  });
});

describe("rutaRetornoSegura", () => {
  it("acepta rutas internas", () => {
    expect(rutaRetornoSegura("/servidores/3?tab=creds")).toBe("/servidores/3?tab=creds");
  });

  it("rechaza destinos externos y pantallas de acceso", () => {
    for (const malo of ["//evil.example", "https://evil.example", "/\\evil", "javascript:alert(1)",
      "/login", "/mfa/verificar", "/login?next=/x", "", null]) {
      expect(rutaRetornoSegura(malo)).toBeNull();
    }
  });
});

describe("rutaLogin", () => {
  it("sin motivo va al login a secas", () => {
    expect(rutaLogin(null, "/vault")).toBe("/login");
  });

  it("al expirar conserva la página de origen", () => {
    expect(rutaLogin("expirada", "/vault")).toBe("/login?motivo=expirada&next=%2Fvault");
    expect(rutaLogin("expirada", "/")).toBe("/login?motivo=expirada");
  });

  it("al cerrar sesión voluntariamente no guarda retorno", () => {
    expect(rutaLogin("cerrada", "/vault")).toBe("/login?motivo=cerrada");
  });
});
