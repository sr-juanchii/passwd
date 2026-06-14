# Control de acceso: roles y concesiones por activo

El sistema combina dos capas de autorización que se evalúan **en cada petición**
contra la base de datos (nada se confía al navegador):

1. **RBAC por tipo de operación** (`app/rbac.py`): qué clase de acción permite un rol.
2. **Control de acceso por objeto** (`app/access.py`): para el rol *analista*, sobre qué
   activos concretos puede operar, según las concesiones que un administrador le otorgue.

## Roles

| Rol | Alcance |
|---|---|
| **admin** | Control total. Único que gestiona usuarios y **concede/revoca accesos**. |
| **operador** | Gestiona todo el inventario y todas las credenciales (visibilidad total). |
| **auditor** | Lectura total del inventario y de la bitácora; **nunca** revela contraseñas. |
| **analista** | *Default-deny*: **no ve nada** hasta que un admin le concede acceso a activos concretos. |

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

## Notas de despliegue

La tabla `concesiones_acceso` se crea automáticamente al arrancar (`create_all`). El rol
`analista` se añadió a la restricción `CHECK` de `usuarios.rol`: las bases creadas con una
versión anterior deben **recrearse** (entorno de pruebas/preproducción, datos desechables) o
migrarse antes de crear analistas. Para migraciones sobre bases con datos en producción se
recomienda introducir Alembic (pendiente, ver el plan de evolución).
