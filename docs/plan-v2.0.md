# Plan de la versión 2.0

| | |
|---|---|
| **Estado** | Propuesta para revisión y aprobación — nada de esto está implementado |
| **Parte de** | 1.2.0 (2026-11-14) |
| **Tipo (SemVer)** | MAYOR: retira una interfaz, cambia valores por defecto y elimina configuración obsoleta |
| **Documentos relacionados** | [`hoja-de-ruta.md`](hoja-de-ruta.md) (fases 9–12), [`analisis-mejoras.md`](analisis-mejoras.md), [`notas-version-1.2.0.md`](notas-version-1.2.0.md) |

## 1. Para qué una versión mayor

La 1.x creció añadiendo capacidades sobre dos interfaces paralelas. La 1.2.0 demostró el
coste: la misma función implementada dos veces divergió y una de las copias filtraba
contraseñas de activos restringidos. La 2.0 tiene **tres objetivos**, en este orden:

1. **Una sola implementación de cada regla.** Retirar la interfaz clásica (Jinja) y mover la
   lógica a una capa de servicios, de modo que un control de acceso exista en un único sitio.
2. **Segura sin configurar.** Que una instalación recién desplegada arranque con los valores
   que hoy solo tienen las plantillas de producción, y que las acciones de mayor impacto exijan
   reautenticación.
3. **Verificable.** Pruebas de navegador y una matriz de permisos que impidan que una ruta
   nueva quede sin cubrir.

Las funciones nuevas (apartado 5, bloque D) son el cuarto objetivo y **ceden ante los tres
primeros**: si el calendario aprieta, pasan a la 2.1.

## 2. Por qué es MAYOR: lo que rompe

Según [`versionado.md`](versionado.md), un cambio que rompe configuración, datos o integraciones
es MAYOR. La 2.0 rompe, de forma deliberada:

| # | Rotura | A quién afecta | Mitigación |
|---|---|---|---|
| R1 | Desaparecen las rutas HTML de la interfaz clásica (`/login`, `/servidores/…`, `/configuracion`…). | Quien aún use la interfaz clásica o tenga marcadores a ella. | Aviso de retirada en la 1.3; redirecciones a la ruta equivalente del frontend. |
| R2 | `PASSWD_REQUIRE_ENV_KEYS=true` por defecto: sin claves por entorno la aplicación no arranca. | Instalaciones que dependen de las claves autogeneradas en el volumen. | Comando `exportar-claves` y guía; `false` explícito para desarrollo. |
| R3 | `PASSWD_RATE_LIMIT_BACKEND=bd` por defecto. | Nadie funcionalmente; cambia el coste de escritura. | Documentado; `memoria` sigue disponible. |
| R4 | Se eliminan `PASSWD_SMTP_TLS` y la herencia `SMTP_ENABLED` ← `NOTIFY_ENABLED` (obsoletas desde la 1.2.0). | Despliegues que no migraron su `.env`. | La 1.3 avisa en el arranque y en la consola si se usan. |
| R5 | Las notas del vault personal pasan a guardarse cifradas (cambio de columna, no aditivo). | Datos existentes. | Migración Alembic que cifra en el sitio; respaldo obligatorio previo. |
| R6 | La cadena de auditoría pasa a HMAC con clave: los registros anteriores quedan como tramo «heredado». | Quien verifique la cadena con herramientas propias. | `verificar-auditoria` valida ambos tramos y marca el punto de corte. |
| R7 | `/api/v1/inventario` excluye por defecto los activos restringidos y pagina siempre. | Integraciones que esperan el listado completo en una respuesta. | Alcance de token `inventario:restringidos` y cabeceras de paginación; anunciado en la 1.3. |
| R8 | Exportar exige reautenticación (contraseña + código). | Automatismos que llamen a `/api/web/exportar`. | La CLI `exportar-csv` no cambia. |

Todo lo demás debe seguir funcionando sin tocar nada. **Regla de alcance:** si aparece una
novena rotura durante el desarrollo, se decide expresamente si entra o se pospone a la 3.0.

## 3. Camino hasta la 2.0

