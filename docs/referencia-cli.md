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
solicitud interactiva. La frase debe tener al menos 12 caracteres.

- El respaldo es **portable**: puede restaurarse en otra instancia aunque tenga claves de cifrado
  distintas, siempre que se conozca la frase.
- **Sin la frase, el archivo es irrecuperable.** Custódiela aparte del respaldo.
- Si el respaldo falla y las notificaciones están activas, se envía una **alerta por correo**.

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

### Rotación de la clave de cifrado (caso de uso)

Si sospecha que `PASSWD_ENCRYPTION_KEY` se ha comprometido:

```bash
python -m app.cli respaldo --salida rotacion.passwd        # 1) respaldo con frase fuerte
# 2) cambiar PASSWD_ENCRYPTION_KEY en .env y reiniciar la app
python -m app.cli restaurar --entrada rotacion.passwd --sobrescribir   # 3) restaurar (re-cifra con la clave nueva)
# 4) destruir rotacion.passwd de forma segura y registrar la operación
```

---

## Documentos relacionados

- [`referencia-configuracion.md`](referencia-configuracion.md) — variables `PASSWD_*`.
- [`manual-administrador.md`](manual-administrador.md) — operación desde la interfaz.
- [`guia-implementacion.md`](guia-implementacion.md) §4.4 y §4.7 — claves y respaldos en producción.
</content>
