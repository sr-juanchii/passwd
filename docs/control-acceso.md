# Control de acceso: roles y concesiones por activo

El sistema combina tres capas de autorización que se evalúan **en cada petición**
contra la base de datos (nada se confía al navegador):

1. **RBAC por tipo de operación** (`app/rbac.py`): qué clase de acción permite un rol.
2. **Control de acceso por objeto — concesiones** (`app/access.py`): para el rol *analista*,
   sobre qué activos concretos puede operar, según las concesiones que un administrador le otorgue.
3. **Control de acceso por objeto — restricciones** (`app/access.py`): un administrador puede
   marcar un activo como **restringido**, ocultándolo a los operadores (ver más abajo).

## Roles

| Rol | Alcance |
|---|---|
| **admin** | Control total. Único que gestiona usuarios, **concede/revoca accesos** y **restringe activos**. |
| **operador** | Gestiona el inventario y las credenciales, **excepto** los activos restringidos a administradores. |
| **auditor** | Lectura total del inventario (incluidos los restringidos) y de la bitácora; **nunca** revela contraseñas. |
| **analista** | *Default-deny*: **no ve nada** hasta que un admin le concede acceso a activos concretos. |

## Permisos de la gobernanza de rotación (desde la 1.3.0)

Cambiar la contraseña de una credencial del inventario ya no es una edición: es un ciclo de
autorización con dos personas (ver [`manual-administrador.md`](manual-administrador.md) §4 bis).
Lo gobiernan cuatro permisos nuevos:

| Permiso | admin | operador | auditor | analista |
|---|:-:|:-:|:-:|:-:|
| `rotacion.ver` | ✔ | ✔ (†) | ✔ | ✘ |
| `rotacion.solicitar` | ✔ | ✔ (†) | ✘ | ✘ |
| `rotacion.autorizar` | ✔ **otro** admin; jamás la propia | ✘ | ✘ | ✘ |
| `rotacion.revisar` | ✔ **otro** admin | ✘ | ✘ | ✘ |

`rotacion.solicitar` **no introduce un modelo nuevo de responsabilidad por activo**. Alcanza
exactamente las credenciales que el rol ya puede gestionar hoy, de modo que los activos
restringidos siguen siendo inexistentes para el operador (†) y el analista sigue fuera del ciclo.
Añadir responsabilidad nominal por activo sería una funcionalidad propia, con su modelo y su
interfaz, y está declarada fuera del alcance de esta serie.

Dos reglas no se expresan con permisos, porque un permiso dice *qué rol* y aquí lo que importa es
*qué persona*. Las aplica el servicio (`app/servicios/rotacion.py`):

- **Nadie autoriza su propia solicitud.** La única salida es la vía de emergencia, acotada a una
  ventana corta, marcada de forma imborrable y con revisión obligatoria posterior.
- **La revisión de una emergencia la cierra otro administrador**, nunca quien la autorizó: si
  pudiera cerrarla él, la marca no obligaría a nada.

## Permisos de los agentes de rotación (desde la 1.4.0)

Un agente es una **identidad de máquina** que podrá recibir las contraseñas nuevas de un servidor.
Lo gobiernan dos permisos nuevos (`app/rbac.py`):

| Permiso | admin | operador | auditor | analista |
|---|:-:|:-:|:-:|:-:|
| `agentes.ver` | ✔ | ✔ (†) | ✔ | ✘ |
| `agentes.gestionar` | ✔ | ✘ | ✘ | ✘ |

- **`agentes.ver`** abre el menú **Agentes**, la insignia de cobertura y el panel del agente en la
  ficha del activo. Sirve a quien opera y a quien supervisa; no da acceso a ningún secreto.
- **`agentes.gestionar`** da de alta un agente, reemite su token de instalación, lo revoca y
  decide si una credencial se rota **con el agente** o **a mano**. Crea o retira identidades de
  máquina: solo administradores.
- Los agentes **no amplían la gobernanza**: despachar el trabajo de una rotación autorizada
  («Enviar al agente») exige `rotacion.solicitar`, y resolver una rotación «sin confirmar» exige
  `rotacion.autorizar`, como autorizarla.

**Reautenticación (contraseña + código de la aplicación autenticadora).** El servicio la exige,
con el mismo mecanismo que autorizar una rotación (el código por correo no sirve), para:

