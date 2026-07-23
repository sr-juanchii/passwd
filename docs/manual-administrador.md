# Manual del administrador

**Sistema:** Gestor de Contraseñas de Servidores
**Audiencia:** personas con rol **admin** (y, donde se indica, **auditor**).
**Alcance:** las tareas de administración del día a día desde la interfaz. Para la **instalación**
y el **despliegue** consulte [`guia-implementacion.md`](guia-implementacion.md); para el uso general
del inventario y las credenciales, el [`manual-usuario.md`](manual-usuario.md).

> El administrador es el único rol que gestiona usuarios, concede/revoca accesos por activo y
> administra los tokens de API. El auditor puede ver la bitácora y las métricas, pero no revela
> contraseñas ni gestiona el inventario.

---

## 1. Gestión de usuarios

Menú **Usuarios** (requiere `usuarios.gestionar`, solo admin).

### 1.1 Crear un usuario

1. **Usuarios → + Usuario**.
2. Indique **usuario**, **correo**, **nombre completo** y **rol** (admin, operador, auditor o
   analista).
3. Al guardar, el sistema genera una **contraseña temporal de un solo uso** y la muestra una vez.
   Entréguesela al usuario por un canal seguro.
4. En su primer acceso, el usuario pasará por el circuito obligatorio: **cambio de contraseña +
   enrolamiento MFA + códigos de recuperación** (ver [`manual-usuario.md`](manual-usuario.md) §2).

### 1.2 Acciones sobre una cuenta

| Acción | Efecto |
|---|---|
| **Cambiar rol** | Actualiza el rol y **revoca al instante** todas las sesiones vivas del usuario. |
| **Desactivar** | El usuario no puede entrar; sus sesiones se revocan inmediatamente. La cuenta se conserva (para la auditoría). |
| **Reactivar** | Vuelve a permitir el acceso. |
| **Restablecer contraseña** | Emite una nueva **contraseña temporal** y fuerza su cambio; desbloquea la cuenta. |
| **Reiniciar MFA** | Borra el segundo factor: el usuario re-enrola MFA en su próximo acceso y se le emiten **nuevos códigos de recuperación**; revoca sesiones. |

> **Baja de personal:** desactive la cuenta (corta el acceso de inmediato) y **rote las
> credenciales de los activos** que esa persona pudo haber revelado. La bitácora permite filtrar
> los eventos `credencial_revelada` por usuario para saber cuáles.

### 1.3 Incidentes de acceso frecuentes

| Situación | Procedimiento |
|---|---|
| Cuenta bloqueada (5 intentos) | Esperar 15 min, o **Restablecer contraseña** (desbloquea y emite temporal). |
| Dispositivo MFA perdido | El usuario entra con un **código de recuperación**; si no le quedan, **Reiniciar MFA**. |
| Códigos de recuperación agotados | **Reiniciar MFA** → nuevo juego al re-enrolar. |
| Olvido de contraseña | **Restablecer contraseña** → temporal de un solo uso. |

---

## 2. Roles y control de acceso por objeto

Los cuatro roles y la matriz de permisos están en [`control-acceso.md`](control-acceso.md). Aquí lo
operativo del rol **analista** (*default-deny*: no ve nada hasta que se le concede acceso).

### 2.1 Conceder acceso a un analista

1. Cree el usuario con rol **analista** (§1.1).
2. Abra el **detalle del activo** (servidor físico, hipervisor, VM o dispositivo de red). Al
   final verá el panel **«Accesos de analistas»** (en el frontend, la pestaña/sección de accesos).
3. Elija el analista, el **nivel** y, si procede, los **días de caducidad**; pulse **Conceder**.
   - **Ver** — ve el activo y la lista de credenciales (usuario, servicio, puerto, descripción),
     **sin** las contraseñas.
   - **Ver credenciales** — además puede **revelar/copiar** las contraseñas de ese activo.
4. Para retirar el acceso, pulse **Revocar** en la fila correspondiente (efecto inmediato).

### 2.2 Reglas que conviene recordar

- **Sin herencia:** conceder un servidor físico no da acceso a sus hipervisores ni VMs (ni a los
  dispositivos de red); cada activo se concede por separado.
- **Default-deny:** sin concesión vigente, el analista recibe **404** (ni siquiera se filtra la
  existencia del activo).
- **Caducidad:** al vencer `expira_en`, la concesión deja de surtir efecto automáticamente.
- La traza de quién concedió/revocó qué y cuándo vive en la **bitácora** (`acceso_concedido` /
  `acceso_revocado`).

---

## 3. Auditoría (bitácora)

Menú **Auditoría** (requiere `auditoria.ver`: admin y auditor).

- **Filtros** por usuario y por acción; **paginación** de 50 registros.
- Cada registro incluye: fecha (UTC), usuario, acción, tipo y ID de objeto, detalle, IP, agente y
  resultado (éxito/fallo).
- **Exportar CSV:** botón de exportación; descarga el conjunto **filtrado**. La exportación se
  audita y las celdas se sanean contra **inyección de fórmulas** (Excel/Sheets).

