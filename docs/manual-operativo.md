# Manual de uso, funciones y procedimientos

**Sistema:** Gestor de Contraseñas de Servidores (`passwd`)
**Versión del sistema documentada:** 1.1.0
**Ámbito del documento:** manual único de referencia para **usar, configurar y operar** el sistema
en producción. Cubre **todas** las funciones existentes en el código —interfaz web, API JSON,
API REST de integración, línea de comandos y avisos automáticos—, con **capturas de pantalla** de
cada apartado y la **configuración óptima** de cada parámetro.
**Estado:** listo para revisión y aprobación formal.

---

## Control documental

| Campo | Valor |
|---|---|
| Documento | Manual de uso, funciones y procedimientos |
| Código | MAN-PASSWD-01 |
| Versión del documento | 1.0 |
| Aplica a la versión del sistema | 1.1.0 (ver [`CHANGELOG.md`](../CHANGELOG.md)) |
| Audiencia | Usuarios finales (todos los roles), administradores del sistema y personal de operación/TI |
| Plataforma documentada | **MySQL 8.4 + nginx (TLS) + frontend Next.js + backend FastAPI** |
| Elaborado por | Equipo de TI |
| Revisado por | *(pendiente de firma)* |
| Aprobado por | *(pendiente de firma)* |
| Fecha de aprobación | *(pendiente)* |
| Próxima revisión | A los 12 meses o ante un cambio de versión mayor |

> **Sobre las capturas.** Todas las imágenes de este manual se tomaron sobre el **stack real de
> producción** —nginx terminando TLS, el frontend Next.js compilado en modo producción, el backend
> FastAPI y **MySQL 8.4** como base de datos— con **datos ficticios de demostración**. Su instancia
> mostrará sus propios activos y usuarios; la disposición de pantallas es idéntica.

---

## Índice

