# Protección del código fuente y exposición desde el navegador

Este documento responde a una pregunta concreta y frecuente:

> «¿Se puede bloquear el acceso al código fuente desde las herramientas de desarrollador del
> navegador, para que nadie pueda vulnerar el sistema en producción?»

La respuesta honesta tiene dos partes: **qué no se puede hacer** (y por qué intentarlo empeora la
seguridad) y **qué sí se puede hacer** (que es bastante, y ya está implementado). Al final se
identifica **la brecha real** de exposición de código fuente de este proyecto, que no está en el
navegador.

---

## 1. Lo que no es posible: bloquear las herramientas de desarrollador

**No existe forma de impedir que un usuario lea el código que su propio navegador ejecuta.** No es
una limitación de este proyecto ni de Next.js: es consecuencia de cómo funciona la web.

Para que el navegador pinte una pantalla, el servidor tiene que entregarle el HTML, el CSS y el
JavaScript. Una vez entregados, están en la máquina del usuario y bajo su control total. Las
herramientas de desarrollador son solo **una** de las formas de mirarlos:

| Vía | Se neutraliza con trucos anti-DevTools? |
|---|---|
| F12 / clic derecho → Inspeccionar | Parcialmente, y es trivial de saltar |
| `Ctrl+U` (ver código fuente) | No |
| `view-source:https://…` en la barra de direcciones | No |
| `curl https://…/_next/static/chunks/main-abc123.js` | No |
| `wget -r` sobre el sitio completo | No |
| Un proxy de intercepción (Burp, mitmproxy, ZAP) | No |
| DevTools con JavaScript deshabilitado | No |
| Guardar la página y abrirla en un editor | No |
| Caché del navegador en disco | No |

Las técnicas que circulan para «bloquear DevTools» —bucles de `debugger`, capturar `F12` y el menú
contextual, sobrescribir `console.log`, detectar el tamaño de la ventana— tienen tres problemas:

1. **Se saltan en segundos.** Cualquiera de las filas «No» de la tabla las elude sin esfuerzo. Un
   atacante real no usa DevTools: usa `curl` y un proxy.
2. **Rompen el producto.** Los bucles de `debugger` congelan pestañas legítimas, el bloqueo del clic
   derecho rompe copiar/pegar y la navegación por teclado, y todo ello degrada la accesibilidad
   (lectores de pantalla) y la capacidad de soporte (un administrador no puede diagnosticar nada).
3. **Producen una falsa sensación de seguridad**, que es el peor resultado de los tres: se invierte
   esfuerzo en una barrera decorativa mientras se deja de mirar donde sí hay riesgo.

### El punto de fondo: leer el frontend no debe permitir vulnerar el sistema

La premisa que hay que corregir es «si alguien ve el código, puede vulnerar el sistema». Si eso fuera
cierto en este proyecto, **la vulnerabilidad no sería DevTools: sería el backend**. El frontend de
esta aplicación no toma ninguna decisión de seguridad. Todo lo que importa se decide en el servidor:

- La autenticación, el MFA y la etapa de la sesión (`app/security/sessions.py`).
- Los roles y los permisos por objeto (`app/deps.py`, `app/security/`, ver
  [`control-acceso.md`](control-acceso.md)).
- El cifrado de las credenciales y el revelado de secretos (nunca se envían al cliente salvo en la
  acción explícita de revelar, auditada y con límite de tasa).
- El límite de tasa, la validación de entrada y la auditoría.

El guard de rutas del cliente (`frontend/src/proxy.ts`) es **cosmético a propósito**: evita el
destello de layout antes de redirigir a `/login`, y su propio comentario en el código lo dice. Un
usuario puede quitarlo, modificar el bundle o llamar directamente a la API: cada petición se vuelve a
autorizar en el backend. Ese es el diseño correcto, y es lo que hace que leer el frontend no sea una
brecha.

Dicho de otro modo: el código del cliente se considera **público por diseño**. La seguridad del
sistema no depende de que sea secreto.

---

## 2. Lo que sí se puede hacer, y está implementado

Aunque el bundle sea legible, no tiene por qué ser *cómodo* de leer ni entregar información que la
aplicación no necesita para funcionar. Esto sí reduce superficie de ataque de forma medible.

### 2.1 Sin mapas de origen en producción

Un mapa de origen (`*.map`) reconstruye el **TypeScript original**: estructura de carpetas, nombres
de archivos, de funciones y de variables, y los comentarios. Es la diferencia entre leer código
minificado de una sola línea y leer el repositorio.