| Acción | Por qué |
|---|---|
| Dar de alta un agente | Crea una identidad que podrá recibir contraseñas de ese servidor: una sesión de administrador robada no debe bastar para plantarla. |
| Reemitir su token de instalación («Reinstalar») | Ídem, y además anula la identidad vigente del agente. |
| Resolver una rotación «sin confirmar» | Puede escribir una contraseña en el inventario. |

**Revocar no la pide**: protege. Cada reautenticación fallida queda en la bitácora como
`acceso_denegado` y sobrevive al rollback de la petición.

**Control de acceso por objeto.** Un agente pertenece a **un** activo y hereda su visibilidad: el
agente de un activo restringido **no existe** (404, el mismo que si no existiera) para quien no
alcanza el activo, igual que el activo mismo. Lo mismo vale para la lista de `/agentes`, los
recuentos de **Métricas**, las rotaciones «sin confirmar» del panel de **Rotación** y la vista del
trabajo en curso de una credencial.

El propio agente **no es un usuario**: no tiene rol ni sesión, se autentica en `/api/agent` con su
token de vida corta y solo ve los trabajos de su activo. Ver
[`arquitectura-agentes.md`](arquitectura-agentes.md) y [`contrato-agente.md`](contrato-agente.md).

## Restricciones a administradores (`restringido`)

Además de las concesiones (que *abren* acceso al analista), el administrador puede **cerrar**
el acceso de los operadores a activos sensibles. Marcando un servidor físico, hipervisor o
dispositivo de red como **restringido** (permiso `inventario.restringir`, exclusivo de
administradores):

- El **operador** deja de verlo por completo: no aparece en el inventario, la búsqueda ni el
  export, y su detalle responde **404** (como si no existiera). Tampoco puede crear, editar,
  eliminar ni revelar sus credenciales o notas.
- El **auditor sí lo ve** (su función es supervisar el inventario completo) pero, como con
  cualquier activo, **no puede revelar contraseñas**.
- El **analista** solo lo ve si tiene una **concesión explícita**: la concesión que otorga el
  propio administrador **prevalece** sobre la restricción (es una decisión deliberada).
- Las **máquinas virtuales heredan** la restricción de su hipervisor (la restricción *sí*
  hereda hacia abajo, al contrario que las concesiones).

Cada cambio de la marca queda auditado (`activo_restriccion_cambiada`). El operador puede
seguir enviando el campo en formularios o CSV, pero el sistema lo **ignora** salvo que quien
opere sea administrador.

## Concesiones (`ConcesionAcceso`)

Un administrador concede a un analista acceso a **un activo concreto** (servidor físico,
hipervisor o máquina virtual) con:

- **Nivel**:
  - `ver` — ve el activo y la lista de credenciales (usuario, servicio, puerto, descripción),
    **sin** las contraseñas.
  - `ver_credenciales` — además puede **revelar/copiar** las contraseñas de ese activo.
- **Caducidad opcional** (`expira_en`): al vencer, la concesión se ignora automáticamente.

### Reglas de seguridad

- **Sin herencia**: conceder un servidor físico **no** da acceso a sus hipervisores ni VMs;
  cada activo se concede por separado (least privilege, sin sorpresas).
- **Default-deny**: sin concesión vigente, un analista recibe **404** al pedir un activo
  (no se filtra siquiera su existencia → defensa contra IDOR/BOLA, OWASP API1).
- **Nivel insuficiente**: si tiene `ver` pero intenta revelar, recibe **403**.
- **Revocación inmediata**: revocar borra la concesión; surte efecto en la siguiente petición.
  La traza histórica (quién concedió/revocó, cuándo, sobre qué) vive en la **bitácora de
  auditoría** (`acceso_concedido` / `acceso_revocado`), no en filas marcadas.
- **Las credenciales no cambian su blindaje**: siguen cifradas en reposo (Fernet), se
  descifran solo en el servidor al revelar/copiar, cada acceso queda **auditado** (con la
  marca «vía concesión» cuando es un analista) y sujeto al **límite anti-exfiltración por
  usuario**. Los analistas no tienen export ni respaldo.

## Cómo conceder acceso (administrador)

1. Cree el usuario con rol **analista** en *Usuarios → + Usuario* (recibe contraseña temporal;
   en su primer acceso cambia la contraseña y enrola MFA, como cualquier usuario).