Acciones típicas a vigilar (revisión semanal recomendada, ver
[`guia-implementacion.md`](guia-implementacion.md) §5.1): `login_fallido`, `cuenta_bloqueada`,
`acceso_denegado`, `credencial_revelada`/`credencial_copiada` inusuales y `revelado_tasa_excedida`.

> La retención por defecto es de 365 días y **nunca baja de 90** aunque se configure menos
> (CIS 8.10). Se purga automáticamente al arrancar la aplicación.

---

## 4. Métricas de seguridad

Menú **Métricas** (requiere `metricas.ver`: admin y auditor). Panel de apoyo a la revisión que
resume:

- **Rotación vencida:** credenciales que superan el umbral (90 días por defecto) sin rotarse.
- **Logins fallidos** en las últimas 24 h y 7 días.
- **Usuarios bloqueados** en este momento.
- **Cuentas sin MFA** (deberían ser cero salvo durante un re-enrolamiento).
- **Top de accesos a credenciales** (últimos 30 días).
- **Concesiones por caducar.**

---

## 5. Tokens de API (integración con SIEM/automatización)

Menú **Tokens** (requiere `tokens.gestionar`, solo admin). Los tokens dan acceso a la **API REST de
solo lectura** (`/api/v1`), que **nunca** expone secretos. Detalle técnico en
[`referencia-api-rest.md`](referencia-api-rest.md).

1. **Crear token:** indique un **nombre** descriptivo; el sistema muestra el valor del token
   **una sola vez**. Cópielo y guárdelo de forma segura (en BD solo queda su hash).
2. **Revocar:** desactiva el token; las peticiones con él dejan de funcionar de inmediato.
3. La lista muestra el **último uso** de cada token para detectar tokens olvidados.

> Use los tokens siempre **sobre TLS**. Un token comprometido solo permite **leer** inventario y
> auditoría (sin contraseñas), pero conviene revocarlo igualmente.

---

## 6. Importación masiva por CSV

Menú **Importar** (requiere `inventario.gestionar`: admin y operador).

- Suba un **CSV** con activos y/o credenciales. El archivo se procesa **en memoria** (no se
  persiste) y las contraseñas se **cifran al guardar**.
- Los **errores por fila no abortan** la importación: al final se muestra un resumen con lo creado
  (servidores, hipervisores, dispositivos de red, VMs, credenciales) y la lista de errores.
- La operación queda auditada.

El CSV usa una columna `tipo` (`servidor`/`hipervisor`/`dispositivo`/`vm`/`credencial`) y, para las
VMs y credenciales, una referencia al activo padre (en credenciales, `activo_tipo` acepta también
`dispositivo`). Los dispositivos de red usan además `tipo_dispositivo`, `version` (firmware) y
`puertos`. Tras importar, revise el inventario y rote o complete las credenciales que lo necesiten.

---

## 7. Respaldo y restauración

Operación de **CLI** (no desde la web). Referencia completa en
[`referencia-cli.md`](referencia-cli.md); operación recomendada en
[`guia-implementacion.md`](guia-implementacion.md) §4.7.

```bash
# Crear un respaldo cifrado (pide una frase de mín. 16 caracteres)
python -m app.cli respaldo --salida copia.passwd

# Restaurar (sobre una instancia, posiblemente con claves distintas)
python -m app.cli restaurar --entrada copia.passwd --sobrescribir
```

- El archivo incluye usuarios, inventario, credenciales, códigos de recuperación y bitácora,
  cifrado con una clave derivada de la frase (**scrypt + Fernet**). Es **portable** entre
  instancias.
- **Sin la frase, el respaldo es irrecuperable**: custódiela aparte del archivo (gestor de secretos
  / sobre sellado).
- Para respaldos desatendidos (cron), defina `PASSWD_BACKUP_PASSPHRASE` y use `--retener N`.

---

## 8. Buenas prácticas operativas

- **Menor privilegio:** asigne el rol más bajo que permita la tarea (operador para gestión diaria,
  auditor para revisión, analista con concesiones puntuales).
- **Retire `PASSWD_ADMIN_PASSWORD`** del `.env` tras el primer arranque (solo se usa si la BD está
  vacía).
- **Custodie las claves** `PASSWD_SECRET_KEY` y `PASSWD_ENCRYPTION_KEY` y la frase de respaldo fuera
  del servidor. Perder la clave de cifrado = perder todas las contraseñas guardadas (salvo el
  respaldo cifrado).
- **Prueba de restauración trimestral** en una máquina aparte.
- **Revise la bitácora** con la cadencia de [`guia-implementacion.md`](guia-implementacion.md) §5.1.

---

## 9. Documentos relacionados

- [`manual-usuario.md`](manual-usuario.md) — uso general (todos los roles).
- [`control-acceso.md`](control-acceso.md) — roles y concesiones por activo.
- [`referencia-cli.md`](referencia-cli.md) — comandos de línea de comandos.
- [`referencia-api-rest.md`](referencia-api-rest.md) — API REST de solo lectura.
- [`guia-implementacion.md`](guia-implementacion.md) — instalación, producción y operación.
</content>