| Versión | Contenido | Propósito |
|---|---|---|
| **1.2.x** | Solo correcciones de la 1.2.0. | Estabilizar lo publicado. |
| **1.3.0** | Avisos de retirada (R1, R4, R7), capa de servicios para autenticación y credenciales **sin retirar nada**, pruebas de navegador, matriz de permisos, **gobernanza de rotación y HMAC de la cadena de auditoría** (R6 adelantado). | Que la 2.0 sea «quitar lo ya avisado», no una reescritura. |
| **1.4.0** | **Agente Linux y protocolo `/api/agent`** ([`plan-rotacion-agentes.md`](plan-rotacion-agentes.md) §8.2). Aditiva, sin roturas. | Rotación real sobre gobernanza probada, sin condicionar R1–R8. |
| **2.0.0** | Las roturas R1–R8 y los bloques A–C. | La versión mayor. |
| **2.1.0 en adelante** | Lo del bloque D que no haya entrado y la continuación de la serie de agentes (Windows y programación, telemetría y cobertura, conectores y endurecimiento del canal). | Funciones nuevas sin presión de fecha. |

A partir de la 2.1.0 ambos planes comparten numeración: cada versión declara en su PR qué contenido
lleva de este plan y qué contenido de [`plan-rotacion-agentes.md`](plan-rotacion-agentes.md) §8. El
bloque D no es bloqueante, de modo que puede repartirse entre esas versiones sin alterar el orden
de la serie de agentes.

La 1.3.0 crece respecto a lo previsto porque la gobernanza de rotación necesita exactamente lo mismo
que esta versión ya iba a construir —`app/servicios/` y la reautenticación de alto impacto— y porque
el libro mayor de rotaciones solo vale como prueba si la cadena de auditoría está firmada (R6). La
1.4.0 se intercala sin roturas y no retrasa ninguna de las ocho.

La prueba `tests/test_version.py` exige `X.Y.Z` estricto, así que las versiones candidatas se
publican como etiquetas `v2.0.0-rc.N` **sin** cambiar `__version__` hasta la definitiva, o se
amplía antes esa prueba para admitir prelanzamientos. Decisión pendiente (apartado 8).

## 4. Principios de diseño

- **Un caso de uso, una función.** `app/servicios/` contiene las reglas; `api_web` solo
  traduce HTTP ↔ servicio. Ningún control de acceso vive en un controlador.
- **Denegar por defecto.** Los parámetros que amplían lo que se ve (`incluir_restringidos`)
  valen `False` salvo petición explícita, como ya hace la exportación desde la 1.2.0.
- **Sin degradación silenciosa.** Si un control no puede aplicarse (clave ausente, correo
  caído) la función se niega y lo dice; no continúa con menos seguridad.
- **Cada rotura, con salida.** Ninguna de las de R1–R8 se publica sin aviso previo en la 1.3,
  guía de migración y vuelta atrás probada.

## 5. Alcance por bloques

Esfuerzo: **S** horas–un día · **M** días · **L** una o más semanas.

### Bloque A — Una sola implementación (objetivo 1)

| ID | Trabajo | Criterio de aceptación | Esf. |
|---|---|---|:-:|
| A1 | Capa `app/servicios/` para autenticación, credenciales, inventario, usuarios, accesos, notas y vault. | `api_web/*` no contiene consultas ni decisiones de acceso; cada servicio tiene pruebas propias sin HTTP. | L |
| A2 | Migrar las pruebas que hoy entran por la interfaz clásica (`tests/conftest.py` y la mayoría de la suite) a la API JSON. | La suite pasa sin `app/routes`. Es el **trabajo previo obligatorio** de A3 y el de mayor volumen. | L |
| A3 | Retirar `app/routes` (salvo `/api/v1`), `app/templates`, `app/static` y la dependencia `jinja2`. Redirecciones de las rutas antiguas (R1). | No queda ninguna ruta HTML servida por el backend; el barrido pre-MFA sigue cubriendo ≥ 40 rutas. | M |
| A4 | Matriz de pruebas rol × recurso × restricción generada a partir del registro de rutas. | Añadir un endpoint sin declarar su política hace fallar la suite. | M |
| A5 | Manejador global de excepciones y formato de error único `{detail, code}`. | Ningún 500 devuelve traza ni texto del framework. | S |

