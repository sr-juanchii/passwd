import { expect, test, type Page } from "@playwright/test";

import { entrarComoAdministrador } from "./ayudantes";

/**
 * Configuración del sistema desde el navegador.
 *
 * Lo que importa no es que el formulario guarde, sino que el valor guardado
 * MANDA de verdad en el resto de la aplicación y sin reiniciar: se cambia la
 * longitud mínima de contraseña y se comprueba en otra pantalla. Y que el
 * cambio queda en la bitácora, que es el control que hace auditable un ajuste.
 */

const AJUSTE = "Longitud mínima de contraseña (caracteres)";

// El botón de guardar se repite arriba y abajo de la página, a propósito: con
// el formulario largo, obligar a subir sería peor.


let page: Page;

test.describe.configure({ mode: "serial" });

test.beforeAll(async ({ browser }) => {
  page = await browser.newPage();
  await entrarComoAdministrador(page);
});

test.afterAll(async () => {
  await page.close();
});

test("un ajuste guardado se aplica al instante en otra pantalla", async () => {
  await page.goto("/configuracion");
  const campo = page.getByLabel(AJUSTE, { exact: true });
  await expect(campo).toHaveValue("12");

  await campo.fill("16");
  await page.getByRole("button", { name: /Guardar 1 cambio/ }).first().click();
  await expect(page.getByRole("button", { name: "Sin cambios" }).first()).toBeVisible({ timeout: 15_000 });

  // Otra pantalla, misma verdad: no hay copia del valor en el cliente.
  await page.goto("/password/cambiar");
  await expect(page.getByText("Mínimo 16 caracteres", { exact: false })).toBeVisible();
});

test("el cambio queda registrado en la auditoría", async () => {
  await page.goto("/auditoria");
  await expect(page.getByText(/password_min_length/).first()).toBeVisible({ timeout: 15_000 });
});

test("el valor vuelve a su sitio y el resto de pruebas no lo nota", async () => {
  await page.goto("/configuracion");
  const campo = page.getByLabel(AJUSTE, { exact: true });
  await campo.fill("12");
  await page.getByRole("button", { name: /Guardar 1 cambio/ }).first().click();
  await expect(page.getByRole("button", { name: "Sin cambios" }).first()).toBeVisible({ timeout: 15_000 });

  await page.goto("/password/cambiar");
  await expect(page.getByText("Mínimo 12 caracteres", { exact: false })).toBeVisible();
});
