import { generateKeyPairSync } from "node:crypto";
import { expect, test, type Page } from "@playwright/test";

import { PUERTO_BACKEND } from "../playwright.config";
import { ADMIN, asegurarAdministrador, codigoTotp, entrarComoAdministrador } from "./ayudantes";

/**
 * Agentes de rotación en el panel (v1.4.0).
 *
 * Lo que las pruebas de Python no ven: que desde la ficha de un servidor se da
 * de alta un agente con reautenticación, que su token de instalación se ve UNA
 * sola vez, y que la insignia sigue al agente real —pendiente, conectado,
 * revocado—. El agente lo pone la propia prueba: se enrola contra
 * /api/agent/enrolar con una clave X25519 de verdad, como hará el binario.
 */

const SERVIDOR = "srv-agente-e2e";
let page: Page;
let urlServidor = "";
let token = "";

test.describe.configure({ mode: "serial", timeout: 180_000 });

function badge(texto: string) {
  return page.locator('[data-slot="badge"]').filter({ hasText: texto }).first();
}

test.beforeAll(async ({ browser }) => {
  page = await browser.newPage();
});

test.afterAll(async () => {
  await page.close();
});

test("la ficha del servidor muestra que no tiene agente", async () => {
  await entrarComoAdministrador(page);
  await page.goto("/servidores/nuevo");
  await page.getByLabel("Nombre *", { exact: true }).fill(SERVIDOR);
  await page.getByRole("button", { name: "Guardar" }).click();
  await page.waitForURL(/\/servidores\/\d+/, { timeout: 15_000 });
  urlServidor = new URL(page.url()).pathname;

  await expect(page.getByText("Agente de rotación")).toBeVisible();
  await expect(badge("Sin agente")).toBeVisible();
});

test("dar de alta un agente exige reautenticación y enseña el token una sola vez", async () => {
  // El código se pide ANTES de abrir el diálogo: esperar una ventana TOTP nueva
  // con el formulario abierto vencería la sesión de un minuto del banco.
  const { secreto } = await asegurarAdministrador(page);
  const codigo = await codigoTotp(secreto);

  await page.goto(urlServidor);
  await page.getByRole("button", { name: "Dar de alta un agente" }).click();
  await page.getByLabel("Su contraseña").fill(ADMIN.password);
  await page.getByLabel("Código de su aplicación autenticadora").fill(codigo);
  await page.getByRole("button", { name: "Dar de alta", exact: true }).click();

  const caja = page.getByTestId("token-instalacion");
  await expect(caja).toBeVisible({ timeout: 15_000 });
  token = (await caja.innerText()).trim();
  expect(token.length).toBeGreaterThan(20);
  await expect(page.getByText("una sola vez")).toBeVisible();
  // La orden de instalación no lleva el token: se pega por la entrada estándar.
  await expect(page.getByText("--token -")).toBeVisible();

  await page.reload();
  await expect(page.getByTestId("token-instalacion")).toHaveCount(0);
  await expect(badge("Pendiente de instalar")).toBeVisible({ timeout: 15_000 });
});

test("cuando el agente se enrola, la insignia pasa a conectado", async ({ request }) => {
  const { publicKey } = generateKeyPairSync("x25519");
  const spki = publicKey.export({ format: "der", type: "spki" });
  const clavePublica = Buffer.from(spki.subarray(spki.length - 32)).toString("base64");

  const respuesta = await request.post(`http://127.0.0.1:${PUERTO_BACKEND}/api/agent/enrolar`, {
    data: { token_enrolamiento: token, clave_publica: clavePublica, nombre_host: SERVIDOR, version: "1.4.0" },
  });
  expect(respuesta.status()).toBe(200);
  // Y el mismo token ya no sirve.
  const segunda = await request.post(`http://127.0.0.1:${PUERTO_BACKEND}/api/agent/enrolar`, {
    data: { token_enrolamiento: token, clave_publica: clavePublica },
  });
  expect(segunda.status()).toBe(401);

  await entrarComoAdministrador(page);
  await page.goto(urlServidor);
  await expect(badge("Conectado")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText(SERVIDOR).last()).toBeVisible();
});

test("la página de agentes lista el parque con su estado", async () => {
  await page.goto("/agentes");
  const fila = page.getByRole("row").filter({ hasText: SERVIDOR });
  await expect(fila).toBeVisible({ timeout: 15_000 });
  await expect(fila.locator('[data-slot="badge"]').filter({ hasText: "Conectado" })).toBeVisible();

  // Y las métricas lo cuentan.
  await page.goto("/metricas");
  await expect(page.getByText("Agentes de rotación")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("Conectados:")).toBeVisible();
});

test("revocar devuelve el activo a «sin agente»", async () => {
  await page.goto(urlServidor);
  await page.getByRole("button", { name: "Revocar" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Revocar" }).click();
  await expect(badge("Sin agente")).toBeVisible({ timeout: 15_000 });
});