### Bloque B — Segura sin configurar (objetivo 2)

| ID | Trabajo | Criterio de aceptación | Esf. |
|---|---|---|:-:|
| B1 | Reautenticación reutilizable (contraseña + código vigente, válida unos minutos) para exportar, restablecer el segundo factor ajeno, cambiar roles y editar la configuración de correo (R8). | Un único mecanismo, el mismo de «Mi seguridad»; auditado; con límite de tasa. | M |
| B2 | Valores por defecto de producción (R2, R3) y arranque que **se niega** con configuración insegura fuera de modo desarrollo. | Lista de comprobaciones de arranque documentada y probada. | S |
| B3 | Cifrado de las notas del vault personal (R5). | Migración reversible; `recifrar` y el respaldo las cubren. | M |
| B4 | Cadena de auditoría con HMAC y escritura serializada (R6). | Dos escrituras simultáneas no bifurcan la cadena; quien escribe en la BD sin la clave no puede recalcularla. | M |
| B5 | CSP con *nonce* en el frontend: fuera `'unsafe-inline'` de `script-src`. | Cabecera verificada en CI; el modo desarrollo sigue funcionando. | M |
| B6 | Contenedores `read_only`, `cap_drop: ALL`, `no-new-privileges`; imagen escaneada en CI. | Trivy sobre la imagen bloquea vulnerabilidades críticas. | S |
| B7 | Cadena de suministro: lockfile de Python con *hashes*, Dependabot, CodeQL, *actions* fijadas por SHA. | Construcción reproducible; `pip install --require-hashes` en la imagen. | M |
| B8 | `/api/v1/inventario` respeta `restringido` y pagina siempre (R7). | Prueba de contrato; nuevo alcance de token documentado. | S |
| B9 | Eliminar configuración obsoleta (R4) y los ajustes sin efecto. | Ninguna variable aceptada carece de consumidor; `.env.example` generado desde el código. | S |

### Bloque C — Verificable y mantenible (objetivo 3)

| ID | Trabajo | Criterio de aceptación | Esf. |
|---|---|---|:-:|
| C1 | Pruebas de navegador en CI: acceso, expiración de sesión, alta y verificación del segundo factor por ambos métodos, configuración, exportación. | Corren en cada PR contra backend + frontend + SMTP simulado. | M |
| C2 | Pruebas de componentes del frontend y cobertura del backend ≥ 80 %. | Umbral en CI. | M |
| C3 | Paginación del dashboard y del vault; eliminar las consultas repetidas de `serializers.py` y `access.py`; índice para la búsqueda por nombre. | Con 5 000 credenciales el dashboard responde con un número fijo de consultas. | M |
| C4 | Manual operativo y capturas regenerados para la 2.0, incluyendo lo añadido en la 1.2.0. | Las capturas se generan con las pruebas de C1, no a mano. | M |
| C5 | Limpiar los avisos del linter del frontend (`set-state-in-effect`). | `pnpm lint` sin avisos y configurado para fallar con ellos. | S |

### Bloque D — Funciones nuevas (objetivo 4; pasan a 2.1 si hace falta)

| ID | Trabajo | Por qué | Esf. |
|---|---|---|:-:|
| D1 | **Llaves de acceso (WebAuthn)** como tercer método elegible, y como requisito opcional para administradores. | Es la mejora de seguridad de mayor impacto pendiente: el TOTP y el correo son vulnerables a suplantación en tiempo real. La estructura de método elegible de la 1.2.0 ya lo permite. | L |
| D2 | **Sesiones activas**: ver y cerrar las propias; límite de sesiones concurrentes. | Hoy no hay forma de ver dónde está abierta una cuenta. | M |
| D3 | **Contraseñas reutilizadas y filtradas** en inventario y vault (k-anonimato, con opción sin conexión). | Detecta el riesgo más frecuente en credenciales de servidor. | M |
| D4 | **Papelera e historial de versiones** en el vault personal. | El borrado actual es definitivo. | M |
| D5 | **Compartir por enlace de un solo uso** con caducidad. | Evita enviar contraseñas por canales ajenos al sistema. | M |
| D6 | **Cola de correo con reintentos** y plantillas; programación interna de `avisar-rotacion`. | El envío actual es síncrono y sin reintento. | M |
| D7 | Generador configurable y medidor de fortaleza real. | Pulido de uso diario. | S |

