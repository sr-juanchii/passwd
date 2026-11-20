import { expect, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

import { ADMIN, BUZON } from "../playwright.config";
import { generarTotp } from "./totp";

export { ADMIN };

const PASO_TOTP = 30;
let ultimoPaso = -1;

/**
 * Código TOTP válido de una ventana que esta tanda no haya usado ya.
 *
 * El backend rechaza un código cuyo contador no sea mayor que el último
 * aceptado (RFC 6238 §5.2, docs/resistencia-bypass-mfa.md §3). Dos pruebas
 * seguidas dentro del mismo paso de 30 s recibirían «Código incorrecto.» —y
 * con razón: es el mismo código. Por eso se espera al paso siguiente en vez de
 * bajarle el listón al servidor.
 *
 * Para comprobar a propósito el rechazo del reuso, se guarda un código y se
 * envía dos veces, sin volver a pedirlo aquí.
 */
export async function codigoTotp(secreto: string): Promise<string> {
  const paso = () => Math.floor(Date.now() / 1000 / PASO_TOTP);
  while (paso() <= ultimoPaso) await new Promise((r) => setTimeout(r, 250));
  ultimoPaso = paso();
  return generarTotp(secreto);
}

/**
 * Rellena un código en el campo de seis casillas (`OtpInput`).
 *
 * Cada dígito es un `<input>` propio con `aria-label="Dígito N"`; escribir en
 * ellos uno a uno es lo que hace un usuario de verdad, y de paso ejercita el
 * auto-avance entre casillas.
 */
export async function rellenarCodigo(page: Page, codigo: string) {
  const digitos = codigo.replace(/\D/g, "");
  for (let i = 0; i < digitos.length; i += 1) {
    await page.getByLabel(`Dígito ${i + 1}`, { exact: true }).fill(digitos[i]);
  }
}

interface Mensaje {
  recibido_en: number;
  de: string;
  para: string[];
  asunto: string;
  cuerpo: string;
}

function mensajes(): Mensaje[] {
  if (!fs.existsSync(BUZON)) return [];
  return fs
    .readdirSync(BUZON)
    .filter((f) => f.endsWith(".json"))
    .map((f) => JSON.parse(fs.readFileSync(path.join(BUZON, f), "utf-8")) as Mensaje)
    .sort((a, b) => a.recibido_en - b.recibido_en);
}

/** Vacía el buzón, para que una prueba no lea el correo de la anterior. */
export function vaciarBuzon(): void {
  if (!fs.existsSync(BUZON)) return;
  for (const f of fs.readdirSync(BUZON)) fs.unlinkSync(path.join(BUZON, f));
}

/**
 * Espera a que llegue un correo al destinatario y devuelve el último.
 *
 * El envío es asíncrono respecto a la respuesta HTTP, así que se sondea en vez
 * de leer una sola vez: sin esto la prueba sería intermitente, que es peor que
 * no tenerla.
 */
export async function esperarCorreo(para: string, msEspera = 15_000): Promise<Mensaje> {
  const limite = Date.now() + msEspera;
  while (Date.now() < limite) {
    const recibidos = mensajes().filter((m) => m.para.includes(para));
    if (recibidos.length > 0) return recibidos[recibidos.length - 1];
    await new Promise((r) => setTimeout(r, 200));
  }
  throw new Error(`No llegó ningún correo para ${para} en ${msEspera} ms`);
}

/** Extrae el código de un solo uso del cuerpo del correo. */
export function codigoDelCorreo(cuerpo: string): string {
  const encontrado = cuerpo.match(/CÓDIGO:\s*(\d{6,8})/);
  if (!encontrado) throw new Error(`El correo no trae código:\n${cuerpo}`);
  return encontrado[1];
}

/**
 * Las alertas de la aplicación (el componente `Alert`).
 *
 * No vale `getByRole("alert")`: Next monta un `<div role="alert">` vacío como
 * anunciador de rutas para lectores de pantalla, y la búsqueda devolvería dos
 * elementos.
 */
export function alerta(page: Page) {
  return page.locator('[data-slot="alert"]');
}

/** Primer factor: usuario y contraseña. */
export async function primerFactor(page: Page, usuario: string, password: string) {
  await page.goto("/login");
  await page.getByLabel("Usuario", { exact: true }).fill(usuario);
  await page.getByLabel("Contraseña", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Entrar" }).click();
}

/** El secreto TOTP del bloque «Entrada manual» de la pantalla de alta. */
export async function secretoDeLaPantalla(page: Page): Promise<string> {
  const bloque = page.getByText("Entrada manual").locator("xpath=following-sibling::div[1]");
  await expect(bloque).toBeVisible({ timeout: 15_000 });
  const secreto = (await bloque.innerText()).trim();
  if (!/^[A-Z2-7]{16,64}$/.test(secreto)) {
    throw new Error(`El bloque de entrada manual no contiene un secreto base32: ${secreto}`);
  }
  return secreto;
}

/**
 * Primer acceso hasta la pantalla de alta del segundo factor: entra con la
 * contraseña temporal y la cambia por la definitiva.
 */
export async function cambiarPasswordInicial(page: Page) {
  await primerFactor(page, ADMIN.usuario, ADMIN.passwordInicial);

  await page.waitForURL(/\/password\/cambiar/);
  await page.getByLabel("Contraseña actual").fill(ADMIN.passwordInicial);
  // El asterisco forma parte del nombre accesible: `CampoPassword` añade
  // `<span> *</span>` dentro del <label> cuando el campo es obligatorio.
  await page.getByLabel("Nueva contraseña *", { exact: true }).fill(ADMIN.password);
  await page.getByLabel("Confirmar nueva contraseña").fill(ADMIN.password);
  await page.getByRole("button", { name: "Guardar" }).click();
  await page.waitForURL(/\/mfa\/configurar/);
}

/**
 * Enrola el segundo factor con una aplicación autenticadora y devuelve el
 * secreto, que las pruebas necesitan para volver a entrar.
 *
 * Deja la pantalla de códigos de recuperación ya confirmada.
 */
export async function enrolarTotp(page: Page): Promise<string> {
  await page.waitForURL(/\/mfa\/configurar/);
  await page.getByRole("button", { name: /Aplicación autenticadora/ }).click();
  const secreto = await secretoDeLaPantalla(page);
  await rellenarCodigo(page, await codigoTotp(secreto));
  await page.getByRole("button", { name: "Confirmar y activar" }).click();

  // Tras enrolar se muestran los códigos de recuperación una única vez.
  await expect(page.getByRole("heading", { name: "Códigos de recuperación" })).toBeVisible({
    timeout: 15_000,
  });
  return secreto;
}

/** Los diez códigos de recuperación que la pantalla muestra una sola vez. */
export async function codigosDeRecuperacion(page: Page): Promise<string[]> {
  const texto = await page.locator("body").innerText();
  return [...texto.matchAll(/\b([A-Za-z0-9]{5}-[A-Za-z0-9]{5})\b/g)].map((m) => m[1]);
}

/**
 * Completa el primer acceso del administrador inicial: contraseña temporal →
 * contraseña definitiva → enrolamiento del segundo factor con TOTP.
 *
 * Devuelve el secreto y los códigos de recuperación, que solo se muestran en
 * esta pantalla y que las pruebas siguientes necesitan.
 */
export async function arrancarAdministrador(page: Page): Promise<{ secreto: string; codigos: string[] }> {
  await cambiarPasswordInicial(page);
  const secreto = await enrolarTotp(page);
  const codigos = await codigosDeRecuperacion(page);
  await page.getByRole("button", { name: "He guardado mis códigos, continuar" }).click();
  await page.waitForURL((url) => !url.pathname.startsWith("/mfa"), { timeout: 15_000 });
  return { secreto, codigos };
}

/** Acceso completo de una cuenta que ya tiene TOTP configurado. */
export async function entrar(page: Page, usuario: string, password: string, secreto: string) {
  await primerFactor(page, usuario, password);
  await page.waitForURL(/\/mfa\/verificar/);
  await rellenarCodigo(page, await codigoTotp(secreto));
  await page.getByRole("button", { name: "Verificar" }).click();
  await page.waitForURL((url) => !url.pathname.startsWith("/mfa"), { timeout: 15_000 });
}

// ── Administrador compartido entre ficheros de prueba ────────────────────────
//
// El primer acceso solo ocurre una vez por base de datos, y las pruebas de
// otros ficheros necesitan el secreto TOTP que allí se enroló. Se guarda junto
// al buzón, en el mismo directorio efímero que se borra entre tandas.

const FICHERO_ADMIN = path.join(path.dirname(BUZON), "admin.json");

interface DatosAdmin {
  secreto: string;
  codigos: string[];
}

export function guardarAdministrador(datos: DatosAdmin): void {
  fs.mkdirSync(path.dirname(FICHERO_ADMIN), { recursive: true });
  fs.writeFileSync(FICHERO_ADMIN, JSON.stringify(datos), "utf-8");
}

/** Enrola al administrador inicial si aún no lo está, y devuelve sus datos. */
export async function asegurarAdministrador(page: Page): Promise<DatosAdmin> {
  if (fs.existsSync(FICHERO_ADMIN)) {
    return JSON.parse(fs.readFileSync(FICHERO_ADMIN, "utf-8")) as DatosAdmin;
  }
  const datos = await arrancarAdministrador(page);
  guardarAdministrador(datos);
  return datos;
}

/** Deja una sesión de administrador abierta en la página. */
export async function entrarComoAdministrador(page: Page): Promise<void> {
  const { secreto } = await asegurarAdministrador(page);
  await page.context().clearCookies();
  await entrar(page, ADMIN.usuario, ADMIN.password, secreto);
}

/**
 * Crea una cuenta desde la pantalla de administración y devuelve la contraseña
 * temporal que se muestra una sola vez.
 */
export async function crearUsuario(
  page: Page,
  datos: { usuario: string; correo: string; nombre: string; rol: string },
): Promise<string> {
  await page.goto("/usuarios/nuevo");
  await page.getByLabel("Usuario *", { exact: true }).fill(datos.usuario);
  await page.getByLabel("Email *", { exact: true }).fill(datos.correo);
  await page.getByLabel("Nombre completo *", { exact: true }).fill(datos.nombre);
  await page.getByLabel("Rol").click();
  await page.getByRole("option", { name: datos.rol, exact: true }).click();
  await page.getByRole("button", { name: "Crear usuario" }).click();

  const codigo = page.locator("code").first();
  await expect(codigo).toBeVisible({ timeout: 15_000 });
  const temporal = (await codigo.innerText()).trim();
  if (!temporal) throw new Error("La pantalla no mostró la contraseña temporal");
  return temporal;
}

/** Cambia la contraseña forzada del primer acceso de una cuenta cualquiera. */
export async function cambiarPasswordForzada(page: Page, actual: string, nueva: string) {
  await page.waitForURL(/\/password\/cambiar/);
  await page.getByLabel("Contraseña actual").fill(actual);
  await page.getByLabel("Nueva contraseña *", { exact: true }).fill(nueva);
  await page.getByLabel("Confirmar nueva contraseña").fill(nueva);
  await page.getByRole("button", { name: "Guardar" }).click();
}
