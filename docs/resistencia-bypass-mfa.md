# Resistencia al salto del segundo factor (MFA)

Este documento responde a una pregunta operativa concreta:

> «Con el sistema en producción, ¿puede un atacante con Burp Suite saltarse el
> MFA de Google Authenticator?»

Se aborda con el modelo de amenaza explícito, el resultado de una auditoría
dirigida (que encontró **una vulnerabilidad real, ya corregida**) y la batería de
pruebas automáticas que impide que vuelva a abrirse.

---

## 1. Modelo de amenaza

**El atacante ya conoce la contraseña** de un usuario —fuga de otro servicio,
reutilización, phishing— y usa un proxy de intercepción (Burp Suite, ZAP,
mitmproxy) para hablar **directamente con la API**, sin pasar por el frontend.

Esto es importante porque determina qué defensas cuentan y qué defensas no:

| Defensa | ¿Sirve contra este atacante? |
|---|---|
| El guard de rutas de `frontend/src/proxy.ts` | **No.** Es código de cliente; el atacante no lo ejecuta |
| Ocultar botones o pantallas en la interfaz | **No.** Compone las peticiones a mano |
| Ofuscar el bundle de JavaScript | **No.** No necesita leerlo: le basta observar el tráfico |
| Validación en el navegador | **No.** La elimina o la ignora |
| Etapa de sesión verificada en servidor | **Sí** |
| Anti-reutilización del código TOTP en servidor | **Sí** |
| Bloqueo de cuenta por intentos fallidos | **Sí** |
| Rotación del token de sesión al completar el MFA | **Sí** |
| CSRF ligado a la sesión | **Sí** |

Es la misma idea que en [`proteccion-codigo-fuente.md`](proteccion-codigo-fuente.md):
**solo cuentan los controles del servidor.** Un atacante con Burp opera en el
plano donde el cliente no existe.

## 2. La invariante que se verifica

Todo el flujo de acceso se reduce a una sola propiedad, y es la que se prueba de
forma exhaustiva:

> Con una sesión en cualquier etapa **previa** a `activa`, **ningún** endpoint de
> la aplicación entrega datos ni ejecuta efectos.

El proyecto modela el acceso como una máquina de etapas en la tabla
`sesiones_web` (`app/models.py`):

```
cambio_password  →  mfa_enrolamiento  →  activa
                 →  mfa_pendiente     →  activa
```

La etapa vive **en el servidor**, no en la cookie ni en un campo manipulable: la
cookie solo lleva un token aleatorio de 256 bits del que en base de datos se
guarda únicamente el hash SHA-256. El atacante puede reescribir cualquier
cabecera, cuerpo o cookie con Burp, pero no puede cambiar su etapa: eso exigiría
escribir en la base de datos.

Las dependencias que la imponen son `sesion_activa` (web Jinja, `app/deps.py`) y
`sesion_activa_json` (API JSON, `app/api_web/deps.py`), y ambas comparan la etapa
contra `ETAPA_ACTIVA` de forma estricta.

## 3. Vulnerabilidad encontrada y corregida

### Reutilización del código TOTP de enrolamiento (`ultimo_otp_usado`)

**Severidad: alta.** Permitía usar dos veces el mismo código de 6 dígitos, es
decir, exactamente el ataque de *replay* que se monta con Burp: capturar la
petición de verificación y reenviarla.

El proyecto ya implementaba la protección que exige el RFC 6238 §5.2 —retener el
último código aceptado para rechazarlo si se repite— mediante el campo
`Usuario.ultimo_otp_usado`. El fallo estaba en una **asimetría de normalización**
entre el punto que guarda el código y el que lo compara:

| Punto | Código anterior | Efecto |
|---|---|---|
| Enrolamiento (`/mfa/configurar`) | `codigo.strip()` | conserva los espacios internos |
| Verificación (`/mfa/verificar`) | `codigo.strip().replace(" ", "")` | los elimina |

Las aplicaciones autenticadoras muestran los códigos **agrupados** —`599 790`—,
así que la forma con espacio llega al servidor de manera habitual, no
excepcional. Al enrolar con `599 790` se almacenaba literalmente `"599 790"`;
después, en la verificación, el código normalizado `"599790"` **no coincidía**
con lo almacenado, la comparación anti-reutilización daba negativo y el mismo
código volvía a ser aceptado durante toda su ventana de validez (hasta ~90 s con
`valid_window=1`).

