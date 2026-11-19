import { expect, test } from "@playwright/test";

import {
  ADMIN,
  alerta,
  cambiarPasswordInicial,
  codigoTotp,
  codigosDeRecuperacion,
  enrolarTotp,
  guardarAdministrador,
  entrar,
  primerFactor,
  rellenarCodigo,
} from "./ayudantes";

/**
 * Flujo de acceso completo contra el sistema real: backend, frontend y correo.
 *
 * Estas pruebas valen por lo que las de Python no pueden ver: que la interfaz
 * que usa una persona de verdad —con su hidratación, su guard de rutas en el
 * borde y sus cookies de primera parte— lleva al mismo sitio que la API.
 *
 * El orden importa: la primera prueba deja al administrador enrolado y las
 * siguientes lo reutilizan. Se ejecutan con un solo trabajador (ver
 * playwright.config.ts).
 */

// Secreto TOTP y códigos de recuperación del administrador, compartidos entre
// las pruebas de este archivo.
let secretoAdmin = "";
let codigosAdmin: string[] = [];

test.describe.configure({ mode: "serial" });

test("el primer acceso obliga a cambiar la contraseña y a enrolar el segundo factor", async ({ page }) => {
  await cambiarPasswordInicial(page);

  // El correo depende de un buzón que se puede perder o secuestrar; para el rol
  // que puede revelar cualquier credencial se exige la aplicación autenticadora.
  // La opción se ve —no se esconde—, pero deshabilitada y con el motivo escrito.
  const porCorreo = page.getByRole("button", { name: /Código por correo/ });
  await expect(porCorreo).toBeDisabled();
  await expect(porCorreo).toContainText("aplicación autenticadora");

  secretoAdmin = await enrolarTotp(page);
  expect(secretoAdmin).toMatch(/^[A-Z2-7]{16,}$/);

  // Los códigos de recuperación se muestran UNA vez, al enrolar.
  codigosAdmin = await codigosDeRecuperacion(page);
  expect(codigosAdmin.length).toBeGreaterThanOrEqual(8);

  await page.getByRole("button", { name: "He guardado mis códigos, continuar" }).click();
  await page.waitForURL((url) => !url.pathname.startsWith("/mfa"), { timeout: 15_000 });

  // Los demás ficheros de prueba reutilizan este administrador.
  guardarAdministrador({ secreto: secretoAdmin, codigos: codigosAdmin });
});

test("la contraseña temporal ya no sirve después de cambiarla", async ({ page }) => {
  await primerFactor(page, ADMIN.usuario, ADMIN.passwordInicial);
  await expect(alerta(page)).toContainText("Credenciales inválidas.");
  await expect(page).toHaveURL(/\/login/);
});

test("una contraseña incorrecta no distingue de un usuario inexistente", async ({ page }) => {
  await primerFactor(page, ADMIN.usuario, "Clave-Que-No-Es-2026!");
  const conCuenta = await alerta(page).innerText();

  await primerFactor(page, "no-existe-esta-cuenta", "Clave-Que-No-Es-2026!");
  const sinCuenta = await alerta(page).innerText();

  expect(conCuenta).toBe(sinCuenta);
});

test("sin el segundo factor no se entra, aunque la contraseña sea correcta", async ({ page }) => {
  await primerFactor(page, ADMIN.usuario, ADMIN.password);
  await page.waitForURL(/\/mfa\/verificar/);

  // Saltarse la pantalla navegando directamente no abre la sesión.
  await page.goto("/");
  await expect(page).toHaveURL(/\/mfa\/verificar|\/login/);
});

test("un código de segundo factor incorrecto se rechaza", async ({ page }) => {
  await primerFactor(page, ADMIN.usuario, ADMIN.password);
  await page.waitForURL(/\/mfa\/verificar/);
  await rellenarCodigo(page, "000000");
  await page.getByRole("button", { name: "Verificar" }).click();
  await expect(alerta(page)).toBeVisible();
  await expect(page).toHaveURL(/\/mfa\/verificar/);
});

test("el acceso completo con TOTP llega a la aplicación", async ({ page }) => {
  await entrar(page, ADMIN.usuario, ADMIN.password, secretoAdmin);
  await expect(page).toHaveURL(/\/($|\?)/);
  // Shell de la aplicación: barra lateral y buscador global.
  await expect(page.getByRole("link", { name: "Inventario" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Buscar activos/ })).toBeVisible();
});

test("el mismo código TOTP no se puede reutilizar", async ({ page }) => {
  // RFC 6238 §5.2 y docs/resistencia-bypass-mfa.md §3: un código ya usado se
  // rechaza aunque siga dentro de su ventana de 30 segundos.
  const codigo = await codigoTotp(secretoAdmin);

  await primerFactor(page, ADMIN.usuario, ADMIN.password);
  await page.waitForURL(/\/mfa\/verificar/);
  await rellenarCodigo(page, codigo);
  await page.getByRole("button", { name: "Verificar" }).click();
  await page.waitForURL((url) => !url.pathname.startsWith("/mfa"), { timeout: 15_000 });

  await page.context().clearCookies();
  await primerFactor(page, ADMIN.usuario, ADMIN.password);
  await page.waitForURL(/\/mfa\/verificar/);
  await rellenarCodigo(page, codigo);
  await page.getByRole("button", { name: "Verificar" }).click();
  await expect(alerta(page)).toBeVisible();
});

test("un código de recuperación entra una sola vez", async ({ page }) => {
  const codigo = codigosAdmin[codigosAdmin.length - 1];

  await primerFactor(page, ADMIN.usuario, ADMIN.password);
  await page.waitForURL(/\/mfa\/verificar/);
  await page.getByRole("button", { name: /código de recuperación/i }).click();
  await page.getByPlaceholder("XXXXX-XXXXX").fill(codigo);
  await page.getByRole("button", { name: "Verificar" }).click();
  await page.waitForURL((url) => !url.pathname.startsWith("/mfa"), { timeout: 15_000 });

  // Ya consumido: el mismo código no vuelve a abrir sesión.
  await page.context().clearCookies();
  await primerFactor(page, ADMIN.usuario, ADMIN.password);
  await page.waitForURL(/\/mfa\/verificar/);
  await page.getByRole("button", { name: /código de recuperación/i }).click();
  await page.getByPlaceholder("XXXXX-XXXXX").fill(codigo);
  await page.getByRole("button", { name: "Verificar" }).click();
  await expect(alerta(page)).toBeVisible();
});
