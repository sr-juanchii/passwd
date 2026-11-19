import { expect, test, type Page } from "@playwright/test";

import { entrarComoAdministrador } from "./ayudantes";

/**
 * Expiración de sesión por inactividad, con el reloj de verdad.
 *
 * El banco de pruebas arranca el backend con
 * `PASSWD_SESSION_IDLE_MINUTES=1` (ver playwright.config.ts), así que la
 * ventana es de 60 s y el aviso sale a la mitad —`antelacionAvisoMs`—, es
 * decir 30 s después de la última actividad. Con los 15 minutos de producción
 * esto no se podría probar.
 *
 * `expiracion.test.ts` ya cubre la aritmética de los plazos con vitest. Lo que
 * aquí se comprueba es lo que aquella no puede ver: que el servidor cierra de
 * verdad, que extender sirve y que al volver se vuelve a la página de antes.
 */

let page: Page;

test.describe.configure({ mode: "serial" });

test.beforeAll(async ({ browser }) => {
  page = await browser.newPage();
});

test.afterAll(async () => {
  await page.close();
});

const AVISO = "Su sesión está a punto de cerrarse";

test("el aviso sale antes de vencer y «Extender sesión» lo retira", async () => {
  test.setTimeout(180_000);

  await entrarComoAdministrador(page);
  await page.goto("/dispositivos");

  const aviso = page.getByRole("alertdialog").filter({ hasText: AVISO });
  await expect(aviso).toBeVisible({ timeout: 60_000 });

  await page.getByRole("button", { name: "Extender sesión" }).click();
  await expect(aviso).toBeHidden({ timeout: 15_000 });

  // Extender renueva de verdad: se sigue en la misma página, sin reingreso.
  await expect(page).toHaveURL(/\/dispositivos/);
  await expect(page.getByRole("button", { name: /Buscar activos/ })).toBeVisible();
});

test("sin actividad la sesión se cierra y el login dice por qué", async () => {
  test.setTimeout(180_000);

  // Se deja correr el plazo entero sin tocar nada: ni aviso ni extensión.
  await expect(page).toHaveURL(/\/login\?/, { timeout: 150_000 });
  await expect(page).toHaveURL(/motivo=expirada/);
  // Y con el destino al que volver, para no perder dónde estaba.
  await expect(page).toHaveURL(/next=%2Fdispositivos/);

  await expect(
    page.getByText("Por seguridad, su sesión se cerró automáticamente.", { exact: false }),
  ).toBeVisible();
});

test("una sesión cerrada no vale para la API, aunque la pestaña siga abierta", async () => {
  // La cookie sigue en el navegador; lo que ya no vale es la sesión.
  const respuesta = await page.request.get("/api/web/session");
  expect(respuesta.status()).toBe(200);
  const cuerpo = await respuesta.json();
  expect(cuerpo.authenticated).toBe(false);
});