El mismo defecto tenía una segunda cara: la columna es `String(8)`, de modo que
una forma sin normalizar como `1 2 3 4 5 6` (11 caracteres) se truncaría en MySQL
no estricto —rompiendo también la comparación— o provocaría un error en modo
estricto.

Afectaba a **los dos flujos**: la web Jinja (`app/routes/auth.py`) y la API JSON
que consume el frontend Next.js (`app/api_web/auth.py`).

**Corrección aplicada.** En lugar de parchear los dos puntos, se introdujo una
única forma canónica en `app/security/mfa.py`:

```python
def normalizar_codigo(codigo: str) -> str:
    """Forma canónica de un código TOTP: dígitos sin espacios ni separadores."""
    return codigo.strip().replace(" ", "")
```

Ahora los **seis** puntos que tocan un código TOTP —validación, y registro y
comparación en los tres flujos: enrolamiento, verificación y recuperación— pasan
por esa misma función. La asimetría queda cerrada *por construcción*: no puede
reaparecer al editar un solo sitio, porque ya no hay dos definiciones que puedan
divergir. Y la forma canónica cabe siempre en `String(8)`, con lo que desaparece
el problema de truncamiento.

## 4. Vectores auditados sin hallazgos

Cada uno tiene su prueba automática en `tests/test_bypass_mfa.py`:

| Vector de salto del MFA | Resultado |
|---|---|
| **Barrido exhaustivo**: 113 rutas × 3 etapas previas | Ninguna entrega datos |
| **Re-enrolamiento** («registro *mi* autenticador en *tu* cuenta») | Cerrado: desde `mfa_pendiente` el enrolamiento devuelve 403 |
| **Fuga del secreto TOTP** a una sesión pre-MFA | No ocurre: ni el secreto, ni el QR, ni el URI `otpauth://` |
| **Replay del TOTP** entre sesiones distintas | Rechazado (`ultimo_otp_usado`) |
| **Replay reformateando el código** con espacios | Rechazado tras la corrección del apartado 3 |
| **Replay del código de recuperación** de un solo uso | Rechazado (`usado_en`) |
| **Fuerza bruta** de los 6 dígitos (Intruder) | Bloqueo de cuenta y revocación de sesiones |
| **Fijación de sesión**: sembrar una cookie antes del MFA | El token rota al completar el MFA; la cookie previa muere |
| **Falsificación de la cookie** de sesión | En base de datos solo vive el hash SHA-256 |
| **CSRF ausente o de otra sesión** | 403 en ambos flujos |
| **Recuperación de contraseña** como puerta trasera | Exige el segundo factor; no desactiva el MFA ni concede sesión |
| **Tokens de API** emitidos por una sesión pre-MFA | Cerrado: emitirlos exige MFA completo |
| **Saltar el cambio forzado** de contraseña | Cerrado |

Dos notas sobre por qué estos vectores están realmente cerrados:

- **El re-enrolamiento** es el vector más habitual en implementaciones reales de
  MFA. Aquí no funciona porque la etapa se decide en el servidor a partir de
  `usuario.mfa_habilitado`: quien ya tiene MFA cae siempre en `mfa_pendiente`, y
  `en_etapa_json` exige coincidencia **exacta** de etapa, así que el enrolamiento
  es inalcanzable. No hay transición que el cliente pueda inducir.
- **La recuperación de contraseña** («olvidé mi contraseña») tampoco es una
  puerta trasera: `app/security/recuperacion.py` obliga a probar el segundo
  factor —TOTP en vivo o un código de recuperación— *antes* de autorizar el
  cambio, el desafío caduca a los 10 minutos, se invalida a los 5 intentos
  fallidos, y completarlo revoca todas las sesiones sin conceder ninguna: el
  usuario debe volver a pasar por el MFA.

## 5. Cómo están construidas las pruebas (y por qué importa)

`tests/test_bypass_mfa.py` **enumera las rutas registradas en la aplicación** en
lugar de comprobar una lista escrita a mano. Un endpoint nuevo que olvide su
dependencia de sesión rompe la suite automáticamente, en vez de pasar
inadvertido hasta que alguien lo encuentre con Burp en producción. Es la
diferencia entre una prueba que documenta el pasado y una que protege el futuro.

Tres detalles deliberados del diseño de la suite:

- **El 422 no cuenta como rechazo válido.** Un 422 (cuerpo inválido) significaría
  que la petición superó la autenticación y llegó a validar el cuerpo; aceptarlo
  enmascararía un endpoint que sí se ejecutaría con un cuerpo bien formado. Solo
  se admiten 303/401/403/404/405/423/429.
