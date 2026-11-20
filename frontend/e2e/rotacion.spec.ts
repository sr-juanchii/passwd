import { expect, test, type Page } from "@playwright/test";

import {
  ADMIN,
  alerta,
  asegurarAdministrador,
  cambiarPasswordForzada,
  codigoTotp,
  crearUsuario,
  enrolarTotp,
  entrar,
  entrarComoAdministrador,
  primerFactor,
} from "./ayudantes";

/**
 * Ciclo de gobernanza de rotación, de punta a punta y con dos personas de
 * verdad.
 *
 * Es la funcionalidad principal de la 1.3.0 y la que justifica la versión: una
 * contraseña del inventario ya no se cambia editando la credencial, sino que
 * pasa por SOLICITADA → AUTORIZADA → CERRADA, con motivo obligatorio, regla de
 * dos pares y reautenticación del autorizador con aplicación autenticadora.
 *
 * Las pruebas de Python cubren el servicio; esto cubre lo que ellas no pueden
 * ver: que las dos cuentas, en el navegador, recorren el ciclo hasta el final y
 * que la puerta se cierra cuando quien autoriza es quien pidió.
 */

const SERVIDOR = "srv-rotacion-e2e";
const CREDENCIAL = {
  usuario: "root-rotacion",
  password: "Inicial-Rotacion-2026!",
  nueva: "Aplicada-En-El-Activo-2026!",
};

// Segundo administrador: sin él no hay regla de dos pares que aplicar, y toda
// rotación caería por la vía de emergencia (el arranque avisa de ello).
const SEGUNDO = {
  usuario: "admin-dos-e2e",
  correo: "admin-dos-e2e@ejemplo.local",
  nombre: "Segundo administrador",
  passwordTemporal: "",
  // No puede contener el nombre de usuario: la política lo rechaza.
  password: "Custodia-Del-Par-2026!",
  secreto: "",
};

let page: Page;
let urlCredencial = "";

// Tres minutos por prueba, frente al minuto por omisión. Este recorrido encadena
// varias esperas de ventana TOTP —hasta 30 s cada una, porque el servidor
// rechaza un código ya usado— y el escenario inicial encadena dos: el acceso
// del administrador y el enrolamiento del segundo. No es lentitud del sistema,
// es el reloj de RFC 6238.
test.describe.configure({ mode: "serial", timeout: 180_000 });

/** El distintivo de estado del asiento, que la línea de tiempo repite más abajo. */
function estado(texto: string) {
  return page.locator('[data-slot="badge"]').filter({ hasText: texto }).first();
}

test.beforeAll(async ({ browser }) => {
  page = await browser.newPage();
});

test.afterAll(async () => {
  await page.close();
});

test("se prepara el escenario: una credencial y un segundo administrador", async () => {
  await entrarComoAdministrador(page);

  await page.goto("/servidores/nuevo");
  await page.getByLabel("Nombre *", { exact: true }).fill(SERVIDOR);
  await page.getByRole("button", { name: "Guardar" }).click();
  await page.waitForURL(/\/servidores\/\d+/, { timeout: 15_000 });
  const idActivo = page.url().match(/\/servidores\/(\d+)/)![1];

  await page.goto(`/credenciales/nueva?activo=fisico&activo_id=${idActivo}`);
  await page.getByLabel("Usuario de acceso *", { exact: true }).fill(CREDENCIAL.usuario);
  await page.getByLabel("Contraseña *", { exact: true }).fill(CREDENCIAL.password);
  await page.getByRole("button", { name: "Guardar" }).click();
  await expect(page.getByText(CREDENCIAL.usuario).first()).toBeVisible({ timeout: 15_000 });

  // El id de la credencial no aparece en ninguna URL al crearla: se toma del
  // enlace de edición que la ficha del activo muestra junto a ella.
  const enlace = page.locator('a[href^="/credenciales/"][href$="/editar"]').first();
  await expect(enlace).toBeVisible({ timeout: 15_000 });
  urlCredencial = (await enlace.getAttribute("href"))!;
  expect(urlCredencial).toMatch(/^\/credenciales\/\d+\/editar$/);

  SEGUNDO.passwordTemporal = await crearUsuario(page, {
    usuario: SEGUNDO.usuario,
    correo: SEGUNDO.correo,
    nombre: SEGUNDO.nombre,
    rol: "Administrador",
  });

  // Primer acceso del segundo administrador: contraseña definitiva y TOTP.
  // Una cuenta de administrador no puede elegir el correo como segundo factor.
  await page.context().clearCookies();
  await primerFactor(page, SEGUNDO.usuario, SEGUNDO.passwordTemporal);
  await cambiarPasswordForzada(page, SEGUNDO.passwordTemporal, SEGUNDO.password);
  SEGUNDO.secreto = await enrolarTotp(page);
  await page.getByRole("button", { name: "He guardado mis códigos, continuar" }).click();
  await page.waitForURL((url) => !url.pathname.startsWith("/mfa"), { timeout: 15_000 });
});

