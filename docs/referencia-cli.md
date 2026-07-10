# Referencia de la CLI

Utilidades administrativas de línea de comandos del **Gestor de Contraseñas de Servidores**,
implementadas en [`app/cli.py`](../app/cli.py). Sirven para inicializar la base de datos, crear el
administrador inicial y hacer **respaldos/restauraciones cifradas**.

## Invocación

```bash
python -m app.cli <comando> [opciones]
```

Con Docker, dentro del contenedor de la app:

```bash
docker compose exec app python -m app.cli <comando> [opciones]
```

La CLI usa la **misma configuración** (`PASSWD_*`) y la **misma base de datos** que la aplicación
web. Llama a `init_db()` antes de operar, de modo que crea/concilia el esquema si hace falta.

| Comando | Para qué sirve |
|---|---|
| `init-db` | Crear las tablas de la base de datos. |
| `crear-admin` | Crear una cuenta de administrador. |
| `respaldo` | Exportar un respaldo cifrado de todo el sistema. |
| `restaurar` | Restaurar un respaldo cifrado. |
| `recifrar` | Recifrar todos los secretos con la clave primaria (rotación de la clave de cifrado). |
| `exportar-csv` | Exportar el inventario **en claro** a CSV para migración (formato del importador). |

Todos devuelven **código de salida 0** si tienen éxito y **1** ante un error (con el motivo en
`stderr`).

---

## `init-db`

Crea las tablas que falten (idempotente).

```bash
python -m app.cli init-db
```

Normalmente no hace falta ejecutarlo a mano: la aplicación inicializa el esquema al arrancar. Útil
para preparar la base de datos antes de un primer arranque o en scripts.

---

## `crear-admin`

Crea una cuenta de **administrador**. Pensado para arrancar el sistema sin pasar por las variables
`PASSWD_ADMIN_*`, o para crear un admin adicional.

```bash
python -m app.cli crear-admin --username admin --email admin@su-organizacion.tld
```

| Opción | Obligatoria | Por defecto | Descripción |
|---|:-:|---|---|
| `--username` | sí | — | Nombre de usuario (se normaliza a minúsculas). |
| `--email` | sí | — | Correo electrónico. |
| `--nombre` | no | `"Administrador"` | Nombre completo mostrado. |
| `--password` | no | — | Contraseña temporal. **Si se omite, se solicita de forma interactiva** (sin eco). |

- La contraseña debe **cumplir la política** (mín. 12 caracteres, no común, sin el username); si no,
  se rechaza con el motivo.
- Si ya existe un usuario con ese nombre, falla sin crear nada.
- La cuenta nace con **cambio de contraseña forzado**: en su primer acceso deberá cambiarla y
  **enrolar MFA**.

> Pasar la contraseña por `--password` puede dejarla en el historial del shell. Prefiera el modo
> interactivo cuando sea posible.

---

## `respaldo`

Exporta **todo el sistema** (usuarios, códigos de recuperación, inventario, credenciales y bitácora)
a un único archivo **cifrado** con una clave derivada de una frase (**scrypt + Fernet**).

```bash
python -m app.cli respaldo --salida copia.passwd
```

| Opción | Obligatoria | Por defecto | Descripción |
|---|:-:|---|---|
| `--salida` | sí | — | Ruta del archivo de respaldo a crear (se escribe con permisos `0600`). |
| `--passphrase` | no | — | Frase de cifrado. Si se omite, se usa `PASSWD_BACKUP_PASSPHRASE` o se **solicita interactivamente** (con confirmación). |
| `--retener N` | no | `0` (sin poda) | Conserva solo los **N** respaldos `*.passwd` más recientes del directorio de salida y elimina el resto. |

**Resolución de la frase** (en este orden): `--passphrase` → variable `PASSWD_BACKUP_PASSPHRASE` →
solicitud interactiva. La frase debe tener al menos **16 caracteres**.

- El respaldo es **portable**: puede restaurarse en otra instancia aunque tenga claves de cifrado
  distintas, siempre que se conozca la frase.
- **Sin la frase, el archivo es irrecuperable.** Custódiela aparte del respaldo.
- Si el respaldo falla y las notificaciones están activas, se envía una **alerta por correo**.
- **Formato v2**: el archivo declara sus parámetros de derivación (scrypt `n=2^17`) y se validan
  con topes de cordura al abrirlo. Los respaldos **v1** existentes (creados con versiones
  anteriores, scrypt `n=2^14` y frase mínima de 12) **siguen siendo restaurables**.

