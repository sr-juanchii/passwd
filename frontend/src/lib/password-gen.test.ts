import { describe, expect, it } from "vitest";
import { generarPassword } from "./password-gen";

describe("generarPassword", () => {
  it("respeta la longitud pedida (20 por defecto)", () => {
    expect(generarPassword()).toHaveLength(20);
    expect(generarPassword(32)).toHaveLength(32);
  });

  it("excluye los caracteres ambiguos I, O, l, 0 y 1", () => {
    const muestra = generarPassword(500);
    expect(muestra).not.toMatch(/[IOl01]/);
  });

  it("produce valores distintos en llamadas sucesivas (CSPRNG)", () => {
    const a = generarPassword(24);
    const b = generarPassword(24);
    expect(a).not.toEqual(b);
  });
});