## 6. Orden de ejecución

```
1.3.0  ─ A1 (auth, credenciales) ─ A4 ─ C1 ─ avisos de retirada
2.0.0  ─ A2 ─► A3            (la retirada depende de migrar las pruebas)
       ─ A1 (resto) ─ A5
       ─ B1 ─► B8, R8        (la reautenticación desbloquea exportar)
       ─ B3, B4              (migraciones de datos: juntas, un solo respaldo)
       ─ B2, B9              (al final: cambian valores por defecto)
       ─ B5, B6, B7, C2–C5   (en paralelo)
2.1.0  ─ D1 … D7 según prioridad
```

Dos dependencias mandan sobre el resto: **A2 antes que A3** (la suite actual entra casi toda
por la interfaz clásica) y **C1 antes que A3** (sin pruebas de navegador, retirar una interfaz
deja el frontend como única vía y sin red).

## 7. Riesgos

| Riesgo | Probabilidad | Efecto | Respuesta |
|---|:-:|:-:|---|
| A2 resulta mucho mayor de lo previsto (casi toda la suite usa formularios Jinja). | Alta | Retrasa A3 | Medirlo en la 1.3 migrando un módulo; si no cabe, la 2.0 sale con la interfaz clásica desactivada por defecto pero aún presente. |
| B3/B4 fallan a mitad de migración. | Baja | Pérdida de datos | Migración idempotente, respaldo obligatorio y ensayo en preproducción con copia real. |
| R2 deja sin arrancar una instalación tras actualizar. | Media | Parada | El arranque explica qué falta y cómo exportar las claves existentes; se prueba la actualización desde 1.2.0. |
| CSP con *nonce* (B5) obliga a renderizado dinámico y penaliza el rendimiento. | Media | Lentitud | Medir antes; alternativa: *hashes* de los scripts de arranque. |
| WebAuthn (D1) amplía mucho la superficie. | Media | Fecha | Está en el bloque D: no condiciona la 2.0. |

## 8. Decisiones que necesita el responsable del sistema

1. **¿Se retira del todo la interfaz clásica en la 2.0**, o se deja desactivada por defecto una
   versión más? (Recomendado: retirarla; la duplicación es el origen del fallo de la 1.2.0.)
2. **¿WebAuthn entra en la 2.0 o en la 2.1?** (Recomendado: 2.1, salvo que sea requisito de
   cumplimiento.)
3. **¿El aislamiento del vault personal frente al administrador es un requisito?** Hoy quien
   tiene la clave y la base de datos puede leerlo. Si lo es, hace falta cifrado del lado del
   cliente, que cambia la recuperación de cuentas y no cabe en este plan.
4. **¿Se integran directorio corporativo u OIDC?** Sigue excluido por decisión anterior; una
   versión mayor es el momento natural para reabrirla.
5. **¿Se publican versiones candidatas?** Condiciona la prueba de versionado (apartado 3).

## 9. Cuándo se da por terminada la 2.0

- No existe `app/routes` (salvo `/api/v1`) ni plantillas; la suite completa pasa.
- La matriz de permisos (A4) cubre todas las rutas y falla ante una ruta sin política.
- Una instalación nueva con la configuración por defecto supera la lista de verificación de
  producción sin cambios manuales.
- Actualización probada 1.2.0 → 2.0.0 sobre una copia de datos reales, con vuelta atrás.
- Pruebas de navegador en verde en CI; cobertura ≥ 80 %.
- Guía de migración, notas de versión con catálogo de cambios y manual regenerado.

## 10. Fuera de alcance

Alta disponibilidad multinodo, firma de imágenes, auditoría en tiempo real y GeoIP siguen
como en la [hoja de ruta](hoja-de-ruta.md): diferidos o descartados por bajo retorno.