1. [Presentación del sistema](#1-presentación-del-sistema)
2. [Arquitectura de producción](#2-arquitectura-de-producción)
3. [Roles y matriz de permisos](#3-roles-y-matriz-de-permisos)
4. [Acceso al sistema](#4-acceso-al-sistema)
5. [Navegación general](#5-navegación-general)
6. [Inventario de activos](#6-inventario-de-activos)
7. [Credenciales](#7-credenciales)
8. [Notas seguras](#8-notas-seguras)
9. [Control de acceso por objeto y activos restringidos](#9-control-de-acceso-por-objeto-y-activos-restringidos)
10. [Vault personal](#10-vault-personal)
11. [Búsqueda](#11-búsqueda)
12. [Importación y exportación CSV](#12-importación-y-exportación-csv)
13. [Administración de usuarios](#13-administración-de-usuarios)
14. [Métricas de seguridad](#14-métricas-de-seguridad)
15. [Auditoría](#15-auditoría)
16. [Tokens de API e integración con el SIEM](#16-tokens-de-api-e-integración-con-el-siem)
17. [Configuración en caliente](#17-configuración-en-caliente)
18. [Avisos por correo y MFA de respaldo](#18-avisos-por-correo-y-mfa-de-respaldo)
19. [Funciones de línea de comandos](#19-funciones-de-línea-de-comandos)
20. [Configuración óptima de producción](#20-configuración-óptima-de-producción)
21. [Procedimientos operativos](#21-procedimientos-operativos)
22. [Lista de verificación para la aprobación](#22-lista-de-verificación-para-la-aprobación)
23. [Anexos](#23-anexos)

---

## 1. Presentación del sistema

El sistema custodia las **credenciales de acceso de toda la infraestructura** —servidores físicos
dedicados, hipervisores, máquinas virtuales y dispositivos de red— con un inventario relacional,
cifrado en reposo, autenticación de dos factores obligatoria, control de acceso por rol y por
objeto, y una bitácora de auditoría que registra **cada acceso a una contraseña**.

Tres ideas gobiernan todo el diseño y conviene tenerlas presentes al leer el manual:

1. **Nada se muestra sin dejar rastro.** Revelar o copiar una contraseña es una acción auditada,
   con usuario, IP, agente y hora.
2. **Mínimo privilegio por defecto.** El rol decide qué operaciones puede intentar un usuario; el
   control por objeto decide sobre qué activos concretos. El analista no ve nada hasta que se le
   concede algo.
3. **Los secretos nunca salen del sistema en claro** salvo por dos vías explícitas y auditadas: el
   revelado/copiado en pantalla y la exportación de migración (sección 12).

### Tipos de activo

```
🖥️  Servidor físico dedicado       una función única (p. ej. la base de datos de nómina)
⚙️  Hipervisor (Proxmox, ESXi…)    máquina física con su hardware que aloja VMs
    └── 🗔 Máquina virtual         cada una con su sistema y función
🔌  Dispositivo de red             switch, router, firewall, punto de acceso, balanceador…
```

Cada uno de los cuatro niveles almacena sus **credenciales** (usuario, contraseña cifrada,
servicio/protocolo, puerto y descripción del sistema al que da acceso) y una **nota segura**
cifrada.

---

## 2. Arquitectura de producción

El despliegue documentado en este manual es el de referencia para producción:

```
Navegador ──HTTPS(443)──▶ nginx  ──▶ /api/*, /healthz ──▶ backend FastAPI (uvicorn) ──▶ MySQL 8.4
                            │                                    │
                            └──▶ resto de rutas ──▶ frontend Next.js (build standalone)
```

| Componente | Función | Referencia |
|---|---|---|
| **nginx** | Termina TLS, aplica HSTS, limita tasa y tamaño de petición en el borde, enruta `/api/*` y `/healthz` al backend y el resto al frontend, bloquea `*.map`, `/.git`, `/.env` | [`infrastructure/nginx/templates-frontend/default.conf.template`](../infrastructure/nginx/templates-frontend/default.conf.template), [`guia-nginx-tls.md`](guia-nginx-tls.md) |
| **Frontend Next.js** | Interfaz de usuario (App Router, React 19, shadcn/ui); salida `standalone`, sin *source maps*, sin cabecera `X-Powered-By` | [`frontend/`](../frontend/), [`frontend/next.config.ts`](../frontend/next.config.ts) |
| **Backend FastAPI** | Lógica, seguridad, API JSON `/api/web` y API REST `/api/v1`; también sirve la interfaz clásica Jinja | [`app/`](../app/), [`arquitectura.md`](arquitectura.md) |
| **MySQL 8.4** | Persistencia (17 tablas). Los secretos llegan **ya cifrados** con Fernet/AES | [`modelo-datos.md`](modelo-datos.md) |

> La interfaz clásica (Jinja) que sirve el propio backend mantiene **paridad funcional** con el
> frontend Next.js. Este manual ilustra el **frontend Next.js**, que es la interfaz recomendada en
> producción; los procedimientos son equivalentes en ambas.

---

## 3. Roles y matriz de permisos

El sistema define cuatro roles. La matriz está implementada en [`app/rbac.py`](../app/rbac.py) y el
control por objeto en [`app/access.py`](../app/access.py).

| Permiso | admin | operador | auditor | analista |
|---|:-:|:-:|:-:|:-:|
| Ver inventario y credenciales (sin contraseña) | ✔ | ✔ † | ✔ | solo concedidos |
| Gestionar inventario (alta/edición/baja) | ✔ | ✔ † | ✘ | ✘ |
| Marcar un activo como **restringido** | ✔ | ✘ | ✘ | ✘ |
| Gestionar credenciales | ✔ | ✔ † | ✘ | ✘ |
| **Revelar/copiar** contraseñas (auditado) | ✔ | ✔ † | ✘ | solo concedidas con nivel «ver y revelar» |
| Exportar el inventario en claro (migración) | ✔ | ✔ | ✘ | ✘ |
| Vault personal propio | ✔ | ✔ | ✔ | ✔ |
| Gestionar usuarios | ✔ | ✘ | ✘ | ✘ |
| Conceder/revocar accesos por activo | ✔ | ✘ | ✘ | ✘ |
| Ver métricas y bitácora de auditoría | ✔ | ✘ | ✔ | ✘ |
| Gestionar tokens de API | ✔ | ✘ | ✘ | ✘ |
| Cambiar la configuración en caliente | ✔ | ✘ | ✘ | ✘ |

† Los activos marcados como **restringidos** quedan fuera del alcance del operador, que los trata
como inexistentes (error 404) en toda operación. El auditor sí los ve —su función es supervisar el
inventario completo— pero, como siempre, no puede revelar ninguna contraseña.

**Criterio de asignación recomendado**

| Perfil real | Rol |
|---|---|
| Responsable de TI / administrador de la plataforma | `admin` (mínimo 2 cuentas, máximo 4) |
| Administrador de sistemas y redes que opera a diario | `operador` |
| Auditoría interna, seguridad de la información, cumplimiento | `auditor` |
| Personal externo, becarios, proveedores, soporte puntual | `analista` + concesiones con caducidad |

---

## 4. Acceso al sistema

El acceso se realiza en **tres etapas** obligatorias: identidad → segundo factor → sesión activa.
Las cuentas nuevas atraviesan además el cambio de contraseña forzado y el enrolamiento del MFA.

### 4.1 Inicio de sesión

Abra la dirección del sistema (`https://<dominio>`), escriba **usuario** y **contraseña** y pulse
**Entrar**.

![Pantalla de inicio de sesión](capturas/01-login.png)

Si las credenciales no son correctas, el sistema devuelve **siempre el mismo mensaje genérico**, sin
indicar si el usuario existe (anti-enumeración de cuentas):

![Mensaje genérico de credenciales inválidas](capturas/02-login-credenciales-invalidas.png)

> **Bloqueo por intentos.** Tras **5 intentos fallidos** la cuenta queda bloqueada **15 minutos**.
> Además hay un límite por IP (15 intentos cada 5 minutos) y otro más estricto en nginx. Ambos son
> configurables (sección 17).

### 4.2 Cambio de contraseña obligatorio (primer acceso)

La contraseña que entrega el administrador es de **un solo uso**. En el primer acceso el sistema
exige definir una nueva.

![Cambio de contraseña obligatorio](capturas/03-password-cambio-obligatorio.png)

**Requisitos de la contraseña** (valores por defecto):

- mínimo **12 caracteres**;
- no puede figurar en la lista empaquetada de **10 000 contraseñas comunes**;
- no puede contener el nombre de usuario;
- se almacena con **Argon2id** (nunca en claro ni reversible).

### 4.3 Enrolamiento del segundo factor (MFA)

El MFA **es obligatorio para todas las cuentas, incluidas las administrativas**. Escanee el código
QR con su aplicación autenticadora (Aegis, FreeOTP, Google Authenticator, Microsoft Authenticator…)
o introduzca manualmente el secreto mostrado bajo el QR, y confirme el código de 6 dígitos.

![Enrolamiento MFA con código QR](capturas/04-mfa-enrolamiento-qr.png)

Al activarse, el sistema muestra **8 códigos de recuperación de un solo uso**. Solo se muestran una
vez: guárdelos en un lugar seguro (gestor personal o sobre sellado en caja fuerte) **antes** de
continuar. En la base de datos solo se guarda su hash.

![Códigos de recuperación de un solo uso](capturas/05-mfa-codigos-recuperacion.png)

### 4.4 Verificación en accesos posteriores

En los accesos siguientes, tras usuario y contraseña se pide el código de 6 dígitos.

![Verificación del segundo factor](capturas/06-mfa-verificacion.png)

Si no dispone del dispositivo, use **uno de los códigos de recuperación** (cada uno sirve una sola
vez).

![Acceso con código de recuperación](capturas/07-mfa-codigo-recuperacion.png)

> **Anti-reutilización.** El último código TOTP aceptado se retiene y se rechaza si se reenvía, aun
> reformateado con espacios (RFC 6238 §5.2). La ventana de validez tolera ±30 s de desfase de reloj.
> Este control se corrigió y endureció en la versión actual (ver Anexo E).

**Orden de preferencia recomendado:** aplicación autenticadora (TOTP) → código de recuperación →
código por correo (sección 4.4.1).

#### 4.4.1 Segundo factor por correo (OTP de respaldo)

Cubre el caso del usuario que **perdió el dispositivo autenticador y también sus códigos de
recuperación**. Requiere que el correo esté configurado (sección 17.1) y que el método esté
habilitado (`PASSWD_EMAIL_OTP_ENABLED`, activo por defecto).

En la pantalla de verificación aparece la opción **Enviarme un código por correo**:

![Opción de código por correo](capturas/06b-mfa-opcion-codigo-por-correo.png)

Al pulsarla, el sistema envía al **buzón registrado** un código de **8 dígitos** válido **10
minutos** y de **un solo uso**, e indica su vigencia sin revelar la dirección completa:

![Código enviado al correo registrado](capturas/06c-mfa-otp-correo-enviado.png)

El correo recibido tiene esta forma —contiene el código, la IP desde la que se solicitó y una
advertencia explícita— y **ningún otro secreto**:

```text
Asunto: [passwd-PROD] Código de verificación de un solo uso

Se solicitó un código de verificación para completar el acceso de la cuenta «jcarrasco».

    CÓDIGO:  45919740

Caduca en 10 minutos y solo puede usarse UNA vez.

  Solicitado desde la IP: 10.20.30.51
  Fecha y hora (UTC):     2026-08-06 11:37:49

Si NO fue usted quien lo solicitó, alguien conoce su contraseña: cambie su contraseña de
inmediato y avise al administrador. No comparta este código con nadie, ni siquiera con
personal de soporte.
```

**Controles que lo rodean** (implementados en [`app/security/otp_correo.py`](../app/security/otp_correo.py)):

| Control | Valor |
|---|---|
| Punto de partida | Solo desde la etapa `mfa_pendiente`: **exige la contraseña válida primero**, nunca es un punto de entrada |
| Código | 8 dígitos, un solo uso, caducidad 10 min (configurable), máximo 5 intentos |
| Almacenamiento | Solo el **hash SHA-256** en la base de datos |
| Límite de solicitudes | 3 cada 15 minutos **por cuenta** y 3 cada 15 minutos **por IP** (evita inundar un buzón y usar el sistema como amplificador de correo) |
| Auditoría | `mfa_otp_correo_solicitado` y `mfa_otp_correo_usado` |
| Alerta | Cada acceso completado por esta vía **avisa al equipo de seguridad**, porque merece revisión |
| Desactivación | `PASSWD_EMAIL_OTP_ENABLED=false`, también en caliente, sin afectar al resto del MFA |

> ⚠️ **Decisión de riesgo que debe quedar firmada en la aprobación.** Este factor es **más débil que
> el TOTP**: quien controle el buzón del usuario y conozca su contraseña completa el acceso, y añade
> el proveedor de correo a la cadena de confianza. Actívelo solo si el correo corporativo exige a su
> vez MFA; si no, desactívelo y deje como única alternativa los códigos de recuperación. Análisis
> completo en [`notificaciones-y-mfa-correo.md`](notificaciones-y-mfa-correo.md).

> 📌 **Disponibilidad por interfaz.** Esta opción se ofrece hoy en la **interfaz clásica (Jinja)** y
> en la API (`POST /api/web/mfa/otp-correo`); el frontend Next.js aún no la muestra. Ver Anexo F.
> Las dos capturas anteriores corresponden por eso a la interfaz clásica.

### 4.5 Recuperación de contraseña (autoservicio)

Desde el enlace **¿Olvidó su contraseña?** de la pantalla de acceso, un usuario con MFA enrolado
puede recuperar el acceso **sin intervención del administrador**. El circuito tiene tres pasos:

**Paso 1 — Identidad.** Usuario y **correo registrado** deben coincidir con los de la cuenta.

![Paso 1: identificación de la cuenta](capturas/08-recuperar-identidad.png)

> El sistema responde **siempre lo mismo** —y avanza al paso 2— exista o no la cuenta: no es posible
> deducir qué usuarios existen a partir de esta pantalla (anti-enumeración).

**Paso 2 — Segundo factor.** Se exige el código de 6 dígitos de la aplicación autenticadora o, con
el enlace inferior, **uno de los códigos de recuperación** de un solo uso.

![Paso 2: verificación con el segundo factor](capturas/09-recuperar-segundo-factor.png)

**Paso 3 — Nueva contraseña.** Se define la contraseña nueva (mismas reglas de la sección 4.2) y se
vuelve a entrar con normalidad. Todo el circuito queda auditado (`recuperacion_iniciada`,
`recuperacion_verificada`, `recuperacion_completada`, `recuperacion_fallida`) y tiene límite de tasa
por IP y por usuario.

> Si el usuario **perdió también** sus códigos de recuperación, o su cuenta aún no tenía MFA, la vía
> es el restablecimiento por parte del administrador (sección 13.3).

### 4.6 Duración y cierre de la sesión

| Control | Valor por defecto |
|---|---|
| Expiración por **inactividad** | 15 minutos |
| Expiración **absoluta** | 8 horas |
| Cookie | `HttpOnly`, `Secure`, `SameSite=Strict`; solo se guarda su hash en la BD |
| Revocación | Inmediata al cerrar sesión, al desactivar la cuenta o al restablecer la contraseña |

Cierre siempre la sesión desde el **menú de usuario** (esquina superior derecha) al terminar.

---

## 5. Navegación general

La interfaz tiene tres zonas fijas: la **barra lateral** (secciones visibles según el rol), la
**barra superior** (buscador global, tema claro/oscuro y menú de usuario) y el **área de trabajo**.

![Panel de inventario](capturas/10-inventario-panel.png)

- **Buscador global**: escriba en la barra superior o pulse `Ctrl/⌘ + K` para abrir la **paleta de
  comandos**, que navega a activos, credenciales y secciones sin usar el ratón.

  ![Paleta de comandos](capturas/13-paleta-comandos.png)

- **Menú de usuario**: muestra la cuenta y el rol activos, y contiene el cierre de sesión.

  ![Menú de usuario](capturas/12-menu-usuario-sesion.png)

- **Tema claro / oscuro**: el botón sol/luna alterna el tema; la preferencia se recuerda en el
  navegador.

  ![Modo oscuro](capturas/30-inventario-modo-oscuro.png)

- **Errores de recurso**: si un activo no existe —o el usuario no tiene acceso a él— se muestra un
  mensaje neutro que **no revela la existencia** del recurso.

  ![Recurso no disponible](capturas/46-error-recurso-no-disponible.png)

---

## 6. Inventario de activos

### 6.1 Panel principal

La pantalla de **Inventario** resume el estado de toda la infraestructura:

| Bloque | Qué muestra |
|---|---|
| **Postura de seguridad** | Número de credenciales que requieren rotación, con desglose **al día / por vencer / vencidas** y los totales de servidores, hipervisores, VMs, dispositivos y credenciales |
| **Cola de riesgo** | Las credenciales más urgentes de rotar, ordenadas por antigüedad |
| **Listado** | Todos los activos ordenados por urgencia, con estado, etiquetas, IP de gestión, número de credenciales y marca de vencidas |

Los filtros superiores (**Todo · En riesgo · Servidores · Hipervisores · Dispositivos**) y los tres
modos de vista (lista, tabla, tarjetas) acotan lo que se muestra. Los hipervisores se despliegan con
la flecha para ver sus máquinas virtuales.

Al pulsar sobre un activo se abre un **panel lateral** con su resumen y sus credenciales, sin salir
del listado:

![Panel lateral de un activo](capturas/11-inventario-panel-lateral-activo.png)

**Ficha completa** abre la vista detallada del activo.

### 6.2 Ficha de un activo

![Ficha completa de un servidor](capturas/14-servidor-ficha-completa.png)

La ficha reúne cuatro bloques: **información del activo** (hardware, sistema, ubicación, garantía,
proveedor, estado y etiquetas), **credenciales**, **nota segura** y —solo para administradores—
**control de acceso por objeto**.

### 6.3 Alta y edición de activos

Botones **+ Servidor**, **+ Hipervisor** y **+ Dispositivo** del panel principal; **Editar** en cada
ficha. Requiere rol `admin` u `operador`.

| Campo | Aplica a | Recomendación |
|---|---|---|
| Nombre | todos | Único; use la nomenclatura corporativa (`srv-`, `hv-`, `vm-`, `sw-`, `fw-`) |
| Descripción | todos | **Para qué sirve** el activo, en una frase |
| Sistema operativo / Plataforma+Versión | servidor, VM / hipervisor | Versión exacta (ayuda al inventario de parcheo) |
| IP de gestión | todos | Dirección por la que se administra |
| Marca/modelo, nº de serie, garantía, proveedor | servidor, hipervisor, dispositivo | Necesarios para soporte y renovación |
| RAM, CPU, almacenamiento | servidor, hipervisor, VM | En la VM son los recursos **asignados** |
| Tipo, firmware, puertos | dispositivo de red | Switch/router/firewall/AP/balanceador/otro |
| Estado | todos | `Activo` · `En mantenimiento` · `Retirado` |
| Etiquetas | todos | Minúsculas separadas por comas; son buscables (`producción, crítico, nómina`) |
| Restringido | servidor, hipervisor, dispositivo | Solo `admin`; ver sección 9.3 |

![Alta de servidor](capturas/21-servidor-alta-formulario.png)

![Edición de servidor: hardware, estado y etiquetas](capturas/22-servidor-edicion-hardware-estado.png)

### 6.4 Hipervisores y máquinas virtuales

La ficha del hipervisor documenta la **máquina física** (es el propio servidor) y lista sus
**máquinas virtuales** con su estado, además de sus credenciales de gestión (panel web, iLO/IPMI,
SSH…).

![Ficha de hipervisor con sus VMs](capturas/23-hipervisor-detalle-vms.png)

![Alta de hipervisor](capturas/24-hipervisor-alta-formulario.png)

Las VM se crean **desde su hipervisor** (`+ Nueva VM`) y tienen ficha propia con sus recursos
asignados y sus credenciales.

![Ficha de máquina virtual](capturas/25-maquina-virtual-detalle.png)

![Alta de máquina virtual](capturas/26-maquina-virtual-alta-formulario.png)

### 6.5 Dispositivos de red

Sección **Dispositivos de red** de la barra lateral. Cubre switches, routers, cortafuegos, puntos de
acceso, balanceadores y equipos no catalogados.

![Listado de dispositivos de red](capturas/27-dispositivos-red-listado.png)

![Ficha de dispositivo de red](capturas/28-dispositivo-red-detalle.png)

![Alta de dispositivo de red](capturas/29-dispositivo-red-alta-formulario.png)

### 6.6 Baja de un activo

**Eliminar** en la ficha. La operación pide confirmación explícita y es **en cascada**: se borran las
credenciales del activo, su historial, sus notas y sus concesiones; al eliminar un hipervisor se
eliminan también sus máquinas virtuales.

![Confirmación de borrado](capturas/20-confirmacion-eliminar.png)

> **Procedimiento recomendado:** antes de eliminar un activo en producción, cambie su estado a
> `Retirado` y espere el periodo de gracia acordado (30 días es un valor habitual). El borrado deja
> registro en la bitácora, pero no es reversible sin restaurar un respaldo.

---

## 7. Credenciales

### 7.1 Consultar una contraseña

Cada credencial ofrece dos vías, **ambas auditadas por separado**:

| Botón | Comportamiento | Cuándo usarlo |
|---|---|---|
| **Copiar** | Envía la contraseña al portapapeles **sin mostrarla** y lo limpia a los 30 s | Uso normal: es la vía de menor exposición |
| **Revelar** | Muestra la contraseña 30 s con cuenta atrás y la vuelve a ocultar sola | Solo cuando hay que teclearla o dictarla |

![Contraseña revelada con cuenta atrás](capturas/15-credencial-revelada.png)

![Contraseña copiada al portapapeles](capturas/16-credencial-copiada-portapapeles.png)

> **Límite anti-exfiltración.** Un mismo usuario puede revelar o copiar como máximo **20
> contraseñas cada 5 minutos** (configurable). Al superarlo, el sistema deniega la operación **y la
> registra** como intento bloqueado; conviene tratarlo como un indicador de incidente (sección 21.5).

### 7.2 Indicadores de rotación

| Indicador | Significado (umbral por defecto: 90 días) |
|---|---|
| `hace Nd` en gris | Credencial al día |
| `Nd · por vencer` en ámbar | Se acerca el vencimiento (aviso preventivo 14 días antes) |
| `Nd · vencida` en rojo + botón **Rotar** | Superó el umbral: debe rotarse |

### 7.3 Alta de credencial

Desde la ficha del activo, **+ Nueva credencial**.

![Alta de credencial con generador](capturas/31-credencial-alta-generador.png)

| Campo | Recomendación |
|---|---|
| Usuario de acceso | La cuenta real del sistema (`root`, `admin`, `svc-veeam`…) |
| Servicio / Protocolo | SSH, RDP, iLO/IPMI, panel web, base de datos, Telnet, SNMP… |
| Contraseña | Use **Generar**: 20 caracteres con CSPRNG. No reutilice contraseñas entre activos |
| Puerto | El real del servicio; ayuda a documentar accesos no estándar |
| Descripción | **A qué da acceso**; es lo que verá quien consulte la credencial |

### 7.4 Edición y rotación

**Editar** (lápiz) o **Rotar** en una credencial vencida.

![Edición y rotación de una credencial](capturas/32-credencial-edicion-rotacion.png)

- **Dejar la contraseña vacía conserva la actual** y permite corregir usuario, puerto o descripción
  sin tocar el secreto.
- **Introducir una contraseña nueva la rota**: reinicia el contador de antigüedad y guarda la
  anterior **cifrada** en el historial (por defecto, las **5** últimas).
- El historial se consulta desde la propia credencial; cada revelado de una contraseña histórica
  también queda auditado.

> **Orden correcto de una rotación:** cambie primero la contraseña **en el sistema real** y a
> continuación regístrela aquí; así el sistema nunca contiene una clave que el servidor no acepta.

### 7.5 Baja de credencial

El icono de papelera pide confirmación y elimina la credencial junto con su historial. Queda
registrada en la bitácora.

---

## 8. Notas seguras

Cada activo admite **una nota segura cifrada en reposo** para instrucciones de acceso, dependencias,
ventanas de mantenimiento o cualquier detalle sensible que no sea una contraseña.

![Nota segura revelada](capturas/17-nota-segura-revelada.png)

- **Ver nota** la descifra y muestra; el revelado **queda auditado** igual que una contraseña.
- **Editar nota** la modifica; el guardado también se audita.
- Las notas **no** aparecen en la exportación de migración ni en la API REST.

> **Qué no poner en una nota:** contraseñas. Para eso están las credenciales, que tienen contador de
> rotación, historial y control de acceso propio.

---

## 9. Control de acceso por objeto y activos restringidos

### 9.1 Concesiones a analistas (permitir de forma explícita)

El rol `analista` es **default-deny**: no ve nada hasta que un administrador le concede activos
concretos. Las concesiones se gestionan desde el bloque **Control de acceso por objeto** de la ficha
de cada activo.

![Panel de concesiones de un activo](capturas/18-control-acceso-por-objeto.png)

| Campo | Valores | Efecto |
|---|---|---|
| Analista | Cuentas con rol `analista` | Beneficiario de la concesión |
| Nivel | **Ver (sin contraseñas)** | Ve el activo y la lista de credenciales, sin poder revelarlas |
| | **Ver y revelar credenciales** | Además puede revelar/copiar (auditado y con el límite anti-exfiltración) |
| Caduca (días) | Número o vacío (∞) | **Ponga siempre una fecha**: la revocación automática es el control más eficaz |

**Las concesiones no se heredan.** Conceder un hipervisor **no** da acceso a sus máquinas virtuales:
cada activo se concede por separado. Revocar es inmediato (icono de papelera) y también se audita.

### 9.2 Cómo ve el sistema un analista

El analista ve **solo su inventario concedido**, con el nivel y la caducidad de cada concesión:

![Inventario del analista](capturas/47-analista-inventario-concedido.png)

En un activo concedido con nivel «ver y revelar» dispone de los botones Copiar/Revelar:

![Activo concedido al analista](capturas/48-analista-activo-con-concesion.png)

Un activo **no concedido** es indistinguible de uno inexistente (no se filtra su existencia):

![Activo sin concesión](capturas/49-analista-activo-sin-concesion.png)

### 9.3 Activos restringidos (ocultar de forma explícita)

Un administrador puede marcar un activo como **Restringido**. A partir de ese momento:

- el **operador** lo trata como inexistente (404) en listados, búsqueda, fichas y exportaciones;
- el **auditor** sí lo ve (supervisión del inventario completo) pero **nunca** revela contraseñas;
- la restricción **sí se hereda hacia abajo**: restringir un hipervisor restringe sus VMs;
- una concesión explícita de un administrador a un analista **prevalece** sobre la restricción.

![Activo restringido](capturas/19-activo-restringido.png)

### 9.4 Cómo ve el sistema un auditor

El auditor ve el inventario completo —incluidos los restringidos— y las secciones de Métricas y
Auditoría, pero **no** puede gestionar ni revelar nada.

![Inventario visto por el auditor](capturas/50-auditor-inventario-sin-revelado.png)

![Credenciales sin opción de revelado para el auditor](capturas/51-auditor-credenciales-ocultas.png)

---

## 10. Vault personal

Cada usuario dispone de un **vault privado** (sección **Mi vault**) para contraseñas de servicios,
aplicaciones o cuentas propias que no forman parte del inventario de infraestructura.

![Vault personal](capturas/34-vault-personal.png)

- **Solo el dueño** ve, edita y revela sus entradas: **ni el administrador** accede a ellas.
- Las contraseñas se cifran en reposo igual que las del inventario; revelar y copiar están auditados
  y sujetos al mismo límite anti-exfiltración.
- Las entradas **se incluyen en el respaldo cifrado**, pero **nunca** en la exportación en claro.

![Alta de entrada en el vault](capturas/35-vault-alta-entrada.png)

| Campo | Uso |
|---|---|
| Título | Nombre reconocible del servicio |
| Usuario | Cuenta o correo de acceso |
| Contraseña | Botón **Generar** disponible |
| URL | Dirección del servicio |
| Categoría | `Servicio` · `Aplicación` · `Cuenta` · `Otro` |
| Notas | Texto libre (no cifrado como la contraseña: no ponga secretos aquí) |

---

## 11. Búsqueda

**Buscar** (o `Ctrl/⌘ + K`) localiza activos y credenciales por nombre, descripción, IP, sistema
operativo, usuario de acceso, servicio o etiqueta.

![Búsqueda global](capturas/33-busqueda-global.png)

- **Nunca** se busca por contraseña ni se muestran contraseñas en los resultados.
- Los resultados respetan el control de acceso: el analista solo ve sus activos concedidos y el
  operador no ve los restringidos.

---

## 12. Importación y exportación CSV

Sección **Importar** (roles `admin` y `operador`).

![Importación y exportación CSV](capturas/36-importacion-exportacion-csv.png)

### 12.1 Importación masiva

1. Descargue la **plantilla CSV** desde la propia pantalla.
2. Complete una fila por elemento. La primera columna es el **tipo** (`servidor`, `hipervisor`,
   `vm`, `credencial`); el campo `padre` referencia el activo contenedor por nombre.
3. Arrastre el archivo o selecciónelo y confirme.

El archivo se procesa **en memoria** y las contraseñas se cifran al guardarse. Los errores de una
fila **no abortan** la importación: al terminar se informa de las filas creadas y de las rechazadas
con su motivo. La operación queda registrada en la bitácora.

> **El CSV contiene secretos en claro.** Trátelo como material clasificado: transpórtelo por canal
> seguro, no lo deje en descargas ni en almacenamiento compartido y **destrúyalo de forma
> permanente** inmediatamente después de importarlo.

### 12.2 Exportación para migración

**Exportar inventario en claro (CSV)** descarga todo el inventario —incluidas las contraseñas— en el
**mismo formato del importador**, de modo que se puede editar y volver a importar (round-trip) al
migrar entre instancias o versiones. Los **vaults personales quedan fuera**. La descarga queda
auditada. Aplican las mismas precauciones de custodia y destrucción del archivo.

---

## 13. Administración de usuarios

Sección **Usuarios** (solo `admin`).

![Gestión de usuarios](capturas/37-usuarios-gestion.png)

Las tarjetas superiores resumen las cuentas por rol; la tabla muestra estado, MFA, último acceso y
las acciones disponibles.

### 13.1 Alta de usuario

![Formulario de alta de usuario](capturas/38-usuario-alta-formulario.png)

Al crear la cuenta, el sistema genera una **contraseña temporal de un solo uso** que se muestra
**una única vez**:

![Contraseña temporal generada](capturas/39-usuario-password-temporal.png)

**Procedimiento de entrega:** copie la contraseña temporal y entréguela al usuario por un canal
seguro (en persona, teléfono o mensajería corporativa cifrada). El usuario deberá cambiarla y
enrolar el MFA en su primer acceso. El alta se notifica al equipo de seguridad por correo, **sin
incluir la contraseña**.

### 13.2 Cambio de rol

Desde la fila del usuario. El cambio es inmediato, se audita y **revoca las sesiones activas** del
afectado, que deberá volver a entrar con sus nuevos permisos; si los avisos están activos, se le
notifica el cambio.

### 13.3 Restablecer contraseña y restablecer MFA

| Acción | Efecto | Cuándo |
|---|---|---|
| **Restablecer contraseña** | Genera una contraseña temporal de un solo uso, desbloquea la cuenta y **revoca todas sus sesiones**. Si el correo está configurado, la temporal **se envía al buzón del titular** y el administrador solo ve el destino enmascarado; si el envío falla, se le muestra en pantalla como contingencia (y así queda anotado en la bitácora) | Olvido sin códigos de recuperación, sospecha de compromiso |
| **Restablecer MFA** | Borra el enrolamiento y **revoca las sesiones**: el usuario deberá volver a escanear el QR y recibirá códigos de recuperación nuevos | Pérdida o cambio del dispositivo autenticador y de los códigos |

La acción pide confirmación explícita:

![Confirmación del restablecimiento](capturas/39b-usuario-reset-confirmacion.png)

Con el correo configurado, el administrador **ya no manipula la contraseña**: la temporal viaja
directamente al buzón del titular y en pantalla solo se muestra el destino **enmascarado**, lo que
elimina el paso manual de copiarla y transmitirla por un canal sin auditoría.

![Contraseña temporal enviada al titular](capturas/39c-usuario-reset-enviado-al-titular.png)

> 📌 Esta pantalla corresponde a la **interfaz clásica**. En el frontend Next.js la acción funciona
> igual en el servidor (la contraseña se envía por correo), pero el diálogo aún no refleja el envío
> y muestra el campo de contraseña vacío. Ver Anexo F.

> **Verifique la identidad del solicitante fuera del sistema** (videollamada, responsable directo)
> antes de restablecer un MFA: es la vía más directa para tomar control de una cuenta.

### 13.4 Desactivación y reactivación

**Desactivar** revoca de inmediato todas las sesiones de la cuenta e impide nuevos accesos,
conservando su rastro en la bitácora. Es la acción correcta ante una **baja de personal** —no borrar
la cuenta—. **Reactivar** la habilita de nuevo.

---

## 14. Métricas de seguridad

Sección **Métricas** (roles `admin` y `auditor`). Es el panel de apoyo a la revisión periódica.

![Métricas de seguridad](capturas/40-metricas-seguridad.png)

| Indicador | Cómo leerlo | Acción esperada |
|---|---|---|
| Logins fallidos (24 h / 7 d) | Un salto sostenido sugiere fuerza bruta | Revisar la bitácora filtrando por `login_fallido` e IP |
| Rotación vencida | Credenciales por encima del umbral | Planificar rotación (sección 21.3) |
| Cuentas sin MFA | Altas que aún no completaron el enrolamiento | Cerrar el circuito con el usuario o desactivar la cuenta |
| Usuarios bloqueados | Cuentas bloqueadas por intentos fallidos | Contactar al usuario; verificar si es un ataque |
| Top accesos a credenciales | Quién consulta más contraseñas | Comparar con la operación esperada de cada persona |
| Concesiones por caducar | Accesos temporales próximos a expirar | Renovar de forma consciente o dejar caducar |

**Cadencia recomendada:** revisión semanal por el operador y revisión mensual documentada por el
auditor.

---

## 15. Auditoría

Sección **Auditoría** (roles `admin` y `auditor`). Registro **de solo anexado**, **encadenado por
hash** (cada registro incorpora el hash del anterior, lo que hace evidente cualquier manipulación) y
con **retención configurable** (mínimo 90 días; 365 por defecto).

![Bitácora de auditoría](capturas/41-auditoria-bitacora.png)

Cada registro incluye: fecha y hora, usuario, acción, tipo y ID de objeto, detalle, **dirección IP
real del cliente**, agente de usuario y resultado (éxito/fallo).

Los filtros por **usuario** y por **acción** acotan la consulta:

![Bitácora filtrada por acción](capturas/42-auditoria-filtro-accion.png)

**Acciones registradas** (lista completa en [`app/audit.py`](../app/audit.py)):

| Familia | Acciones |
|---|---|
| Autenticación | `login_correcto`, `login_fallido`, `login_cuenta_bloqueada`, `login_tasa_excedida`, `cierre_sesion`, `cuenta_bloqueada` |
| MFA | `mfa_correcto`, `mfa_fallido`, `mfa_enrolado`, `mfa_reiniciado`, `mfa_codigo_recuperacion_usado`, `mfa_otp_correo_solicitado`, `mfa_otp_correo_usado` |
| Contraseña propia | `password_cambiada`, `recuperacion_iniciada`, `recuperacion_verificada`, `recuperacion_completada`, `recuperacion_fallida` |
| Usuarios | `usuario_creado`, `usuario_actualizado`, `usuario_desactivado`, `usuario_reactivado` |
| Inventario | `activo_creado`, `activo_actualizado`, `activo_eliminado`, `activo_restriccion_cambiada` |
| Credenciales | `credencial_creada`, `credencial_actualizada`, `credencial_eliminada`, **`credencial_revelada`**, **`credencial_copiada`**, `historial_revelado`, `revelado_tasa_excedido` |
| Notas | `nota_actualizada`, `nota_revelada` |
| Acceso por objeto | `acceso_concedido`, `acceso_revocado`, `acceso_denegado` |
| Vault personal | `vault_entrada_creada`, `vault_entrada_actualizada`, `vault_entrada_eliminada`, `vault_entrada_revelada`, `vault_entrada_copiada` |
| Integración y datos | `token_api_creado`, `token_api_revocado`, `auditoria_exportada`, `importacion_realizada`, `inventario_exportado`, `respaldo_creado`, `respaldo_restaurado` |
| Configuración | `configuracion_cambiada`, `configuracion_restablecida`, `correo_prueba_enviado` |

**Exportar CSV** descarga la consulta filtrada (la exportación misma queda auditada, y el archivo se
genera con mitigación de inyección de fórmulas para abrirlo con seguridad en una hoja de cálculo).

La integridad del encadenamiento se comprueba en cualquier momento con:

```bash
python -m app.cli verificar-auditoria
```

---

## 16. Tokens de API e integración con el SIEM

Sección **Tokens API** (solo `admin`). Los tokens autentican la **API REST de solo lectura**
`/api/v1`, pensada para SIEM, CMDB y automatización. **Nunca exponen secretos.**

![Tokens de API](capturas/43-tokens-api.png)

### 16.1 Crear un token

Indique un **nombre descriptivo**, el **alcance** y la **caducidad** en días (`0` = nunca, no
recomendado).

| Alcance | Endpoints accesibles |
|---|---|
| Solo auditoría | `GET /api/v1/auditoria` |
| Solo inventario | `GET /api/v1/inventario` |
| Auditoría e inventario | Ambos |

El valor del token **se muestra una sola vez**; cópielo y guárdelo en el gestor de secretos del
sistema consumidor. En la base de datos solo queda su hash.

![Token generado (se muestra una sola vez)](capturas/44-token-api-generado.png)

### 16.2 Uso

```bash
curl -H "Authorization: Bearer <TOKEN>" \
     "https://passwd.empresa.tld/api/v1/auditoria?limite=500"
```

- Autenticación exclusivamente por cabecera `Authorization: Bearer` (sin cookies ni CSRF).
- Límite de 500 registros por petición y limitador de tasa propio por token.
- Referencia de parámetros y respuestas: [`referencia-api-rest.md`](referencia-api-rest.md).

### 16.3 Revocación

El icono de papelera revoca el token de inmediato (el registro permanece con estado **Revocado** para
la trazabilidad). Revoque un token en cuanto la integración deje de usarse o se sospeche de su fuga.

---

## 17. Configuración en caliente

Sección **Configuración** (solo `admin`). Modifica los parámetros de operación **sin reiniciar**; los
cambios se auditan, anulan las variables de entorno y se propagan al resto de procesos y réplicas.

![Configuración del sistema](capturas/45-configuracion-en-caliente.png)

Cada campo indica su procedencia: **por defecto** (valor de fábrica), **por entorno** (fijado en el
`.env`) o modificado en caliente; el botón de restablecer devuelve un ajuste a su valor base.

![Detalle de la pantalla de configuración](capturas/45b-configuracion-detalle.png)

### 17.1 Parámetros editables y valores recomendados

**Sesión y comportamiento**

| Ajuste | Por defecto | Recomendado en producción | Notas |
|---|---|---|---|
| Inactividad máxima (min) | 15 | **15** (10 en entornos de alta sensibilidad) | Cierre automático por inactividad |
| Vida máxima de sesión (h) | 8 | **8** | Tope absoluto aunque haya actividad |
| Amortiguación de actividad (s) | 60 | **60** | Reduce escrituras en la BD |

**Política de cuentas**

| Ajuste | Por defecto | Recomendado | Notas |
|---|---|---|---|
| Longitud mínima de contraseña | 12 | **14** | Con Argon2id y lista de comunes, 14 es un buen equilibrio |
| Intentos fallidos antes de bloquear | 5 | **5** | Bajarlo aumenta el riesgo de bloqueo por error del usuario |
| Duración del bloqueo (min) | 15 | **15** | |

**Límites de tasa (anti-abuso)**

| Ajuste | Por defecto | Recomendado | Notas |
|---|---|---|---|
| Límite de inicios de sesión (por IP) | 15 | **15** | Complementa el límite de nginx |
| Ventana de inicio de sesión (min) | 5 | **5** | |
| Límite de revelados/copiados (por usuario) | 20 | **20** (10 si la operación diaria es baja) | Control **anti-exfiltración** |
| Ventana de revelados (min) | 5 | **5** | |

**Inventario y auditoría**

| Ajuste | Por defecto | Recomendado | Notas |
|---|---|---|---|
| Rotación: días antes de alertar | 90 | **90** (60 para activos críticos) | Marca las credenciales como vencidas |
| Historial de contraseñas | 5 | **5** | Contraseñas anteriores conservadas cifradas |
| Retención de auditoría (días) | 365 | **365** o lo que exija su normativa (mínimo 90) | Purga automática al arranque |

**Notificaciones por correo**

| Ajuste | Por defecto | Recomendado | Notas |
|---|---|---|---|
| Notificaciones activas | desactivado | **activado** | Sin correo no hay avisos, ni OTP por correo, ni autoservicio de recuperación |
| Servidor / Puerto SMTP | — / 587 | Servidor corporativo / **587** | |
| Usuario y contraseña SMTP | — | Cuenta de servicio dedicada | La contraseña se guarda **cifrada** y nunca se muestra |
| Usar STARTTLS | activado | **activado** | |
| Remitente (From) | — | `passwd-alertas@empresa.tld` | |
| Destinatarios | — | Buzón del equipo de seguridad/SOC | Separados por comas |
| Nombre/emisor (TOTP) | `Gestor-Passwd` | `passwd-PROD` | Etiqueta visible en la app autenticadora |
| MFA por correo (OTP) | activado | **decisión de riesgo** (ver 18.2) | |
| Vigencia del OTP por correo (min) | 10 | **10** | |
| Avisos dinámicos a usuarios | activado | **activado** | |
| Aviso previo de rotación (días) | 14 | **14** | |

**Ejemplo de configuración de correo guardada** (los campos marcados «configurado aquí» tienen un
override en caliente; la contraseña SMTP se guarda cifrada y nunca se muestra):

![Configuración SMTP](capturas/45c-configuracion-correo-smtp.png)

**Probar el correo** envía un mensaje de prueba con la configuración guardada; úselo tras cada
cambio de SMTP. El resultado se muestra bajo el formulario:

![Prueba de correo correcta](capturas/45d-configuracion-prueba-correo.png)

> En la instancia de demostración de las capturas, STARTTLS aparece desactivado porque el servidor
> SMTP de prueba es local y sin TLS. **En producción manténgalo activado.**

### 17.2 Parámetros **no** editables en caliente

Por diseño, estos solo se fijan por entorno (requieren reinicio y viven en el gestor de secretos):
claves criptográficas, URL y pool de la base de datos, `cookie_secure`, tamaño máximo de petición,
proxies de confianza, backend del limitador de tasa y el administrador inicial. Se muestran como
**información de solo lectura** al pie de la pantalla de configuración.

---

## 18. Avisos por correo y MFA de respaldo

### 18.1 Qué notifica el sistema

Los correos comunican **el hecho, nunca el secreto**: jamás incluyen contraseñas, ni valores
anteriores, ni pistas sobre ellos.

| Aviso | Destinatario |
|---|---|
| Cuenta bloqueada por intentos fallidos | Equipo de seguridad (`Destinatarios`) y titular de la cuenta |
| Posible exfiltración (límite de revelados superado) | Equipo de seguridad |
| Alta de usuario | Equipo de seguridad |
| Contraseña temporal tras un restablecimiento | Titular de la cuenta (la contraseña viaja al buzón registrado; ver 13.3) |
| Fallo de respaldo programado | Equipo de seguridad |
| Inicio de sesión propio (con IP y agente) | Titular de la cuenta |
| Cambio en sus permisos, rol o concesiones | Usuario afectado |
| Contraseña de un activo compartido actualizada | Resto de usuarios con acceso a ese activo |
| Rotación obligatoria próxima | Usuarios con acceso a la credencial (los que pueden rotarla) |
| Acceso completado con OTP por correo | Equipo de seguridad (merece revisión) |

**Cómo se eligen los destinatarios.** Los avisos dirigidos a usuarios **no** usan una lista fija: se
resuelven en tiempo de ejecución contra la **matriz de permisos**, reutilizando las mismas funciones
que autorizan de verdad (`puede_ver_activo` / `puede_revelar_en_activo`), de modo que quien recibe
el aviso es exactamente quien tiene acceso al activo. Dos consecuencias operativas:

- Los envíos a varios destinatarios salen como **mensajes independientes**: agrupar direcciones en
  un `To:` revelaría quién más tiene acceso al activo.
- Los avisos de actividad sensible se **deduplican por sesión y categoría** (un aviso por tipo de
  actividad y sesión, no uno por acción) para que la señal no se pierda entre decenas de correos.
  La bitácora sí conserva el registro acción por acción. La deduplicación se apoya en el limitador
  de tasa: con más de un *worker*, use `PASSWD_RATE_LIMIT_BACKEND=bd`.

**Interruptores.** `PASSWD_NOTIFY_ENABLED` gobierna todo el correo; dentro de él,
`PASSWD_NOTIFY_USERS_ENABLED` (activo por defecto) gobierna los avisos a usuarios finales. Si su
despliegue ya tenía el correo activo y solo quiere las alertas al equipo de seguridad, póngalo en
`false`.

> **Antes de activar los avisos a usuarios, anúncielo.** Los usuarios que reciben por primera vez
> correos del sistema («se inició sesión en su cuenta») pueden confundirlos con phishing.

**Aviso preventivo de rotación.** El comando `python -m app.cli avisar-rotacion` (tarea diaria,
sección 20.7) avisa a quienes pueden rotar cada credencial cuando se acerca el cambio obligatorio,
distinguiendo «próxima» de «VENCIDA». Con `--simular` muestra el alcance **sin enviar nada**: úselo
la primera vez para comprobar a cuánta gente llegaría.

### 18.2 MFA de respaldo por correo (OTP)

El uso paso a paso está en la **sección 4.4.1**, con sus capturas y la tabla de controles. Aquí solo
la decisión de gobierno:

> **Decisión de riesgo que debe documentarse en la aprobación.** El OTP por correo es un factor
> **más débil** que el TOTP: quien controle el buzón y conozca la contraseña puede entrar. Si su
> correo corporativo ya exige MFA y está bien protegido, es un respaldo razonable; si no, desactívelo
> (`PASSWD_EMAIL_OTP_ENABLED=false`) y deje como única vía alternativa los códigos de recuperación.
> Análisis completo en [`notificaciones-y-mfa-correo.md`](notificaciones-y-mfa-correo.md) y
> [`resistencia-bypass-mfa.md`](resistencia-bypass-mfa.md).

**Excepciones deliberadas a la regla «ningún secreto por correo».** Solo dos mensajes llevan un
secreto, ambos de un solo uso, de vida corta y dirigidos al buzón de su propio titular: el **OTP del
MFA** y la **contraseña temporal de un restablecimiento**. Ninguna contraseña del inventario sale
nunca por correo.

---

## 19. Funciones de línea de comandos

Se ejecutan en el contenedor de la aplicación (`docker compose exec app python -m app.cli …`) o en el
servidor con el entorno cargado. Referencia detallada: [`referencia-cli.md`](referencia-cli.md).

| Comando | Para qué | Cuándo usarlo |
|---|---|---|
| `init-db` | Crea el esquema de la base de datos | Instalación inicial |
| `crear-admin --username U --email E` | Crea una cuenta de administrador | Arranque o recuperación de acceso administrativo |
| `respaldo --salida F [--retener N]` | **Respaldo cifrado portátil** de todo el sistema (usuarios, inventario, credenciales, vaults y bitácora) con frase (scrypt + Fernet) | Diario, automatizado (sección 20.6) |
| `restaurar --entrada F [--sobrescribir]` | Restaura un respaldo, incluso en otra instancia con claves distintas | Recuperación ante desastre, migración |
| `recifrar` | Recifra todo el material con la clave primaria | Rotación de la clave de cifrado (sección 21.6) |
| `exportar-csv --salida F` | Exporta el inventario **en claro** (mismo formato del importador; archivo con permisos 0600) | Migración entre instancias |
| `verificar-auditoria` | Verifica el encadenamiento por hash de la bitácora | Revisión periódica y ante sospecha de manipulación |
| `avisar-rotacion [--simular]` | Avisa por correo de las rotaciones obligatorias próximas | Tarea programada diaria |

> **Sin la frase de cifrado, un respaldo es irrecuperable.** Custódiela **aparte** del archivo de
> respaldo (gestor de secretos corporativo o caja fuerte), y verifique periódicamente que la frase
> guardada es la vigente (sección 21.4).

---

## 20. Configuración óptima de producción

### 20.1 Despliegue de referencia

```bash
cp .env.produccion.example .env      # y rellenar los secretos
chmod 600 .env
# certificados en infrastructure/nginx/certs/{fullchain,privkey}.pem
docker compose -f docker-compose.yml \
               -f docker-compose.frontend.yml \
               -f docker-compose.mysql.yml \
               -f docker-compose.backup.yml up -d --build
```

Esto levanta: **MySQL 8.4**, **backend FastAPI**, **frontend Next.js**, **nginx (TLS)** y el
**servicio de respaldos programados**.

### 20.2 Variables de entorno: valores óptimos

Plantilla completa en [`.env.produccion.example`](../.env.produccion.example). Resumen de decisiones:

| Variable | Valor recomendado | Por qué |
|---|---|---|
| `PASSWD_DOMAIN` | Dominio o IP interna del servicio | `server_name` de nginx |
| `PASSWD_REQUIRE_ENV_KEYS` | `true` | **Impide arrancar** si las claves no vienen del entorno: evita que se autogeneren junto a la base de datos |
| `PASSWD_SECRET_KEY` | Valor único de 48 bytes | `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `PASSWD_ENCRYPTION_KEY` | Clave Fernet única | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `MYSQL_PASSWORD` | Contraseña fuerte, sin `@ : / ?` | Se interpola en la URL de conexión |
| `PASSWD_COOKIE_SECURE` | `true` | Obligatorio: hay HTTPS por nginx |
| `PASSWD_SESSION_IDLE_MINUTES` / `_MAX_HOURS` | `15` / `8` | |
| `PASSWD_PASSWORD_MIN_LENGTH` | `14` | |
| `PASSWD_MAX_FAILED_ATTEMPTS` / `PASSWD_LOCKOUT_MINUTES` | `5` / `15` | |
| `PASSWD_LOGIN_RATE_LIMIT` / `_WINDOW_MINUTES` | `15` / `5` | |
| `PASSWD_REVEAL_RATE_LIMIT` / `_WINDOW_MINUTES` | `20` / `5` | Anti-exfiltración |
| `PASSWD_RATE_LIMIT_BACKEND` | **`bd`** | Con varios *workers* o réplicas, `memoria` multiplica el límite real por proceso |
| `PASSWD_MAX_REQUEST_BYTES` | `65536` | nginx aplica un tope equivalente en el borde |
| `PASSWD_TRUSTED_PROXIES` | `*` si **solo** nginx alcanza la app; si no, la IP/red del proxy | Hace que auditoría y límites usen la **IP real** del cliente |
| `PASSWD_AUDIT_RETENTION_DAYS` | `365` (mínimo 90) | |
| `PASSWD_ROTATION_MAX_DAYS` / `PASSWD_ROTATION_WARNING_DAYS` | `90` / `14` | |
| `PASSWD_PASSWORD_HISTORY_MAX` | `5` | |
| `PASSWD_TOTP_ISSUER` | `passwd-PROD` | Distinga los ambientes en la app autenticadora |
| `PASSWD_NOTIFY_ENABLED` + `SMTP_*` + `NOTIFY_TO` | Configurados | Sin correo no hay alertas ni autoservicio |
| `PASSWD_EMAIL_OTP_ENABLED` | Según la decisión de riesgo de 18.2 | |
| `PASSWD_BACKUP_PASSPHRASE` | Frase larga, custodiada fuera del servidor | Respaldos desatendidos |
| `PASSWD_DB_POOL_SIZE` / `_MAX_OVERFLOW` / `_POOL_RECYCLE_SECONDS` | `5` / `10` / `1800` | Ajuste el pool a los *workers*: `pool_size × workers ≤ max_connections` de MySQL |

**Reglas de oro**

1. Cada ambiente (producción, preproducción, calidad) usa **sus propias claves y su propia base de
   datos**. Nunca comparta `PASSWD_SECRET_KEY` ni `PASSWD_ENCRYPTION_KEY` entre ambientes.
2. Los secretos se entregan por gestor de secretos: todas las variables sensibles admiten la
   variante `PASSWD_<NOMBRE>_FILE` apuntando a un fichero montado (Docker secrets), de modo que no
   aparecen en la tabla de procesos ni en `docker inspect`.
3. `chmod 600 .env` y fuera del repositorio.

### 20.3 MySQL 8.4

| Aspecto | Recomendación |
|---|---|
| Juego de caracteres | `utf8mb4` / `utf8mb4_unicode_ci` (el overlay ya lo aplica) |
| Usuario | `passwd`, con privilegios **solo** sobre la base `passwd`; sin acceso remoto de `root` |
| Red | La base **no** se publica fuera de la red interna de compose |
| Conexiones | `max_connections` ≥ `(pool_size + max_overflow) × workers` + margen |
| `wait_timeout` | Mayor que `PASSWD_DB_POOL_RECYCLE_SECONDS` (1800 s) |
| Volumen | Volumen dedicado y respaldado; el respaldo lógico del sistema (`app.cli respaldo`) **no** sustituye al respaldo del motor, lo complementa |
| Cifrado | El sistema cifra los secretos **antes** de escribirlos; active además el cifrado del volumen si su política lo exige |

### 20.4 nginx

La plantilla incluida ya aplica la configuración recomendada; verifique tras cada despliegue:

- TLS 1.2/1.3 con suites modernas, `ssl_session_tickets off`, OCSP stapling;
- **HSTS emitido solo por nginx** (`max-age=31536000; includeSubDomains`);
- `limit_req` de 20 r/s general y **2 r/s en las rutas de login/MFA**, con `limit_conn` de 30;
- `client_max_body_size 4m`;
- 404 para `*.map`, `*.ts`, `*.tsx` y para `/.git`, `/.env` y similares (excepto `/.well-known/`);
- `server_tokens off` y ocultación de `X-Powered-By`;
- caché larga solo para `/_next/static/`.

Certificados y rotación sin caída: [`guia-nginx-tls.md`](guia-nginx-tls.md). Para redes sin dominio
(acceso por IP interna) hay scripts de CA interna en `infrastructure/nginx/`.

### 20.5 Frontend Next.js

| Aspecto | Valor |
|---|---|
| Build | `output: "standalone"`, imagen mínima y usuario sin privilegios |
| Mapas de origen en el navegador | **Desactivados** (`productionBrowserSourceMaps: false`) |
| Cabecera `X-Powered-By` | **Desactivada** |
| CSP | Restrictiva: `default-src 'self'`, sin orígenes externos, `frame-ancestors 'none'` |
| Indexación | `X-Robots-Tag: noindex, nofollow, noarchive, nosnippet` |
| Enrutado de API | nginx envía `/api/*` y `/healthz` al backend; el resto al servidor Next |

> Ninguna medida impide que el navegador ejecute —y por tanto lea— el JavaScript de la aplicación:
> lo que se elimina es la información **extra** (código original, huella tecnológica, metadatos).
> El razonamiento completo está en [`proteccion-codigo-fuente.md`](proteccion-codigo-fuente.md).

### 20.6 Respaldos programados

El overlay `docker-compose.backup.yml` ejecuta un **respaldo cifrado diario** conservando los 30 más
recientes y avisa por correo si falla. Complételo con:

1. **Copia externa (offsite)**: monte un destino remoto en `/srv/passwd/backups` o añada un envío a
   almacenamiento externo tras cada respaldo.
2. **Custodia de la frase** fuera del servidor.
3. **Prueba de restauración trimestral** documentada (sección 21.4).

### 20.7 Tareas programadas recomendadas

| Frecuencia | Tarea |
|---|---|
| Diaria | `python -m app.cli respaldo` (ya automatizado por el overlay) |
| Diaria | `python -m app.cli avisar-rotacion` |
| Mensual | `python -m app.cli verificar-auditoria` |
| Trimestral | Prueba de restauración en un entorno aislado |
| Semestral | Revisión de usuarios, roles y concesiones vigentes |

### 20.8 Comprobación posterior al despliegue

```bash
curl -sk https://<dominio>/healthz            # {"estado":"ok","version":"…"}
curl -sI https://<dominio>/ | grep -i strict  # HSTS presente
curl -s  http://<dominio>/ -o /dev/null -w '%{http_code}\n'   # 301 a HTTPS
```

Y en la propia interfaz: pantalla **Configuración → Información del sistema**, donde deben leerse
`Motor de base de datos: MySQL/MariaDB`, `Cookies solo por HTTPS: sí`, `Claves criptográficas por
entorno: sí` y `Backend del limitador de tasa: bd`.

---

## 21. Procedimientos operativos

### 21.1 Alta de un usuario

1. **Usuarios → Nuevo usuario**: complete usuario, correo, nombre y **rol mínimo necesario**.
2. Copie la **contraseña temporal** (se muestra una sola vez) y entréguela por canal seguro.
3. Indique al usuario que en su primer acceso deberá cambiarla y **enrolar el MFA**, y que debe
   guardar sus **códigos de recuperación**.
4. Si es `analista`, conceda los activos necesarios **con caducidad** (sección 9.1).
5. Verifique en **Métricas** que la cuenta ya no figura en «Cuentas sin MFA».

### 21.2 Baja de un usuario

1. **Usuarios → Desactivar** (no eliminar): revoca sus sesiones al instante.
2. Revoque sus **concesiones** vigentes y los **tokens de API** que hubiera creado.
3. **Rote las credenciales** a las que la persona tuvo acceso de revelado; priorice las de activos
   críticos.
4. Deje constancia en el registro de cambios de la organización; la bitácora conserva su rastro.

### 21.3 Rotación periódica de credenciales

1. **Inventario → filtro «En riesgo»** o **Métricas → Rotación vencida** para obtener la lista.
2. Por cada credencial: cambie la contraseña **en el sistema real** y después regístrela en la ficha
   (**Rotar** → **Generar** → **Guardar**).
3. Verifique que el contador vuelve a cero y que la anterior quedó en el historial.
4. Al terminar, la postura de seguridad del panel debe mostrar 0 vencidas.

### 21.4 Respaldo y prueba de restauración

```bash
# Respaldo manual
docker compose exec app python -m app.cli respaldo --salida /srv/passwd/backups/manual.passwd

# Restauración de prueba (SIEMPRE en una instancia aislada, nunca en producción)
docker compose exec app python -m app.cli restaurar --entrada /ruta/copia.passwd --sobrescribir
```

Documente en cada prueba: fecha, archivo utilizado, resultado, tiempo de restauración y responsable.

### 21.5 Respuesta a un posible incidente de exfiltración

Disparadores: alerta de correo «posible exfiltración», acción `revelado_tasa_excedido` en la
bitácora, o un pico anómalo en **Top accesos a credenciales**.

1. **Contener**: desactive la cuenta implicada (revoca sus sesiones al instante).
2. **Delimitar**: en **Auditoría**, filtre por ese usuario y por `credencial_revelada` /
   `credencial_copiada`; exporte el CSV como evidencia.
3. **Erradicar**: rote **todas** las credenciales consultadas en la ventana afectada.
4. **Verificar**: `python -m app.cli verificar-auditoria` para confirmar que la bitácora no fue
   manipulada.
5. **Documentar** el incidente y revisar si procede endurecer `PASSWD_REVEAL_RATE_LIMIT`.

### 21.6 Rotación de la clave de cifrado

1. Ponga en `PASSWD_ENCRYPTION_KEY` **`nueva,antigua`** (la primera cifra, las demás solo descifran).
2. Reinicie el servicio y ejecute `python -m app.cli recifrar`.
3. Compruebe que se revela correctamente una credencial de prueba.
4. Deje **solo `nueva`** en la variable y reinicie.
5. Genere un respaldo nuevo: los anteriores siguen siendo válidos (usan su propia frase).

### 21.7 Actualización de versión

1. Respaldo cifrado **y** copia del volumen de MySQL.
2. Lea el [`CHANGELOG.md`](../CHANGELOG.md) de las versiones intermedias.
3. Despliegue primero en preproducción con una copia de los datos y ejecute la verificación
   funcional (`python scripts/verificar_api_web.py`).
4. Actualice producción en ventana acordada; el esquema se reconcilia al arrancar.
5. Verifique con la lista de comprobación de la sección 20.8 y revise la bitácora del arranque.

---

## 22. Lista de verificación para la aprobación

Antes de firmar la puesta en producción, compruebe punto por punto:

**Plataforma**

- [ ] nginx sirve **solo** HTTPS y redirige el puerto 80; certificado válido y vigente.
- [ ] La aplicación **no** está publicada directamente: solo es alcanzable a través de nginx.
- [ ] MySQL no expone puerto fuera de la red interna; el usuario `passwd` no es administrador.
- [ ] `PASSWD_REQUIRE_ENV_KEYS=true` y las claves proceden del gestor de secretos.
- [ ] `PASSWD_COOKIE_SECURE=true` y `PASSWD_RATE_LIMIT_BACKEND=bd`.
- [ ] `PASSWD_TRUSTED_PROXIES` correcto: la bitácora muestra la **IP real** del cliente.
- [ ] `.env` con permisos `600` y fuera del repositorio.

**Cuentas y accesos**

- [ ] El administrador inicial cambió su contraseña y enroló MFA; sus códigos de recuperación están
      custodiados.
- [ ] Existen al menos **dos** cuentas `admin` (evita el bloqueo total) y ninguna cuenta compartida.
- [ ] No hay cuentas sin MFA en **Métricas**.
- [ ] Las concesiones a analistas tienen **caducidad**.
- [ ] Los activos sensibles están marcados como **Restringidos** si procede.

**Operación**

- [ ] Correo configurado y **probado** desde la pantalla de configuración (§17.1).
- [ ] **Decisión firmada sobre el segundo factor por correo**: activado (con el correo corporativo
      protegido por su propio MFA) o desactivado con `PASSWD_EMAIL_OTP_ENABLED=false` (§4.4.1).
- [ ] Usuarios **avisados** de que empezarán a recibir correos del sistema, antes de activar los
      avisos dinámicos (§18.1).
- [ ] Verificado en el borde: `curl -sk https://<dominio>/x.map` y `https://<dominio>/.git/config`
      devuelven **404**, y las respuestas no llevan `X-Powered-By` (§20.5).
- [ ] `scripts/verificar-build-frontend.sh` activo en el pipeline de CI (Anexo E).
- [ ] Respaldo programado activo, con frase custodiada aparte y **una restauración de prueba
      documentada**.
- [ ] Tarea diaria de `avisar-rotacion` programada.
- [ ] Retención de auditoría conforme a la normativa aplicable.
- [ ] Tokens de API creados con **alcance mínimo** y caducidad.
- [ ] Personal formado con este manual; responsables designados por rol.

---

## 23. Anexos

### Anexo A — Índice de capturas

| # | Captura | Apartado |
|---|---|---|
| 01 | Inicio de sesión | 4.1 |
| 02 | Credenciales inválidas (mensaje genérico) | 4.1 |
| 03 | Cambio de contraseña obligatorio | 4.2 |
| 04 | Enrolamiento MFA (QR) | 4.3 |
| 05 | Códigos de recuperación | 4.3 |
| 06 | Verificación del segundo factor | 4.4 |
| 07 | Acceso con código de recuperación | 4.4 |
| 06b | Opción «Enviarme un código por correo» | 4.4.1 |
| 06c | Código enviado al correo registrado | 4.4.1 |
| 08 | Recuperación de contraseña (identidad) | 4.5 |
| 09 | Recuperación: segundo factor | 4.5 |
| 10 | Panel de inventario | 5, 6.1 |
| 11 | Panel lateral de un activo | 6.1 |
| 12 | Menú de usuario | 5 |
| 13 | Paleta de comandos | 5, 11 |
| 14 | Ficha completa de servidor | 6.2 |
| 15 | Contraseña revelada | 7.1 |
| 16 | Contraseña copiada | 7.1 |
| 17 | Nota segura revelada | 8 |
| 18 | Control de acceso por objeto | 9.1 |
| 19 | Activo restringido | 9.3 |
| 20 | Confirmación de borrado | 6.6 |
| 21 | Alta de servidor | 6.3 |
| 22 | Edición de servidor | 6.3 |
| 23 | Hipervisor con sus VMs | 6.4 |
| 24 | Alta de hipervisor | 6.4 |
| 25 | Ficha de máquina virtual | 6.4 |
| 26 | Alta de máquina virtual | 6.4 |
| 27 | Listado de dispositivos de red | 6.5 |
| 28 | Ficha de dispositivo de red | 6.5 |
| 29 | Alta de dispositivo de red | 6.5 |
| 30 | Modo oscuro | 5 |
| 31 | Alta de credencial con generador | 7.3 |
| 32 | Edición y rotación de credencial | 7.4 |
| 33 | Búsqueda global | 11 |
| 34 | Vault personal | 10 |
| 35 | Alta en el vault | 10 |
| 36 | Importación y exportación CSV | 12 |
| 37 | Gestión de usuarios | 13 |
| 38 | Alta de usuario | 13.1 |
| 39 | Contraseña temporal | 13.1 |
| 39b | Confirmación del restablecimiento | 13.3 |
| 39c | Temporal enviada al buzón del titular | 13.3 |
| 40 | Métricas de seguridad | 14 |
| 41 | Bitácora de auditoría | 15 |
| 42 | Bitácora filtrada | 15 |
| 43 | Tokens de API | 16 |
| 44 | Token generado | 16.1 |
| 45 / 45b | Configuración en caliente | 17 |
| 45c | Configuración SMTP guardada | 17.1 |
| 45d | Prueba de correo correcta | 17.1 |
| 46 | Recurso no disponible | 5 |
| 47 | Inventario del analista | 9.2 |
| 48 | Activo concedido al analista | 9.2 |
| 49 | Activo sin concesión | 9.2 |
| 50 | Inventario visto por el auditor | 9.4 |
| 51 | Credenciales sin revelado (auditor) | 9.4 |

### Anexo B — Mapa función → interfaz → rol

| Función | Dónde | Rol mínimo |
|---|---|---|
| Iniciar sesión / MFA / recuperación | `/login`, `/mfa/*`, `/recuperar` | cualquiera |
| Pedir un OTP de respaldo por correo | `/mfa/verificar` (interfaz clásica) · `POST /api/web/mfa/otp-correo` | sesión en etapa `mfa_pendiente` |
| Cambiar la contraseña propia | `/password/cambiar` | cualquiera |
| Ver inventario y fichas | `/`, `/servidores/*`, `/hipervisores/*`, `/vms/*`, `/dispositivos/*` | auditor (analista: concedidos) |
| Crear/editar/eliminar activos | Botones de alta y ficha | operador |
| Marcar activo restringido | Edición del activo | admin |
| Ver lista de credenciales | Ficha del activo | auditor (analista: concedidos) |
| Revelar / copiar contraseña | Ficha del activo | operador (analista con nivel «ver y revelar») |
| Crear/editar/rotar/eliminar credencial | Ficha del activo | operador |
| Ver historial de contraseñas | Credencial | operador |
| Ver / editar nota segura | Ficha del activo | operador (ver: auditor) |
| Conceder / revocar accesos | Ficha del activo | admin |
| Vault personal | `/vault` | cualquiera (solo el propio) |
| Búsqueda global | `/buscar`, `Ctrl/⌘+K` | auditor (analista: concedidos) |
| Importar CSV | `/importar` | operador |
| Exportar inventario en claro | `/importar` | operador |
| Gestionar usuarios | `/usuarios` | admin |
| Métricas | `/metricas` | auditor |
| Auditoría y export CSV | `/auditoria` | auditor |
| Tokens de API | `/tokens` | admin |
| Configuración en caliente | `/configuracion` | admin |
| API REST de integración | `/api/v1/*` | token con alcance |
| Respaldo, restauración, recifrado, verificación | CLI | administrador del servidor |

### Anexo C — Documentación relacionada

| Documento | Contenido |
|---|---|
| [`arquitectura.md`](arquitectura.md) | Cómo está construido el sistema |
| [`modelo-datos.md`](modelo-datos.md) | Esquema relacional |
| [`control-acceso.md`](control-acceso.md) | Roles y control de acceso por objeto |
| [`referencia-configuracion.md`](referencia-configuracion.md) | Todas las variables `PASSWD_*` |
| [`referencia-cli.md`](referencia-cli.md) | Comandos de la CLI |
| [`referencia-api-rest.md`](referencia-api-rest.md) | API REST `/api/v1` |
| [`guia-implementacion.md`](guia-implementacion.md) | Instalación, UAT y paso a producción |
| [`guia-nginx-tls.md`](guia-nginx-tls.md) | HTTPS, certificados y rotación |
| [`ambientes.md`](ambientes.md) | Plantillas por ambiente y TLS sin dominio |
| [`notificaciones-y-mfa-correo.md`](notificaciones-y-mfa-correo.md) | Avisos, OTP por correo y reset |
| [`cumplimiento-cis-v8.1.md`](cumplimiento-cis-v8.1.md) · [`cumplimiento-iso-27003.md`](cumplimiento-iso-27003.md) · [`cumplimiento-owasp.md`](cumplimiento-owasp.md) | Matrices de cumplimiento |
| [`glosario-faq.md`](glosario-faq.md) | Glosario y preguntas frecuentes |

### Anexo D — Glosario mínimo

| Término | Significado |
|---|---|
| **MFA / TOTP** | Segundo factor de autenticación mediante código temporal de 6 dígitos (RFC 6238) |
| **Argon2id** | Algoritmo de hash de contraseñas de usuario; no reversible |
| **Fernet (AES)** | Cifrado simétrico usado para las contraseñas de activos, notas y semillas TOTP |
| **RBAC** | Control de acceso basado en roles (qué operaciones permite el rol) |
| **Acceso por objeto** | Control adicional sobre **qué activos concretos** alcanza un usuario |
| **Concesión** | Permiso explícito y temporal de un administrador a un analista sobre un activo |
| **Activo restringido** | Activo oculto a los operadores por decisión del administrador |
| **Rotación** | Cambio periódico de una contraseña; el sistema alerta al superar el umbral |
| **Anti-exfiltración** | Límite de revelados/copiados por usuario y ventana de tiempo |
| **HSTS** | Cabecera que obliga al navegador a usar siempre HTTPS |
| **OTP por correo** | Código de un solo uso enviado al buzón registrado, como segundo factor de respaldo |

### Anexo E — Novedades y parches de la versión en curso

Resumen de lo incorporado desde la 1.1.0 (detalle completo en [`CHANGELOG.md`](../CHANGELOG.md)),
con su implicación operativa. **Léalo antes de aprobar el despliegue.**

| Novedad | Qué cambia para la operación | Dónde en este manual |
|---|---|---|
| **Segundo factor por correo (OTP)** | Nueva vía de respaldo del MFA. Exige decidir si se activa (decisión de riesgo firmada) y tener SMTP operativo | §4.4.1, §17.1, §18.2 |
| **Restablecimiento administrativo con envío automático** | El administrador ya no manipula la contraseña temporal: viaja al buzón del titular y solo ve el destino enmascarado. Si SMTP falla, se le entrega en pantalla y la bitácora lo registra de forma distinguible | §13.3 |
| **Avisos dinámicos por matriz de permisos** | Los usuarios finales empiezan a recibir correos (inicio de sesión, cambios de permisos, credenciales compartidas, rotación próxima). **Anúncielo antes de activarlo** para que no se confundan con phishing; desactivable con `PASSWD_NOTIFY_USERS_ENABLED=false` | §18.1 |
| **Comando `avisar-rotacion`** | Nueva tarea diaria programable, con `--simular` para revisar el alcance sin enviar | §19, §20.7 |
| **Nuevos ajustes en caliente** | `PASSWD_EMAIL_OTP_ENABLED`, `PASSWD_EMAIL_OTP_TTL_MINUTES`, `PASSWD_NOTIFY_USERS_ENABLED`, `PASSWD_ROTATION_WARNING_DAYS` | §17.1 |

**Parches de seguridad incorporados**

| Parche | Qué corrige | Implicación |
|---|---|---|
| **Reutilización del código TOTP de enrolamiento** (severidad alta; OWASP A07, RFC 6238 §5.2) | Una asimetría de normalización permitía que **el mismo código de 6 dígitos se aceptara dos veces** durante su ventana de validez (hasta ~90 s) —el ataque de *replay* con proxy de intercepción—. Ahora la forma canónica del código vive en una única función por la que pasan los seis puntos que manipulan un TOTP | Sin acción del operador: se corrige al actualizar. Refuerza el control descrito en §4.4 |
| **Reducción de la exposición del código fuente** (OWASP A05) | Mapas de origen desactivados y bloqueados en nginx (`*.map`, `*.ts`, `*.tsx`), 404 a rutas que empiezan por punto (`/.git/`, `/.env`), sin trazas de pila en la consola del navegador, sin `X-Powered-By`, `X-Robots-Tag: noindex` | Verifíquelo tras el despliegue (§20.5 y lista de §22). No impide leer el *bundle*: eso es imposible por diseño del navegador |
| **Control automático del build del frontend** | `scripts/verificar-build-frontend.sh` falla el CI si aparecen mapas de origen, patrones de secretos o rutas absolutas de la máquina de compilación en `.next/static` o `public/` | Manténgalo en el pipeline; es la red de seguridad del punto anterior |
| **Batería contra el salto del MFA** | 20 pruebas que atacan **todas** las rutas registradas desde sesiones detenidas en cada etapa previa a `activa`, de modo que un endpoint nuevo sin dependencia de sesión rompe la suite | Ejecute `pytest` en cada actualización antes de promover a producción (§21.7) |

### Anexo F — Cobertura por interfaz y limitaciones conocidas

El sistema ofrece dos interfaces con el **mismo backend y el mismo modelo de seguridad**: el
**frontend Next.js** (recomendado en producción, el que ilustra este manual) y la **interfaz clásica
Jinja** que sirve el propio backend. Dos funciones de la última versión están hoy **solo** en la
interfaz clásica y en la API:

| Función | Backend / API | Interfaz clásica (Jinja) | Frontend Next.js |
|---|:-:|:-:|:-:|
| Segundo factor por correo (OTP) | ✔ `POST /api/web/mfa/otp-correo`, `GET /api/web/mfa/metodos` | ✔ botón **Enviarme un código por correo** | ✘ la pantalla de verificación solo ofrece TOTP y códigos de recuperación |
| Restablecimiento con envío al titular | ✔ devuelve `correo_enviado` y `destino` enmascarado | ✔ muestra «se envió a su correo registrado (j\*\*\*\*\*\*\*\*o@empresa.tld)» | ⚠ el envío **sí ocurre**, pero el diálogo no lo refleja y muestra el campo de contraseña vacío |

**Consecuencias prácticas mientras esto no se ajuste:**

1. Si activa el OTP por correo, publique también el acceso a la interfaz clásica (o instruya a los
   usuarios para usarla en ese caso concreto); de lo contrario la vía de respaldo no es alcanzable
   desde el frontend.
2. Al restablecer una contraseña desde el frontend Next.js, **el campo vacío no indica un fallo**:
   la contraseña temporal ya fue enviada al buzón del titular. Confírmelo en la bitácora
   (`usuario_actualizado`, con el detalle «enviada a su correo»). Para ver el destino enmascarado,
   realice la operación desde la interfaz clásica.

> Ambos puntos son ajustes de interfaz, no de seguridad: la autorización, la auditoría y el envío
> se resuelven en el backend, que ya está completo. Deben resolverse antes de retirar la interfaz
> clásica del despliegue.

---

*Fin del documento. Cualquier modificación de este manual requiere nueva revisión y aprobación.*
