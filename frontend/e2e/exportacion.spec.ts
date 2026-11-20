import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";

import { entrarComoAdministrador } from "./ayudantes";

/**
 * Exportación del inventario para migración.
 *
 * Es la operación más delicada de la aplicación: produce un CSV con TODAS las
 * contraseñas en claro. La prueba comprueba las tres cosas que la hacen
 * aceptable: que hay una confirmación explícita antes, que lo exportado es de
 * verdad lo que hay, y que la descarga queda en la bitácora.
 */

const SERVIDOR = "srv-export-e2e";
const CREDENCIAL = { usuario: "root-export", password: "Secreto-Exportado-2026!" };

let page: Page;

test.describe.configure({ mode: "serial" });

test.beforeAll(async ({ browser }) => {
  page = await browser.newPage();
  await entrarComoAdministrador(page);
});

test.afterAll(async () => {
  await page.close();
});

test("se da de alta un servidor con una credencial", async () => {
  await page.goto("/servidores/nuevo");
  await page.getByLabel("Nombre *", { exact: true }).fill(SERVIDOR);
  await page.getByRole("button", { name: "Guardar" }).click();

  await page.waitForURL(/\/servidores\/\d+/, { timeout: 15_000 });
  const id = page.url().match(/\/servidores\/(\d+)/)![1];

  await page.goto(`/credenciales/nueva?activo=fisico&activo_id=${id}`);
  await page.getByLabel("Usuario de acceso *", { exact: true }).fill(CREDENCIAL.usuario);
  await page.getByLabel("Contraseña *", { exact: true }).fill(CREDENCIAL.password);
  await page.getByRole("button", { name: "Guardar" }).click();

  await expect(page.getByText(CREDENCIAL.usuario).first()).toBeVisible({ timeout: 15_000 });
});

test("exportar en claro exige confirmación y entrega lo que hay", async () => {
  await page.goto("/importar");

  // Sin confirmar no se descarga nada: el botón solo abre el diálogo.
  await page.getByRole("button", { name: /Exportar inventario en claro/ }).click();
  await expect(page.getByRole("alertdialog")).toContainText("sin cifrar");

  const descarga = page.waitForEvent("download", { timeout: 30_000 });
  await page.getByRole("button", { name: "Exportar en claro" }).click();
  const fichero = await descarga;

  expect(fichero.suggestedFilename()).toMatch(/\.csv$/);
  const ruta = await fichero.path();
  const csv = fs.readFileSync(ruta!, "utf-8");

  expect(csv).toContain(SERVIDOR);
  expect(csv).toContain(CREDENCIAL.usuario);
  // El propósito del fichero: las contraseñas van en claro, no cifradas.
  expect(csv).toContain(CREDENCIAL.password);
});

test("la descarga queda registrada en la auditoría", async () => {
  await page.goto("/auditoria");
  // El detalle exacto del asiento (app/exporter.py), no la palabra «export»:
  // esta misma pantalla tiene un botón «Exportar CSV» y la prueba pasaría sola.
  await expect(
    page.getByText("Export en claro del inventario (CSV de migración).").first(),
  ).toBeVisible({ timeout: 15_000 });
});
