import { describe, expect, it } from "vitest";
import type { Credencial } from "./types";
import { DIAS_PROXIMA, nivelActivo, nivelCredencial } from "./riesgo";

function cred(over: Partial<Credencial>): Credencial {
  return {
    id: 1,
    usuario_acceso: "root",
    servicio: "SSH",
    puerto: 22,
    descripcion: "",
    dias_sin_rotar: 0,
    rotacion_vencida: false,
    puede_revelar: true,
    tipo_activo: "fisico",
    activo_id: 1,
    ...over,
  };
}

describe("nivelCredencial", () => {
  it("marca 'vencida' cuando la rotación está vencida", () => {
    expect(nivelCredencial(cred({ rotacion_vencida: true }))).toBe("vencida");
  });
  it("marca 'proxima' al alcanzar el umbral de días", () => {
    expect(nivelCredencial(cred({ dias_sin_rotar: DIAS_PROXIMA }))).toBe("proxima");
  });
  it("marca 'ok' cuando está recién rotada", () => {
    expect(nivelCredencial(cred({ dias_sin_rotar: 3 }))).toBe("ok");
  });
});

describe("nivelActivo", () => {
  it("propaga 'vencida' desde una credencial de una VM anidada", () => {
    const activo = {
      credenciales: [cred({})],
      vms: [{ credenciales: [cred({ rotacion_vencida: true })] }],
    };
    expect(nivelActivo(activo)).toBe("vencida");
  });
  it("es 'ok' si nada está por vencer", () => {
    expect(nivelActivo({ credenciales: [cred({})], vms: [] })).toBe("ok");
  });
});