test("el formulario de la credencial ya no permite cambiar la contraseña", async () => {
  // Es la rotura de comportamiento de esta versión: el campo desaparece y en su
  // lugar se explica que la contraseña se cambia por rotación.
  await entrarComoAdministrador(page);
  await page.goto(urlCredencial);

  await expect(page.getByText("La contraseña se cambia por rotación")).toBeVisible();
  await expect(page.getByLabel("Contraseña *", { exact: true })).toHaveCount(0);
});

test("solicitar una rotación exige un motivo y deja la solicitud a la espera", async () => {
  await page.goto(urlCredencial);
  await page.getByLabel("Motivo").fill("Rotación de verificación del ciclo de gobernanza 1.3.0.");
  await page.getByRole("button", { name: "Solicitar rotación" }).click();

  await expect(estado("Esperando autorización")).toBeVisible({ timeout: 15_000 });
});

test("quien pidió la rotación no puede autorizarla", async () => {
  // La regla de dos pares, que es la razón de ser de toda la versión. El botón
  // se ve —ambas cuentas tienen el permiso—, pero el servidor lo rechaza.
  // El código se pide ANTES de abrir el diálogo: `codigoTotp` puede esperar
  // hasta 30 s a una ventana nueva, y con la inactividad del banco puesta en 1
  // minuto esa espera a mitad del formulario vencería la sesión.
  const { secreto } = await asegurarAdministrador(page);
  const codigo = await codigoTotp(secreto);

  await page.goto(urlCredencial);
  await page.getByRole("button", { name: "Autorizar" }).click();
  await page.getByLabel("Su contraseña").fill(ADMIN.password);
  await page.getByLabel("Código de su aplicación autenticadora").fill(codigo);
  await page.getByRole("button", { name: "Autorizar", exact: true }).last().click();

  await expect(alerta(page).or(page.getByText(/no puede autorizar|quien la solicitó/i)).first())
    .toBeVisible({ timeout: 15_000 });
  // Y la solicitud sigue esperando: no se coló por ninguna rendija.
  await page.goto(urlCredencial);
  await expect(estado("Esperando autorización")).toBeVisible();
});

test("el segundo administrador autoriza con su propia reautenticación", async () => {
  await page.context().clearCookies();
  await entrar(page, SEGUNDO.usuario, SEGUNDO.password, SEGUNDO.secreto);

  // Igual que arriba: la espera de la ventana TOTP va antes del formulario.
  const codigo = await codigoTotp(SEGUNDO.secreto);

  await page.goto(urlCredencial);
  await page.getByRole("button", { name: "Autorizar" }).click();
  await page.getByLabel("Su contraseña").fill(SEGUNDO.password);
  await page.getByLabel("Código de su aplicación autenticadora").fill(codigo);
  await page.getByRole("button", { name: "Autorizar", exact: true }).last().click();

  await expect(estado("Autorizada, pendiente de aplicar")).toBeVisible({ timeout: 15_000 });
});

test("registrar la contraseña aplicada cierra el ciclo sin marca de emergencia", async () => {
  await page.goto(urlCredencial);
  await page.getByLabel("Contraseña que quedó aplicada en el activo").fill(CREDENCIAL.nueva);
  await page.getByRole("button", { name: "Registrar la rotación" }).click();

  await expect(estado("Cerrada")).toBeVisible({ timeout: 15_000 });

  // Con dos administradores la rotación NO debe caer por la vía excepcional.
  // Si esta marca apareciera, la regla de dos pares no se habría aplicado de
  // verdad y el ciclo entero sería decorativo.
  await expect(page.getByText("Emergencia sin segundo par")).toHaveCount(0);
});

test("la rotación queda en la auditoría", async () => {
  await entrarComoAdministrador(page);
  await page.goto("/auditoria");
  await expect(page.getByText(/rotacion/i).first()).toBeVisible({ timeout: 15_000 });
});
