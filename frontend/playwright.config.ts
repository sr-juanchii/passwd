import { defineConfig, devices } from "@playwright/test";
import path from "node:path";

// Puertos propios del banco de pruebas: no chocan con un backend (8000) ni un
// frontend (3000) que alguien tenga levantados mientras desarrolla.
const PUERTO_BACKEND = 8111;
const PUERTO_FRONTEND = 3111;
const PUERTO_SMTP = 8125;

const RAIZ = path.resolve(__dirname, "..");
const DATOS = path.join(RAIZ, ".e2e", "datos");
export const BUZON = path.join(RAIZ, ".e2e", "buzon");

// Credenciales del administrador inicial que el backend crea al arrancar con
// la base vacía. Son de banco de pruebas y viven en un directorio efímero.
export const ADMIN = {
  usuario: "admin",
  correo: "admin@ejemplo.local",
  passwordInicial: "Arranque-E2E-2026!",
  password: "Definitiva-E2E-2026!",
};

const entornoBackend = {
  PASSWD_DATA_DIR: DATOS,
  PASSWD_COOKIE_SECURE: "false",
  PASSWD_ADMIN_USERNAME: ADMIN.usuario,
  PASSWD_ADMIN_EMAIL: ADMIN.correo,
  PASSWD_ADMIN_PASSWORD: ADMIN.passwordInicial,
  // Correo dirigido al buzón local: la aplicación envía como enviaría a
  // cualquier servidor, sin saber que está en pruebas.
  PASSWD_SMTP_ENABLED: "true",
  PASSWD_SMTP_HOST: "127.0.0.1",
  PASSWD_SMTP_PORT: String(PUERTO_SMTP),
  PASSWD_SMTP_SECURITY: "ninguna",
  PASSWD_SMTP_FROM: "passwd@ejemplo.local",
  PASSWD_NOTIFY_ENABLED: "true",
  PASSWD_NOTIFY_TO: "seguridad@ejemplo.local",
  // Sesión corta para poder comprobar la expiración sin esperar 15 minutos.
  PASSWD_SESSION_IDLE_MINUTES: "1",
  // El límite de accesos por IP (15 cada 5 minutos) protege contra la prueba
  // sistemática de contraseñas desde un origen. La tanda entera entra desde
  // 127.0.0.1 y abre más de veinte sesiones legítimas en pocos minutos, así
  // que lo agotaría y las pruebas se colgarían en el login. Se sube el techo
  // **solo en el banco de pruebas**: ninguna prueba de navegador ejercita ese
  // control, que está cubierto en tests/test_fase3.py y tests/test_mfa_metodo.py.
  PASSWD_LOGIN_RATE_LIMIT: "200",
};

export default defineConfig({
  testDir: "./e2e",
  // Un solo trabajador: todas las pruebas comparten una base de datos y un
  // buzón. Paralelizar exigiría una instancia por trabajador, que es mucho
  // aparato para cinco flujos.
  workers: 1,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  // Sin reintentos, ni en CI. Las pruebas comparten una base de datos y la van
  // modificando (crean cuentas, consumen códigos de un solo uso, gastan el
  // límite de envíos): repetir una tanda desde un estado ya alterado daría
  // verde o rojo por motivos que no son el cambio bajo prueba.
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: process.env.CI ? [["github"], ["list"]] : [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${PUERTO_FRONTEND}`,
    // Una acción sobre un selector que no existe debe fallar PRONTO. Sin esto
    // heredaría el minuto del timeout de prueba y, con la ventana de
    // inactividad puesta en 1 minuto, la sesión vencería durante la espera: la
    // aplicación saltaría al login y la acción acabaría ejecutándose sobre los
    // campos de ESA pantalla. El fallo resultante no se parece en nada a su
    // causa.
    actionTimeout: 10_000,
    trace: "retain-on-failure",
    // Capturas y vídeo solo del fallo: una traza por prueba cuesta un tercio
    // del tiempo de CPU de la tanda.
    screenshot: "only-on-failure",
    video: "off",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `python scripts/buzon_pruebas.py --puerto ${PUERTO_SMTP} --directorio ${BUZON}`,
      cwd: RAIZ,
      port: PUERTO_SMTP,
      reuseExistingServer: !process.env.CI,
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      command: `python -m uvicorn app.main:app --host 127.0.0.1 --port ${PUERTO_BACKEND}`,
      cwd: RAIZ,
      url: `http://127.0.0.1:${PUERTO_BACKEND}/healthz`,
      env: entornoBackend,
      reuseExistingServer: !process.env.CI,
      stdout: "pipe",
      stderr: "pipe",
      timeout: 60_000,
    },
    {
      // El build de producción `standalone`, que es lo que arranca el
      // contenedor. e2e/servidor.mjs explica por qué no vale `next dev` ni
      // `next start`.
      command: "node e2e/servidor.mjs",
      cwd: __dirname,
      url: `http://127.0.0.1:${PUERTO_FRONTEND}/login`,
      env: {
        PORT: String(PUERTO_FRONTEND),
        // Debe estar definida ya en el build: los rewrites se resuelven ahí.
        PASSWD_API_BASE: `http://127.0.0.1:${PUERTO_BACKEND}`,
      },
      reuseExistingServer: !process.env.CI,
      stdout: "pipe",
      stderr: "pipe",
      timeout: 240_000,
    },
  ],
});
