import { expect, test, type Page } from "@playwright/test";

import {
  alerta,
  cambiarPasswordForzada,
  codigoDelCorreo,
  crearUsuario,
  entrarComoAdministrador,
  esperarCorreo,
  primerFactor,
  vaciarBuzon,
} from "./ayudantes";

/**
 * Segundo factor por correo, de punta a punta y con correo de verdad.
 *
 * El otro método (aplicación autenticadora) lo cubre acceso.spec.ts. C1 exige
 * los dos, y este es el que más piezas atraviesa: el envío SMTP, la vigencia
 * del código y el límite de solicitudes.
 *
 * Se usa una cuenta de operador porque una de administrador no puede elegir
 * correo — lo comprueba acceso.spec.ts.
 *
 * El envío está limitado a 3 por cuenta cada 15 minutos
 * (app/servicios/autenticacion.py). Estas pruebas gastan 2 a propósito: el
 * presupuesto es del sistema y no se toca para que quepan más pruebas.
 */

const OPERADOR = {
  usuario: "operador-e2e",
  correo: "operador-e2e@ejemplo.local",
  nombre: "Operador de pruebas",
  passwordTemporal: "",
  // No puede contener el nombre de usuario: la política lo rechaza, con razón.
  password: "Custodia-Segura-2026!",
};

// Código de un solo uso con el que se enroló la cuenta; la prueba del reuso lo
// necesita y así no gasta un envío más.
let codigoDeEnrolamiento = "";

// Una sola pestaña para todo el fichero: es un flujo encadenado y cada prueba
// de Playwright estrenaría un contexto —y perdería la sesión— por omisión.
let page: Page;

test.describe.configure({ mode: "serial" });

test.beforeAll(async ({ browser }) => {
  page = await browser.newPage();
});

test.afterAll(async () => {
  await page.close();
});

test("un administrador crea la cuenta y recibe su contraseña temporal", async () => {
  await entrarComoAdministrador(page);
  OPERADOR.passwordTemporal = await crearUsuario(page, {
    usuario: OPERADOR.usuario,
    correo: OPERADOR.correo,
    nombre: OPERADOR.nombre,
    rol: "Operador",
  });
  expect(OPERADOR.passwordTemporal.length).toBeGreaterThanOrEqual(12);
});

test("el operador enrola el segundo factor con un código recibido por correo", async () => {
  await page.context().clearCookies();
  vaciarBuzon();

  await primerFactor(page, OPERADOR.usuario, OPERADOR.passwordTemporal);
  await cambiarPasswordForzada(page, OPERADOR.passwordTemporal, OPERADOR.password);

  await page.waitForURL(/\/mfa\/configurar/);
  await page.getByRole("button", { name: /Código por correo/ }).click();
  await page.getByRole("button", { name: "Enviar código a mi correo" }).click();

  const correo = await esperarCorreo(OPERADOR.correo);
  codigoDeEnrolamiento = codigoDelCorreo(correo.cuerpo);
  await page.getByLabel("Código recibido por correo").fill(codigoDeEnrolamiento);
  await page.getByRole("button", { name: "Confirmar y activar" }).click();

  await expect(page.getByRole("heading", { name: "Códigos de recuperación" })).toBeVisible({
    timeout: 15_000,
  });
  await page.getByRole("button", { name: "He guardado mis códigos, continuar" }).click();
  await page.waitForURL((url) => !url.pathname.startsWith("/mfa"), { timeout: 15_000 });
});

test("un código ya usado no sirve, y el recién recibido abre la sesión", async () => {
  await page.context().clearCookies();
  vaciarBuzon();

  // Con el correo como método principal la pantalla pide el código al
  // montarse: el usuario no tiene que solicitarlo.
  await primerFactor(page, OPERADOR.usuario, OPERADOR.password);
  await page.waitForURL(/\/mfa\/verificar/);
  const correo = await esperarCorreo(OPERADOR.correo);

  await page.getByLabel("Código recibido por correo").fill(codigoDeEnrolamiento);
  await page.getByRole("button", { name: "Verificar" }).click();
  await expect(alerta(page)).toBeVisible();
  await expect(page).toHaveURL(/\/mfa\/verificar/);

  await page.getByLabel("Código recibido por correo").fill(codigoDelCorreo(correo.cuerpo));
  await page.getByRole("button", { name: "Verificar" }).click();
  await page.waitForURL((url) => !url.pathname.startsWith("/mfa"), { timeout: 15_000 });
  await expect(page.getByRole("button", { name: /Buscar activos/ })).toBeVisible();
});

test("el operador no ve la administración", async () => {
  // RBAC visto desde el navegador: la navegación no ofrece lo que el rol no
  // puede usar, y escribir la dirección a mano tampoco lo abre. Se aprovecha la
  // sesión abierta en el paso anterior, así que no gasta otro código.
  await page.goto("/");
  await expect(page.getByRole("link", { name: "Inventario" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Usuarios" })).toHaveCount(0);

  await page.goto("/usuarios");
  await expect(
    page.getByText(/no tiene permisos|acceso restringido|no autorizado/i).first(),
  ).toBeVisible({ timeout: 15_000 });
});

test("el administrador puede restablecer el segundo factor de la cuenta", async () => {
  await entrarComoAdministrador(page);
  await page.goto("/usuarios");

  const fila = page.getByRole("row", { name: new RegExp(OPERADOR.usuario) });
  await fila.getByRole("button", { name: "Acciones" }).click();
  await page.getByRole("menuitem", { name: /MFA/i }).click();
  await page.getByRole("button", { name: /Restablecer/ }).last().click();

  // Tras el restablecimiento la cuenta vuelve a la pantalla de alta.
  await page.context().clearCookies();
  await primerFactor(page, OPERADOR.usuario, OPERADOR.password);
  await page.waitForURL(/\/mfa\/configurar/, { timeout: 15_000 });
});