2. Abra el detalle del activo (servidor físico, hipervisor o VM). Al final verá el panel
   **«Accesos de analistas»**.
3. Elija el analista, el **nivel** y, si procede, los **días de caducidad**; pulse *Conceder*.
4. Para retirar el acceso, pulse *Revocar* en la fila correspondiente.

El analista verá en su panel principal **«Mis accesos»**: la lista de activos concedidos, con
enlace al detalle de cada uno.

## Endpoints

| Método y ruta | Permiso | Acción |
|---|---|---|
| `POST /accesos/conceder` | `accesos.gestionar` (admin) | Concede o actualiza una concesión (upsert por usuario+activo). |
| `POST /accesos/{id}/revocar` | `accesos.gestionar` (admin) | Revoca (borra) una concesión. |
| Campo `restringido` en crear/editar activo | `inventario.restringir` (admin) | Marca/desmarca un activo como restringido a administradores. |
| `GET /api/web/rotacion/panel` | `rotacion.ver` | Pendientes de autorizar, de aplicar, revisiones y señales de patrón. |
| `GET /api/web/rotacion/credenciales/{id}` | `rotacion.ver` | Línea de tiempo de gobernanza de una credencial. |
| `POST /api/web/rotacion/solicitudes` | `rotacion.solicitar` | Abre el ciclo con motivo y tipo. |
| `POST /api/web/rotacion/solicitudes/{id}/autorizar` | `rotacion.autorizar` | Autoriza; exige reautenticación con TOTP. |
| `POST /api/web/rotacion/solicitudes/autorizar-lote` | `rotacion.autorizar` | Igual, con una sola reautenticación para varias solicitudes. |
| `POST /api/web/rotacion/solicitudes/{id}/rechazar` | `rotacion.autorizar` | Rechaza con motivo. |
| `POST /api/web/rotacion/solicitudes/{id}/cancelar` | `rotacion.solicitar` | Retira la solicitud (propia; el admin, cualquiera). |
| `POST /api/web/rotacion/solicitudes/{id}/aplicar-manual` | `rotacion.solicitar` | Registra la contraseña aplicada en el activo y cierra el ciclo. |
| `POST /api/web/rotacion/solicitudes/{id}/revisar` | `rotacion.revisar` | Cierra la revisión de una emergencia sin segundo par. |
| `POST /api/web/rotacion/solicitudes/{id}/despachar` | `rotacion.solicitar` | Vuelve a enviar al agente una rotación ya **autorizada** (1.4.0). No añade autoridad. |
| `POST /api/web/rotacion/trabajos/{id}/resolver` | `rotacion.autorizar` | Dice qué contraseña quedó tras un «sin confirmar»; exige reautenticación con TOTP (1.4.0). |
| `GET /api/web/agentes` | `agentes.ver` | Agentes con su cobertura (`?revocados=true` incluye los revocados). |
| `GET /api/web/agentes/activo/{tipo}/{id}` | `agentes.ver` | Insignia de cobertura y agente de un activo. |
| `POST /api/web/agentes` | `agentes.gestionar` | Da de alta el agente de un activo; exige reautenticación. El token de instalación se devuelve **una vez**. |
| `POST /api/web/agentes/{id}/enrolamiento` | `agentes.gestionar` | Reemite el token de instalación y anula la identidad vigente; exige reautenticación. |
| `POST /api/web/agentes/{id}/revocar` | `agentes.gestionar` | Revoca el agente; sus credenciales vuelven a rotarse a mano. |
| `POST /api/web/agentes/credenciales/{id}/via` | `agentes.gestionar` | Cambia la vía de rotación de una credencial (`agente` o `manual`). |

En todos ellos, el control de acceso **por objeto** se resuelve además en la frontera: una
solicitud sobre un activo restringido es inexistente (404) para quien no alcanza ese activo, igual
que el activo mismo.

## Notas de despliegue

La tabla `concesiones_acceso` se crea automáticamente al arrancar (`create_all`). El rol
`analista` se añadió a la restricción `CHECK` de `usuarios.rol`: las bases creadas con una
versión anterior deben **recrearse** (entorno de pruebas/preproducción, datos desechables) o
migrarse antes de crear analistas. Para migraciones sobre bases con datos en producción el
proyecto ya incorpora **Alembic** (ver [`guia-desarrollo.md`](guia-desarrollo.md) §7): los
cambios no aditivos futuros se entregan como revisiones versionadas.
