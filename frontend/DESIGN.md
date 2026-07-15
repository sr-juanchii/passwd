# Sistema de diseño — passwd

Contrato visual del frontend. Toda pantalla nueva o retocada debe cumplirlo; si una regla
no encaja, se cambia aquí primero. Los tokens viven en `src/app/globals.css` (Tailwind v4,
CSS-first: **no existe `tailwind.config`** y no debe crearse).

## 1. Principio rector: tinta y estado

La interfaz es **monocroma** (Geist sobre neutros oklch de croma 0). El color existe solo
como **señal de estado de rotación/peligro**, con dos tonos validados (banda de marcas +
contraste 4.5:1 de texto pequeño, en claro y oscuro):

| Token | Significado | Claro | Oscuro |
|---|---|---|---|
| `--warning` | credencial **por vencer** (`proxima`) | `oklch(0.555 0.146 49)` | `oklch(0.666 0.157 58.3)` |
| `--destructive` | credencial **vencida** / acción peligrosa | `oklch(0.577 0.245 27.325)` | `oklch(0.704 0.191 22.216)` |

- Variantes suaves para tintes de superficie: `--warning-soft`, `--destructive-soft`
  (color-mix ~10-12%). Nunca fondo sólido rojo/ámbar: siempre tinte + texto del tono.
- **No hay verde de éxito ni azul de info.** "Todo al día" se comunica por ausencia de
  color; el éxito, con el toast neutro. `--sidebar-primary` es neutro también en oscuro.
- El color **nunca va solo** (accesibilidad): siempre acompañado de etiqueta o cifra
  (`RiskDot` + "12d", segmento de barra + leyenda con recuento).

## 2. Tipografía

- **Geist Sans** para prosa e interfaz; **Geist Mono** para todo valor *identificable por
  máquina* (IP, usuario, puerto, token, contador, fecha corta): use `<Mono>`.
- Antetítulos de sección: `<Eyebrow>` (mono, versalitas, `text-2xs` con tracking 0.14em).
- Números grandes siempre `tabular-nums`. Jerarquía de página: `PageHeader` (h1
  `text-2xl font-semibold tracking-tight`).
- Escala micro: `text-2xs` (11px) es token; los tamaños ópticos intermedios
  (11.5/12.5/13/13.5px) están permitidos como valores puntuales, no inventar nuevos.

## 3. Superficie y elevación

- Arquitectura de capas en claro: lienzo `--background` (0.977) < sidebar (0.985) <
  tarjeta `--card` (blanco). En oscuro: lienzo 0.145 < sidebar/tarjeta 0.205.
- **Producto plano:** las superficies se separan con *hairline* (`border` o
  `ring-1 ring-foreground/10`), sin sombra. La sombra (`shadow-overlay`) pertenece SOLO
  a capas flotantes: dropdown, popover, select, dialog, sheet, toast.
- Radios: exclusivamente la escala de tokens — `rounded-md` (8px) controles pequeños,
  `rounded-lg` (10px) controles, `rounded-xl` (14px) paneles/tarjetas, `rounded-4xl`
  píldoras. **Prohibidos los valores bracket** (`rounded-[14px]` → `rounded-xl`).

## 4. Componentes canónicos

- `EmptyState` — único patrón de vacío (tile de icono + título + descripción + CTA).
- `SectionHeader` — único encabezado de sección (Eyebrow + icono opcional + contador
  `Chip` + acción). Retira los patrones `text-sm font-semibold` y variantes.
- `CampoPassword` (+ `MedidorFuerza`) — campo de contraseña con mostrar/ocultar,
  generador y medidor (débil→destructive, media→warning, fuerte→tinta).
- `OtpInput` — 6 casillas (h-12) con auto-avance, pegado distribuido y aria por dígito;
  única representación de códigos TOTP.
- `PageSkeleton` — esqueletos por forma (`hero`, `tabla`, `ficha`, `formulario`).
  Las cargas usan skeleton con la silueta real, **no** `Loader2` centrado.
- Tablas: siempre dentro de tarjeta `rounded-xl border bg-card overflow-hidden`, `thead`
  sobre `bg-muted`.
- Confirmaciones: `AlertDialog` con `AlertDialogAction` destructivo cuando la acción lo
  es; los secretos de un solo uso no se cierran con click fuera.

## 5. Movimiento

- **Sin flags experimentales**: la transición de página la da `(app)/template.tsx`
  (remonta en cada navegación) con `anim-page-in` (fade + rise 6px, 240ms ease-out).
- Listas con entrada escalonada: `anim-rise` + `style={{ "--stagger": i }}` (30ms/ítem,
  tope visual ~8 ítems).
- Todo movimiento respeta `prefers-reduced-motion` (los keyframes viven bajo
  `@media (prefers-reduced-motion: no-preference)`).
- Micro-interacciones ya normadas: `active:translate-y-px` en botones, `transition-colors`
  en filas/hover, `data-open:animate-in` de los flotantes (100ms).

## 6. Reglas de contenido

- Tratamiento de **usted** en todo el producto (nada de tuteo).
- Microcopy de vencimiento: `Nd` + contexto («12d · vencida», «43d · por vencer»).
- Voz de los vacíos: qué falta + cómo resolverlo (CTA si hay permiso).

## 7. Restricciones duras (no tocar)

- CSP de `next.config.ts`: todo recurso self-hosted; sin fuentes/imagenes/scripts externos.
- Next 16.2.9 no estándar: `src/proxy.ts` (no `middleware.ts`); `global-error.tsx` con
  `unstable_retry` y `<html>/<body>` propios. Docs de la versión en
  `node_modules/next/dist/docs/`.
- Seguridad de credenciales: revelar/copiar SIEMPRE vía API (auditado), timers de 30 s,
  contraseña vacía al editar = conservar, CSRF de login, gates `puede()` y flags
  `puede_revelar/puede_gestionar` — el rediseño no altera ninguna condición.
- `CredencialesTabla` conserva nombre y firma. `riesgo.ts` (DIAS_PROXIMA=60) y
  `password-gen.ts` tienen tests y reglas de negocio.
- QR de MFA sobre `bg-white` también en oscuro (escaneo fiable).
