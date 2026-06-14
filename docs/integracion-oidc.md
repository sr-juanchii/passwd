# Integración con LDAP / Active Directory / OIDC (diseño)

> **Estado: diseñado, pendiente de habilitación.** A diferencia del resto de la hoja de ruta,
> esta integración **no se activa "a ciegas"**: toca el flujo de autenticación —la parte más
> crítica del sistema—, requiere los datos del proveedor de identidad (IdP) de la organización
> y varias decisiones de política. Por eso se entrega como **diseño + configuración prevista**,
> para implementarla y habilitarla con tu IdP y una revisión de seguridad dedicada. Mientras
> tanto, la autenticación nativa (contraseña + MFA TOTP) sigue siendo el mecanismo único.

## Objetivo

Permitir el inicio de sesión contra el directorio corporativo (Microsoft Entra ID/Azure AD,
Keycloak, Google Workspace, Okta…) mediante **OpenID Connect (Authorization Code + PKCE**), para
SSO y gestión centralizada de altas/bajas. LDAP/AD directo se contempla a través del IdP OIDC
(recomendado) en lugar de bind LDAP nativo, por seguridad y simplicidad.

## Principios de diseño (seguros por defecto)

1. **Opcional y desactivado por defecto** (`PASSWD_OIDC_ENABLED=false`). Si está desactivado, el
   sistema funciona exactamente como hoy.
2. **Convivencia, no reemplazo**: el login nativo se mantiene como **acceso de emergencia
   (break-glass)** para al menos una cuenta de administrador, por si el IdP no está disponible.
3. **Sin auto-aprovisionamiento por defecto**: un inicio OIDC se asocia a una cuenta **ya
   existente** emparejando por `email` verificado. Si no existe, se **deniega** (evita que
   cualquier identidad del IdP obtenga acceso). El alta de usuarios sigue siendo explícita.
4. **MFA**: cuando el acceso es por OIDC, el **segundo factor lo exige el IdP** (política de la
   organización). El enrolamiento TOTP local no aplica a esas cuentas; debe documentarse que el
   IdP tiene MFA obligatorio.
5. **Roles**: el rol se gestiona **en este sistema** (no se confía en claims del IdP por defecto),
   para no depender de la correcta configuración de grupos del IdP. Opcionalmente, mapeo de un
   claim de grupos → rol, como mejora posterior y revisable.
6. **Mismo modelo de sesión**: tras validar el IdP se crea la misma `SesionWeb` revocable de
   siempre; la sesión OIDC nace ya en etapa activa (el IdP cubrió la autenticación y el MFA).

## Configuración prevista (variables `PASSWD_OIDC_*`)

```ini
PASSWD_OIDC_ENABLED=true
PASSWD_OIDC_DISCOVERY_URL=https://idp.example.com/.well-known/openid-configuration
PASSWD_OIDC_CLIENT_ID=...
PASSWD_OIDC_CLIENT_SECRET=...           # custodiado como el resto de secretos (entorno)
PASSWD_OIDC_REDIRECT_URL=https://passwd.su-organizacion.tld/oidc/callback
PASSWD_OIDC_SCOPES=openid email profile
```

## Flujo (Authorization Code + PKCE)

```
/login  ── "Entrar con SSO" ──> /oidc/login
   genera state + PKCE (code_verifier en sesión temporal), redirige al IdP
IdP autentica (incluido MFA del IdP) ──> /oidc/callback?code=&state=
   verifica state, intercambia code+code_verifier por tokens, valida el id_token
   (firma vía JWKS del discovery, iss, aud, exp, nonce), extrae email verificado
   empareja con un Usuario activo por email  ──> crea SesionWeb activa  ──> /
   si no hay coincidencia: 403 (acceso no aprovisionado), auditado
```

## Implementación prevista

- Dependencia: **`authlib`** (cliente OIDC maduro) + el `httpx` ya presente.
- Módulo `app/routes/oidc.py` con `/oidc/login` y `/oidc/callback`; botón condicional en
  `login.html` cuando `OIDC_ENABLED`.
- Reutiliza `crear_sesion(... etapa=ETAPA_ACTIVA)`, la auditoría (`login_correcto` con detalle
  "vía OIDC") y la limitación de tasa.
- Pruebas con un IdP **simulado** (mock de discovery/JWKS/token/userinfo) para validar el flujo
  sin un IdP real: éxito, `state` inválido, `email` no verificado, usuario inexistente → 403.

## Decisiones que debes confirmar antes de implementarla

1. **IdP y datos**: ¿qué proveedor (Entra ID/Keycloak/Okta/…)? URL de discovery, client id/secret.
2. **Aprovisionamiento**: ¿solo cuentas preexistentes (recomendado) o auto-alta con rol mínimo
   (`analista`) en el primer inicio?
3. **Roles desde el IdP**: ¿gestionar el rol localmente (recomendado) o mapear un claim de grupos?
4. **Break-glass**: confirmar que al menos un administrador conserva login nativo.
5. **MFA**: confirmar que el IdP aplica MFA obligatorio a las cuentas que accederán aquí.

Con esas respuestas, la implementación es acotada (un módulo de rutas + config + pruebas con IdP
simulado) y se entregaría con su propia revisión de seguridad.