- `productionBrowserSourceMaps: false` fijado de forma explícita en
  [`frontend/next.config.ts`](../frontend/next.config.ts). Es el valor por omisión de Next, pero se
  declara para que un cambio accidental a `true` sea visible en la revisión de código.
- **Doble barrera en el borde**: nginx responde `404` a cualquier `*.map`, `*.ts` o `*.tsx`
  ([`templates-frontend/default.conf.template`](../infrastructure/nginx/templates-frontend/default.conf.template)).
  Aunque un build mal configurado los publicara, no salen a la red.
- **Verificación automática en CI**: [`scripts/verificar-build-frontend.sh`](../scripts/verificar-build-frontend.sh)
  falla el pipeline si aparece un `.map` en los artefactos públicos.

### 2.2 Sin secretos en el bundle del cliente

Todo lo que el navegador descarga es público de hecho. En Next, una variable de entorno solo cruza al
cliente con el prefijo `NEXT_PUBLIC_`: **este proyecto no usa ninguna**, y todos los secretos
(`PASSWD_SECRET_KEY`, `PASSWD_ENCRYPTION_KEY`, credenciales de base de datos) viven solo en el
proceso del backend.

El script de verificación busca esos patrones en `.next/static` y `public/` en cada build y falla si
alguno aparece, de modo que una fuga futura se detecta antes de desplegar.

### 2.3 Sin trazas de pila en la consola del navegador

El error boundary de la aplicación volcaba el objeto `Error` completo a la consola con
`console.error(error)`, lo que expone la traza de pila —nombres de módulos y de funciones internas— a
cualquiera con la consola abierta. Ahora ese volcado ocurre **solo en desarrollo**
([`frontend/src/app/(app)/error.tsx`](../frontend/src/app/(app)/error.tsx)); en producción la
interfaz muestra el `digest` de Next, que basta para correlacionar el fallo con el log del servidor
sin revelar nada del código.

### 2.4 Sin documentación interactiva de la API

`docs_url`, `redoc_url` y `openapi_url` están en `None` en [`app/main.py`](../app/main.py). Sin
`/docs`, `/redoc` ni `/openapi.json`, la superficie completa de la API —cada ruta, cada parámetro,
cada esquema— no se publica. Esto vale más que cualquier truco anti-DevTools: es el mapa que un
atacante querría de verdad.

### 2.5 Sin huella tecnológica

- `poweredByHeader: false` en `next.config.ts`: se elimina `X-Powered-By: Next.js`.
- `server_tokens off` y `proxy_hide_header X-Powered-By` en nginx: ni versión de nginx ni cabeceras
  del upstream.

No impide nada por sí solo, pero deja de regalar al atacante la respuesta a «¿qué CVE pruebo
primero?».

### 2.6 Sin metadatos de repositorio accesibles

nginx responde `404` a cualquier ruta que empiece por punto (`/.git/`, `/.env`, `/.svn/`, archivos de
editor), excluyendo `/.well-known/` que es legítimo para ACME. Un `/.git/` accesible es la fuga de
código fuente **completa** más habitual en despliegues reales: entrega el repositorio entero, con
historial. Ahora está cerrado en las dos plantillas de nginx.

### 2.7 Sin indexación ni archivado

Cabecera `X-Robots-Tag: noindex, nofollow, noarchive, nosnippet` en todas las páginas del frontend.
Evita que rutas y marcado de una aplicación interna queden expuestos en copias de terceros
(buscadores, archive.org) fuera de su control.

---

## 3. La brecha real de acceso al código fuente

> ⚠️ **El repositorio `sr-juanchii/passwd` es público en GitHub** (`"visibility": "public"`).

Todo lo del apartado 2 protege el código que viaja al navegador. Pero cualquiera puede ejecutar hoy:

```
git clone https://github.com/sr-juanchii/passwd.git
```

y obtener **el código fuente completo, sin minificar, con comentarios, historial de commits,
documentación de arquitectura, modelo de datos y plantillas de configuración**. Eso es órdenes de
magnitud más de lo que jamás se podría deducir del bundle minificado en DevTools.

Es decir: mientras el repositorio sea público, endurecer el navegador contra la lectura del código es
un esfuerzo sin efecto práctico sobre el objetivo declarado. **Esta es la brecha que hay que decidir
primero**, y es una decisión de negocio, no técnica:

**Opción A — El repositorio debe ser privado.** Es la única acción que cierra la exposición. Requiere
permisos de administrador en GitHub y no se puede hacer desde el código:

1. `https://github.com/sr-juanchii/passwd` → **Settings** → sección **Danger Zone**.
2. **Change repository visibility** → *Make private*.
3. Después: **rotar todo secreto que haya estado alguna vez en el historial**. Hacer el repositorio
   privado no borra los forks ni las copias ya clonadas, ni las cachés de terceros. El
   `.gitignore` de este proyecto excluye correctamente `.env`, `*.db`, `.secret_key`,
   `.encryption_key` y los `*.pem`, y el CI ejecuta `gitleaks` sobre el historial completo, así que
   el riesgo aquí es bajo — pero conviene confirmarlo con `gitleaks detect` antes de darlo por
   cerrado.
4. Revisar los 0 forks actuales y los 2 *stargazers*: los forks de un repositorio que se vuelve
   privado no se eliminan automáticamente en todos los casos.

**Opción B — El repositorio es público a propósito** (proyecto abierto, portafolio, auditoría
externa). Es una postura perfectamente defendible para un gestor de contraseñas: el modelo de
Bitwarden, KeePass y Vaultwarden. Pero entonces hay que asumir la consecuencia y ser coherente:

- El secreto del código **no** es un control de seguridad, y no debe figurar como tal en la matriz de
  cumplimiento.
- Toda la seguridad recae en la configuración de cada despliegue: claves fuertes, MFA obligatorio,
  `PASSWD_SECRET_KEY` y `PASSWD_ENCRYPTION_KEY` únicas por instalación, TLS, y las
  [plantillas por ambiente](ambientes.md) bien aplicadas.
- Conviene entonces **subir la exigencia sobre la revisión de dependencias y secretos**, ya que un
  atacante puede leer el código con calma y buscar el fallo lógico. El CI ya ejecuta `ruff`,
  `bandit`, `pip-audit`, `pnpm audit`, `gitleaks` y `Trivy`: ese es el control que de verdad protege
  en este escenario.

En ambos casos, lo que **no** debe hacerse es asumir que ofuscar el frontend compensa un repositorio
público.

---

## 4. Qué revisar en cada despliegue

Lista de verificación operativa antes de pasar a producción:

- [ ] `NODE_ENV=production` en el contenedor del frontend (ya fijado en `frontend/Dockerfile`).
- [ ] `pnpm build` ejecutado en la imagen, no `pnpm dev`. El servidor de desarrollo de Next **sí**
      sirve mapas de origen y código sin minificar: nunca debe exponerse.
- [ ] `scripts/verificar-build-frontend.sh` en verde (lo ejecuta el CI en cada push).
- [ ] `curl -sI https://SU-DOMINIO/_next/static/chunks/main.js.map` devuelve `404`.
- [ ] `curl -sI https://SU-DOMINIO/.git/config` devuelve `404`.
- [ ] `curl -sI https://SU-DOMINIO/.env` devuelve `404`.
- [ ] `curl -sI https://SU-DOMINIO/api/web/openapi.json` y `/docs` devuelven `404`.
- [ ] `curl -sI https://SU-DOMINIO/` no muestra `X-Powered-By` ni versión de `Server`.
- [ ] Decisión tomada y documentada sobre la visibilidad del repositorio (apartado 3).

---

## 5. Resumen

| Objetivo | ¿Alcanzable? | Estado |
|---|---|---|
| Impedir leer el JS del cliente en DevTools | **No**, y perseguirlo daña el producto | Descartado por diseño |
| Impedir reconstruir el código original (mapas de origen) | Sí | ✅ Implementado, con doble barrera y control en CI |
| Impedir que haya secretos en el cliente | Sí | ✅ Implementado y verificado en CI |
| Impedir trazas de pila en la consola de producción | Sí | ✅ Implementado |
| Impedir publicar el mapa de la API | Sí | ✅ Ya estaba (`openapi_url=None`) |
| Impedir la huella tecnológica | Sí | ✅ Implementado |
| Impedir el acceso a `/.git/` y `/.env` | Sí | ✅ Implementado |
| Impedir la obtención del código fuente completo | Sí, **pero solo haciendo privado el repositorio** | ⚠️ Pendiente de decisión (apartado 3) |

Y el principio que sostiene todo lo anterior: **el sistema es seguro porque el backend autoriza cada
petición, no porque el código sea secreto.** Esa propiedad se puede auditar, probar y demostrar. La
ofuscación, no.

---

## Documentos relacionados

- [`arquitectura.md`](arquitectura.md) — modelo de seguridad y flujos.
- [`control-acceso.md`](control-acceso.md) — RBAC y control por objeto (donde se decide de verdad).
- [`cumplimiento-owasp.md`](cumplimiento-owasp.md) — A05 (configuración incorrecta) y A01 (control de
  acceso roto).
- [`guia-nginx-tls.md`](guia-nginx-tls.md) — configuración del borde.
- [`ambientes.md`](ambientes.md) — plantillas por ambiente.
