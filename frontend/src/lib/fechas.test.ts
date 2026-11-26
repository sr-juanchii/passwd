import { describe, expect, it } from "vitest";

import { instante } from "./fechas";

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
});
