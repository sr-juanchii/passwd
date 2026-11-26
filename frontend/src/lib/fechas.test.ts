import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { instante, soloFecha } from "./fechas";

describe("fechas del servidor", () => {
  it("una fecha sin zona es UTC, sea cual sea la zona del navegador", () => {
    expect(instante("2026-11-26T10:00:00").toISOString()).toBe("2026-11-26T10:00:00.000Z");
    expect(instante("2026-11-26T10:00:00.123456").toISOString()).toBe("2026-11-26T10:00:00.123Z");
  });

  it("una fecha con zona se respeta", () => {
    expect(instante("2026-11-26T10:00:00Z").toISOString()).toBe("2026-11-26T10:00:00.000Z");
    expect(instante("2026-11-26T10:00:00+00:00").toISOString()).toBe("2026-11-26T10:00:00.000Z");
    expect(instante("2026-11-26T06:00:00-04:00").toISOString()).toBe("2026-11-26T10:00:00.000Z");
  });

  it("una fecha sola es ese día del calendario, no el anterior", () => {
    const dia = instante("2026-12-01");
    expect([dia.getFullYear(), dia.getMonth(), dia.getDate()]).toEqual([2026, 11, 1]);
    expect(soloFecha("2026-12-01")).toBe(new Date(2026, 11, 1).toLocaleDateString());
  });
});

/**
 * El control que impide que el desfase vuelva. `new Date(cadena)` lee una fecha
 * del servidor como hora LOCAL; toda fecha que llega de la API pasa por
 * `instante`. Se admite `new Date()` (ahora) y `new Date(año, mes, día)`.
 */
describe("ninguna pantalla interpreta una fecha del servidor por su cuenta", () => {
  const RAIZ = path.resolve(__dirname, "..");
  const PERMITIDO = path.join("lib", "fechas.ts");

  function archivos(dir: string): string[] {
    return readdirSync(dir).flatMap((nombre) => {
      const ruta = path.join(dir, nombre);
      if (statSync(ruta).isDirectory()) return archivos(ruta);
      return /\.(ts|tsx)$/.test(nombre) && !/\.test\.tsx?$/.test(nombre) ? [ruta] : [];
    });
  }

  it("solo lib/fechas.ts convierte cadenas en fechas", () => {
    const infractores: string[] = [];
    for (const archivo of archivos(RAIZ)) {
      if (path.relative(RAIZ, archivo) === PERMITIDO) continue;
      readFileSync(archivo, "utf8").split("\n").forEach((linea, i) => {
        // new Date(…) con un único argumento, o Date.parse(…).
        if (/new Date\(\s*[^),\s][^,)]*\)|Date\.parse\(/.test(linea)) {
          infractores.push(`${path.relative(RAIZ, archivo)}:${i + 1}: ${linea.trim()}`);
        }
      });
    }
    expect(infractores).toEqual([]);
  });
});