### Ejemplo: respaldo desatendido por cron

```bash
# /etc/cron.d/passwd-respaldo  (la frase viene de PASSWD_BACKUP_PASSPHRASE en el .env)
30 2 * * * root cd /srv/passwd && docker compose exec -T app \
  python -m app.cli respaldo --salida /srv/passwd/data/respaldo-$(date +\%F).passwd --retener 30
```

---

## `restaurar`

Restaura un respaldo cifrado. **Reemplaza** el contenido actual de la base de datos.

```bash
python -m app.cli restaurar --entrada copia.passwd --sobrescribir
```

| Opción | Obligatoria | Por defecto | Descripción |
|---|:-:|---|---|
| `--entrada` | sí | — | Ruta del archivo de respaldo a leer. |
| `--passphrase` | no | — | Frase de cifrado (misma resolución que en `respaldo`, **sin** confirmación). |
| `--sobrescribir` | no | desactivado | **Obligatorio si la base de datos no está vacía**: confirma que se reemplazan los datos existentes. |

- Si la frase es incorrecta o el archivo está corrupto, la restauración **falla sin tocar** los
  datos (el HMAC de Fernet detecta la manipulación).
- Al terminar, imprime un **resumen** con la cantidad restaurada de cada entidad (usuarios,
  servidores, hipervisores, VMs, credenciales, auditoría).

---

## `recifrar`

Reescribe **todos los secretos cifrados** (contraseñas de credenciales, historial, semillas TOTP
y notas de los tres tipos de activo) con la **clave primaria** de `PASSWD_ENCRYPTION_KEY`. Es el
mecanismo de **rotación de la clave de cifrado sin restaurar respaldos**: la variable admite
varias claves separadas por comas y la primera es la que cifra (las demás solo descifran).

```bash
python -m app.cli recifrar
```

### Rotación de la clave de cifrado (procedimiento)

Si sospecha que `PASSWD_ENCRYPTION_KEY` se ha comprometido (o toca rotarla por política):

```bash
# 0) respaldo previo, por prudencia
python -m app.cli respaldo --salida previa-rotacion.passwd

# 1) generar la clave nueva y anteponerla a la actual (la nueva CIFRA, la vieja aún DESCIFRA)
#    .env:  PASSWD_ENCRYPTION_KEY=<nueva>,<antigua>
#    reiniciar la app para que tome el cambio

# 2) recifrar todo el material con la clave nueva
python -m app.cli recifrar

# 3) dejar SOLO la clave nueva y reiniciar
#    .env:  PASSWD_ENCRYPTION_KEY=<nueva>

# 4) destruir la clave antigua de forma segura y registrar la operación
```

Imprime cuántos valores recifró por tabla y termina con código 0. Si ninguna clave configurada
puede descifrar algún valor, falla **sin escribir cambios** (todo o nada).

---

## `exportar-csv`

Exporta **todo el inventario** (servidores, hipervisores, VMs y credenciales) a un CSV con las
contraseñas **en claro**, en el **mismo formato que acepta `importar`**: pensado para editar la
información y migrarla entre versiones (round-trip). **No** incluye los vaults personales (privados
de cada usuario).

```bash
python -m app.cli exportar-csv --salida inventario.csv
```

| Opción | Obligatoria | Descripción |
|---|:-:|---|
| `--salida` | sí | Ruta del CSV a crear (se escribe con permisos `0600`). |

- La operación queda **auditada** (`inventario_exportado`).
- El archivo **contiene contraseñas en claro**: custódielo por un canal seguro y **destrúyalo** tras
  la migración. Desde la interfaz web equivale al botón «Exportar inventario en claro» de *Importar*
  (permiso `inventario.exportar`); la plantilla vacía está en `GET /plantilla.csv`.

---

## Documentos relacionados

- [`referencia-configuracion.md`](referencia-configuracion.md) — variables `PASSWD_*`.
- [`manual-administrador.md`](manual-administrador.md) — operación desde la interfaz.
- [`guia-implementacion.md`](guia-implementacion.md) §4.4 y §4.7 — claves y respaldos en producción.
</content>
