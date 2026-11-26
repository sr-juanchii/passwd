import { describe, expect, it } from "vitest";
import { comandoInstalacion, ETIQUETA_COBERTURA, haceCuanto, rutaActivo } from "./agentes";

describe("agentes", () => {
  it("nombra todas las coberturas", () => {
    expect(Object.keys(ETIQUETA_COBERTURA).sort()).toEqual(
      ["caducado", "conectado", "pendiente", "sin_agente", "sin_contacto"],
    );
  });

  it("lleva a la ficha de cada tipo de activo", () => {
    expect(rutaActivo("fisico", 3)).toBe("/servidores/3");
    expect(rutaActivo("hipervisor", 4)).toBe("/hipervisores/4");
    expect(rutaActivo("vm", 5)).toBe("/vms/5");
  });

  it("dice cuánto hace del último latido", () => {
    const ahora = new Date("2026-11-26T10:00:00Z");
    expect(haceCuanto(null, ahora)).toBe("nunca");
    expect(haceCuanto("2026-11-26T09:59:30Z", ahora)).toBe("hace un momento");
    expect(haceCuanto("2026-11-26T09:45:00Z", ahora)).toBe("hace 15 min");
    expect(haceCuanto("2026-11-26T07:00:00Z", ahora)).toBe("hace 3 h");
    expect(haceCuanto("2026-11-20T10:00:00Z", ahora)).toBe("hace 6 días");
  });

  it("la orden de instalación nunca lleva el token", () => {
    const orden = comandoInstalacion("https://passwd.ejemplo.org", ["deploy", "backup"]);
    expect(orden).toContain("--cuentas deploy,backup");
    expect(orden).toContain("--token -");
    expect(orden).toContain("--sumas SHA256SUMS");
  });
});