- **Hay una prueba que vigila al propio barrido**
  (`test_el_barrido_cubre_una_superficie_representativa`): exige que examine al
  menos 40 rutas. Sin ella, un fallo en la enumeración dejaría el barrido pasando
  en vacío. Esto no es hipotético: durante esta auditoría, una lectura plana de
  `aplicacion.routes` devolvía **una sola ruta**, porque desde FastAPI 0.141 los
  routers incluidos se envuelven en `_IncludedRouter` y no se aplanan. Esa guarda
  detectó el falso verde; la enumeración se hace ahora sobre el esquema OpenAPI.
- **Otra prueba impide exenciones fantasma**
  (`test_las_rutas_declaradas_como_pre_mfa_existen_de_verdad`): una entrada
  obsoleta en la lista de rutas exentas podría volver a aplicarse por accidente a
  un endpoint nuevo que reutilizara ese nombre.

## 6. Lo que estas pruebas **no** cubren

Ser explícito aquí importa tanto como el resto del documento:

- **Phishing en tiempo real / *adversary-in-the-middle*.** Un sitio falso que
  proxifica el real (Evilginx, Modlishka) captura contraseña y TOTP y los usa al
  instante. Ningún control del servidor lo detiene, porque el código es válido y
  se usa una sola vez. Es la limitación **intrínseca del TOTP**, no de esta
  implementación. La única defensa real es un segundo factor ligado al origen:
  **WebAuthn/FIDO2** (llave física o *passkey*), donde la firma va atada al
  dominio y un sitio falso no puede reutilizarla. Para un sistema que custodia
  las contraseñas de todos los servidores, migrar a WebAuthn —o añadirlo para las
  cuentas de administrador— es la mejora de seguridad de mayor impacto disponible;
  queda anotada en [`hoja-de-ruta.md`](hoja-de-ruta.md).
- **Robo de la cookie de sesión ya activa.** Fuera del alcance del MFA. Lo
  mitigan `HttpOnly` + `SameSite=Strict` + `Secure`, la doble expiración
  (absoluta y por inactividad), la revocación en servidor y HSTS.
- **Compromiso de una cuenta de administrador.** Un administrador puede
  restablecer el MFA de otro usuario (`/usuarios/{id}/reset-mfa`); es una
  necesidad operativa, queda auditada y no es un salto del MFA. Se controla
  limitando el número de administradores y revisando la bitácora.
- **Acceso al servidor o a la base de datos.** Otro nivel de amenaza: quien
  ejecuta código en el servidor no necesita saltarse el MFA.

## 7. Verificación en producción

```bash
# Con una sesión detenida en 'mfa_pendiente' (cookie tras enviar solo la
# contraseña), ningún endpoint de datos debe responder 200:
curl -sI -b "passwd_session=$COOKIE" https://SU-DOMINIO/api/web/dashboard   # → 401
curl -sI -b "passwd_session=$COOKIE" https://SU-DOMINIO/api/web/vault       # → 401
curl -sI -b "passwd_session=$COOKIE" https://SU-DOMINIO/api/web/mfa/configurar  # → 403

# Una cookie inventada no vale:
curl -sI -b "passwd_session=inventada" https://SU-DOMINIO/api/web/dashboard # → 401
```

Y en cada despliegue:

- [ ] `pytest tests/test_bypass_mfa.py` en verde (lo ejecuta el CI en cada push).
- [ ] `PASSWD_MAX_FAILED_ATTEMPTS` y `PASSWD_LOCKOUT_MINUTES` con valores
      operativos (ver [`referencia-configuracion.md`](referencia-configuracion.md)).
- [ ] `PASSWD_RATE_LIMIT_BACKEND=bd` si hay **más de un worker o réplica**: con el
      backend en memoria, el límite de tasa es por proceso y el presupuesto
      efectivo se multiplica por el número de procesos.
- [ ] `PASSWD_COOKIE_SECURE=true` y TLS en el borde.
- [ ] Relojes sincronizados por NTP: el TOTP tolera ±30 s y un servidor
      desfasado rechazaría códigos legítimos.

---

## Documentos relacionados

- [`control-acceso.md`](control-acceso.md) — RBAC y control de acceso por objeto.
- [`proteccion-codigo-fuente.md`](proteccion-codigo-fuente.md) — por qué los
  controles de cliente no cuentan.
- [`cumplimiento-owasp.md`](cumplimiento-owasp.md) — A01 (control de acceso roto)
  y A07 (fallos de identificación y autenticación).
- [`arquitectura.md`](arquitectura.md) — modelo de seguridad completo.
