# Contrato de la API JSON (`/api/web`)

Esta API JSON vive en el backend FastAPI (módulo `app/api_web/`) y es consumida por el
frontend Next.js. **Reutiliza exactamente** el modelo de seguridad existente:

- **Sesión por cookie** `passwd_session` (HttpOnly, SameSite=Strict). Idéntica a la web Jinja.
- **CSRF**: cada sesión tiene `csrf_token`. Las mutaciones (POST/PUT/DELETE) deben enviar la
  cabecera `X-CSRF-Token` con ese valor. Se valida con `hmac.compare_digest` contra
  `sesion.csrf_token`. Para el login se usa doble cookie (`passwd_csrf_login`).
- **RBAC** (`app.rbac.tiene_permiso`) + **control de acceso por objeto** (`app.access`).
- **Auditoría** (`app.audit.registrar`), **rate limit** (`app.security.ratelimit`),
  **cifrado Fernet** y todas las reglas de negocio se reutilizan tal cual.

Respuestas de error: JSON `{ "detail": "mensaje" }` con el código HTTP apropiado
(401 no autenticado, 403 sin permiso/CSRF, 404 no existe, 409 conflicto, 423 bloqueado,
429 límite de tasa, 400 validación). Las respuestas con secretos llevan `Cache-Control: no-store`.

Todas las rutas cuelgan de `/api/web`.

## Sesión / autenticación

| Método | Path | Cuerpo | Devuelve |
|---|---|---|---|
| GET | `/csrf` | — | Fija cookie `passwd_csrf_login`; `{ "csrf_login": "..." }` |
| POST | `/login` | `{username, password, csrf_login}` | `{ "stage": "cambio_password\|mfa_enrolamiento\|mfa_pendiente", "next": "/..." }`; fija cookie de sesión |
| GET | `/session` | — | `{ authenticated, stage, csrf_token, usuario?: Usuario, permisos?: {clave:bool} }` (siempre 200; si no hay sesión `authenticated=false`) |
| POST | `/password/cambiar` | `{password_actual, password_nueva, password_confirmacion}` | `{ stage?, next?, ok? }` |
| GET | `/mfa/configurar` | — | `{ qr_data_uri, secreto }` (stage `mfa_enrolamiento`) |
| POST | `/mfa/configurar` | `{codigo}` | `{ codigos_recuperacion: string[] }` (única vez; stage→activa) |
| GET | `/mfa/verificar` | — | `{ ok: true }` (solo confirma stage) |
| POST | `/mfa/verificar` | `{codigo}` | `{ ok, aviso? }`. Acepta, por este orden: TOTP, código de recuperación y OTP enviado al correo |
| GET | `/mfa/metodos` | — | `{ totp, codigos_recuperacion, otp_correo }` (stage `mfa_pendiente`): qué vías de 2.º factor ofrecer |
| POST | `/mfa/otp-correo` | — + cabecera `X-CSRF-Token` | `{ ok, destino, vigencia_minutos }`: envía un OTP de un solo uso al correo registrado (**MFA de respaldo**). `destino` va enmascarado y el código **nunca** viaja en la respuesta. 409 si el método está desactivado; 429 si se supera el límite (3 por cuenta y 3 por IP cada 15 min); 502 si SMTP falla |
| POST | `/password/recuperar/iniciar` | `{username, email, csrf_login}` | `{ ok: true, csrf }`; fija cookie efímera `passwd_recuperacion`. **Anti-enumeración**: responde igual exista o no la cuenta. `csrf` es el token del desafío para los pasos siguientes |
| POST | `/password/recuperar/verificar` | `{codigo}` + cabecera `X-CSRF-Token: <csrf del desafío>` | `{ ok: true }`. Acepta TOTP en vivo o un código de recuperación. 400 si el desafío caducó/se agotó; 401 código incorrecto |
| POST | `/password/recuperar/cambiar` | `{password_nueva, password_confirmacion}` + cabecera `X-CSRF-Token` | `{ ok: true, next: "/login" }`; revoca todas las sesiones del usuario y borra la cookie de desafío |
| POST | `/logout` | — | `{ ok: true }`; borra cookie |

`stage`→`next`: `cambio_password`→`/password/cambiar`, `mfa_enrolamiento`→`/mfa/configurar`,
`mfa_pendiente`→`/mfa/verificar`, `activa`→`/`.

`Usuario`: `{ id, username, email, nombre_completo, rol, rol_label, mfa_habilitado, activo, ultimo_acceso }`.

`permisos`: mapa con las claves de `app.rbac` evaluadas para el rol actual:
`inventario.ver, inventario.gestionar, credenciales.ver_lista, credenciales.revelar,
credenciales.gestionar, usuarios.gestionar, auditoria.ver, metricas.ver, accesos.gestionar,
tokens.gestionar`.

## Inventario

| Método | Path | Permiso | Notas |
|---|---|---|---|
| GET | `/dashboard` | inventario.ver | admin/op/auditor: `{ es_analista:false, resumen, arbol: ServidorNodo[], dispositivos: DispositivoNodo[] }`; analista: `{ es_analista:true, concesiones: Concesion[] }` |
| GET | `/servidores/{id}` | inventario.ver (+objeto) | `ServidorDetalle` |
| POST | `/servidores` | inventario.gestionar | cuerpo `ServidorInput` → `{ id }` |
| PUT | `/servidores/{id}` | inventario.gestionar | `ServidorInput` → `{ id }` |
| DELETE | `/servidores/{id}` | inventario.gestionar | `{ ok }` |
| POST | `/servidores/{id}/hipervisores` | inventario.gestionar | `HipervisorInput` → `{ id }` |
| GET | `/hipervisores/{id}` | inventario.ver (+objeto) | `HipervisorDetalle` |
| PUT | `/hipervisores/{id}` | inventario.gestionar | `HipervisorInput` → `{ id }` |
| DELETE | `/hipervisores/{id}` | inventario.gestionar | `{ ok, servidor_fisico_id }` |
| POST | `/hipervisores/{id}/vms` | inventario.gestionar | `VmInput` → `{ id }` |
| GET | `/vms/{id}` | inventario.ver (+objeto) | `VmDetalle` |
| PUT | `/vms/{id}` | inventario.gestionar | `VmInput` → `{ id }` |
| DELETE | `/vms/{id}` | inventario.gestionar | `{ ok, hipervisor_id }` |
| GET | `/dispositivos/{id}` | inventario.ver (+objeto) | `DispositivoDetalle` |
| POST | `/dispositivos` | inventario.gestionar | `DispositivoInput` → `{ id }` (400 nombre vacío, 409 duplicado) |
| PUT | `/dispositivos/{id}` | inventario.gestionar | `DispositivoInput` → `{ id }` |
| DELETE | `/dispositivos/{id}` | inventario.gestionar | `{ ok }` (elimina en cascada sus credenciales) |

`resumen`: `{ servidores, hipervisores, vms, dispositivos, credenciales, rotacion_vencida }`.

`ServidorInput`: `{ nombre, tipo('funcion_unica'|'host_virtualizacion'), descripcion, sistema_operativo,
marca_modelo, ubicacion, ip_gestion, ram, cpu, almacenamiento, numero_serie, garantia_hasta,
proveedor, estado('activo'|'mantenimiento'|'retirado'), etiquetas, restringido?: bool }`.

`HipervisorInput`: `{ nombre, plataforma, version, ip_gestion, descripcion, estado, etiquetas, restringido?: bool }`.

`restringido` (opcional en `ServidorInput`, `HipervisorInput` y `DispositivoInput`): marca el activo
como **restringido a administradores**. Solo se aplica cuando el usuario tiene `inventario.restringir`
(administrador); para el resto de roles el backend **ignora** el campo. Envíalo únicamente cuando el
usuario pueda restringir. Las VMs **heredan** la restricción de su hipervisor y no tienen marca propia.

`VmInput`: `{ nombre, sistema_operativo, ip, descripcion, ram, cpu, almacenamiento, estado, etiquetas }`
(`ram`/`cpu`/`almacenamiento` = recursos asignados a la VM). `VmDetalle` los incluye.

`DispositivoInput`: `{ nombre, tipo_dispositivo('switch'|'router'|'firewall'|'access_point'|'balanceador'|'otro'),
marca_modelo, version (firmware), ip_gestion, ubicacion, puertos (texto libre), descripcion,
numero_serie, garantia_hasta, proveedor, estado, etiquetas, restringido?: bool }`. Etiquetas en español del tipo
(`tipo_dispositivo_label`): Switch, Router, Firewall, Punto de acceso, Balanceador, Otro.

`Credencial` (serializada, **nunca** la contraseña): `{ id, usuario_acceso, servicio, puerto,
descripcion, dias_sin_rotar, rotacion_vencida, puede_revelar, tipo_activo, activo_id }`.
`tipo_activo`: `'fisico'|'hipervisor'|'vm'|'dispositivo'` (`activo_id` = id del activo dueño).

`ServidorNodo` (árbol): `{ id, nombre, tipo, etiqueta_tipo, estado, ip_gestion, etiquetas:string[],
credenciales: Credencial[], hipervisores: HipervisorNodo[], restringido: bool }`.
`HipervisorNodo`: `{ id, nombre, plataforma, estado, credenciales, vms: VmNodo[], restringido: bool }`.
`VmNodo`: `{ id, nombre, sistema_operativo, estado, credenciales }` (sin `restringido`: hereda el del hipervisor).
`DispositivoNodo`: `{ id, nombre, tipo_dispositivo, tipo_dispositivo_label, estado, ip_gestion,
etiquetas: string[], credenciales: Credencial[], restringido: bool }` (solo cuando `es_analista` es false).

Cada nodo servidor/hipervisor/dispositivo del dashboard incluye `restringido: bool`. El dashboard del
**administrador** y del **auditor** devuelve los activos restringidos (con la marca a true); el del
**operador** ya viene filtrado por el backend, así que los restringidos no aparecen (ni las VMs de un
hipervisor restringido). El **analista** solo ve los activos que tenga concedidos.

`ServidorDetalle` = todos los campos del servidor + `etiqueta_tipo`, `lista_etiquetas`,
`credenciales: Credencial[]`, `hipervisores: {id,nombre,plataforma,estado}[]`,
`puede_gestionar: bool`, `puede_gestionar_accesos: bool`, `restringido: bool`,
`puede_restringir: bool`, `tiene_notas: bool`,
`accesos?: Concesion[]` (si admin), `analistas?: {id,username,nombre_completo}[]` (si admin).
Análogo para `HipervisorDetalle` (incluye `servidor_fisico_id`, `servidor_fisico_nombre`,
`vms: {...}[]`), `VmDetalle` (incluye `hipervisor_id`, `hipervisor_nombre`) y
`DispositivoDetalle` (= `DispositivoInput` + `tipo_dispositivo_label`, `lista_etiquetas`,
`credenciales`, `puede_gestionar`, `puede_gestionar_accesos`, `restringido`, `puede_restringir`,
`tiene_notas`, `accesos?`, `analistas?`).

Los detalles de servidor, hipervisor y dispositivo incluyen `restringido: bool` (estado actual de la
marca) y `puede_restringir: bool` (true solo para administradores; habilita el control para cambiarla).
El detalle de un activo restringido devuelve 404 al operador. `VmDetalle` no lleva estos campos: la VM
hereda la restricción de su hipervisor.

`Concesion`: `{ id, usuario_id, username, nombre_completo, nivel('ver'|'ver_credenciales'),
nivel_label, expira_en, expirada, tipo, activo_id, activo_nombre }`. `tipo` puede ser también
`'dispositivo'` (enlaza a `/dispositivos/{id}`).

## Credenciales

| Método | Path | Permiso | Notas |
|---|---|---|---|
| POST | `/credenciales` | credenciales.gestionar | `{activo('fisico'|'hipervisor'|'vm'|'dispositivo'), activo_id, usuario_acceso, password, servicio, puerto?, descripcion}` → `{ id }` |
| GET | `/credenciales/{id}` | credenciales.gestionar | datos para editar + `historial: {id, rotada_en, rotada_por}[]` (sin password) |
| PUT | `/credenciales/{id}` | credenciales.gestionar | `{usuario_acceso, password(''=conservar), servicio, puerto?, descripcion}` → `{ id }` |
| DELETE | `/credenciales/{id}` | credenciales.gestionar | `{ ok }` |
| POST | `/credenciales/{id}/revelar` | credenciales.revelar (+objeto) | `{ usuario, password }` (auditado, rate-limited) |
| POST | `/credenciales/{id}/copiar` | credenciales.revelar (+objeto) | `{ usuario, password }` (auditado, rate-limited) |
| POST | `/credenciales/{id}/historial/{hid}/revelar` | credenciales.gestionar | `{ password }` (auditado, rate-limited) |

## Búsqueda

| GET | `/buscar?q=` | inventario.ver | `{ q, servidores:[], hipervisores:[], vms:[], dispositivos:[], credenciales:[] }` (filtrado por objeto, sin passwords, máx 50/tipo). `dispositivos`: `{ id, nombre, tipo_dispositivo, tipo_dispositivo_label, ip_gestion, estado }[]` |

## Accesos (concesiones)

| POST | `/accesos/conceder` | accesos.gestionar | `{usuario_id, tipo, activo_id, nivel, expira_dias?}` (upsert) → `{ ok }` |
| POST | `/accesos/{id}/revocar` | accesos.gestionar | `{ ok }` |

## Notas seguras

| GET | `/activos/{tipo}/{id}/notas` | inventario.gestionar | `{ tiene_notas: bool }` (no devuelve el contenido en claro) |
| PUT | `/activos/{tipo}/{id}/notas` | inventario.gestionar | `{contenido}` → `{ ok }` |
| POST | `/activos/{tipo}/{id}/notas/revelar` | credenciales.revelar (+objeto) | `{ notas }` (auditado, rate-limited) |

`{tipo}` acepta `fisico`, `hipervisor`, `vm` y `dispositivo`.

## Usuarios

| GET | `/usuarios` | usuarios.gestionar | `{ usuarios: Usuario[] }` |
| POST | `/usuarios` | usuarios.gestionar | `{username, email, nombre_completo, rol}` → `{ username, password_temporal }` |
| POST | `/usuarios/{id}/desactivar` | usuarios.gestionar | `{ ok }` |
| POST | `/usuarios/{id}/reactivar` | usuarios.gestionar | `{ ok }` |
| POST | `/usuarios/{id}/reset-password` | usuarios.gestionar | `{ username, correo_enviado, destino }`. La contraseña temporal se **envía al correo del titular** y NO se devuelve; `destino` va enmascarado. Solo si el envío falla se añaden `password_temporal` y `aviso` como contingencia |
| POST | `/usuarios/{id}/reset-mfa` | usuarios.gestionar | `{ ok }` |
| POST | `/usuarios/{id}/rol` | usuarios.gestionar | `{rol}` → `{ ok }` |

## Tokens de API

| GET | `/tokens` | tokens.gestionar | `{ tokens: {id,nombre,creado_en,ultimo_uso,activo,creado_por}[] }` |
| POST | `/tokens` | tokens.gestionar | `{nombre}` → `{ token }` (única vez) |
| POST | `/tokens/{id}/revocar` | tokens.gestionar | `{ ok }` |

## Auditoría

| GET | `/auditoria?filtro_usuario=&filtro_accion=&pagina=` | auditoria.ver | `{ registros: Registro[], pagina, total_paginas, acciones: string[], filtro_usuario, filtro_accion }` |
| GET | `/auditoria/export.csv?filtro_usuario=&filtro_accion=` | auditoria.ver | `text/csv` (StreamingResponse, mitiga inyección de fórmulas) |

`Registro`: `{ id, fecha, usuario, accion, objeto_tipo, objeto_id, detalle, direccion_ip, agente_usuario, exito }`.

## Métricas

| GET | `/metricas` | metricas.ver | `{ rotacion_vencida:[], logins_fallidos_24h, logins_fallidos_7d, bloqueados:[], sin_mfa:[], top_accesos:[], concesiones_por_caducar:[] }` (mismos datos que `metricas.html`) |

## Configuración del sistema

Ajustes operativos en tiempo de ejecución (se aplican al instante, sin reiniciar). Solo
administradores. Cada cambio se audita; los secretos se guardan cifrados y **nunca** se devuelven
en claro.

| Método | Path | Permiso | Notas |
|---|---|---|---|
| GET | `/configuracion` | configuracion.gestionar | `{ grupos: GrupoConfig[], info_sistema: InfoSistemaItem[] }` |
| PUT | `/configuracion` | configuracion.gestionar | `{ cambios: { clave: valor, … } }` → `{ modificadas: string[] }`. 400 `{detail}` si un valor es inválido (fuera de rango, etc.) |
| POST | `/configuracion/restablecer` | configuracion.gestionar | `{ clave }` → `{ restablecido: bool }` (borra el override; el ajuste vuelve a su valor base) |
| POST | `/configuracion/probar-correo` | configuracion.gestionar | `{ destinatario? }` → `{ ok: true, destinatarios: number }` o 400 `{detail}` con el error SMTP |

`GrupoConfig`: `{ grupo: string, ajustes: AjusteConfig[] }`. Grupos en orden fijo:
`Sesión y comportamiento`, `Política de cuentas`, `Límites de tasa (anti-abuso)`,
`Inventario y auditoría`, `Notificaciones por correo`.

`AjusteConfig`: `{ clave, etiqueta, ayuda, tipo('entero'|'booleano'|'texto'|'secreto'),
minimo: number|null, maximo: number|null, origen('configurado'|'entorno'|'defecto') }`.
Además: los ajustes **no secretos** traen `valor` (number/boolean/string según `tipo`); los
**secretos** no traen `valor` sino `configurado: bool` (si hay uno guardado). `origen`:
`configurado` = override en la BD, `entorno` = fijado por variable de entorno, `defecto` = valor base.

`InfoSistemaItem`: `{ etiqueta: string, valor: string|number }` (solo lectura; definido por entorno
o requiere reinicio — nunca incluye el valor de las claves criptográficas).

**PUT `/configuracion`**: envía valores nativos (`number` para entero, `boolean` para booleano,
`string` para texto/secreto). Para los **secretos**, incluye la clave **solo si** el usuario escribió
un valor nuevo; un secreto vacío o ausente significa «no cambiar». Un valor que iguale su base no
crea override (y elimina el existente); `modificadas` solo lista los cambios reales.

## Vault personal (privado del usuario)

| Método | Path | Permiso | Notas |
|---|---|---|---|
| GET | `/vault` | vault.usar | `{ entradas: VaultEntrada[] }` (solo las del usuario; sin password) |
| GET | `/vault/{id}` | vault.usar | `VaultEntrada` (404 si es de otro usuario) |
| POST | `/vault` | vault.usar | `VaultInput` → `{ id }` |
| PUT | `/vault/{id}` | vault.usar | `VaultInput` (`password ''`=conservar) → `{ id }` |
| DELETE | `/vault/{id}` | vault.usar | `{ ok }` |
| POST | `/vault/{id}/revelar` | vault.usar | `{ usuario, password }` (auditado, rate-limited, `no-store`) |
| POST | `/vault/{id}/copiar` | vault.usar | `{ usuario, password }` (auditado, rate-limited, `no-store`) |

`VaultInput`: `{ titulo, usuario_acceso, password, url, categoria('servicio'|'aplicacion'|'cuenta'|'otro'), notas }`.
`VaultEntrada` (sin password): `{ id, titulo, usuario_acceso, url, categoria, notas, dias_sin_rotar, rotacion_vencida }`.
Cada entrada es **privada del dueño**: una ajena responde 404, ni el admin la ve.

## Importación / exportación CSV

| Método | Path | Permiso | Notas |
|---|---|---|---|
| POST | `/importar` | inventario.gestionar | multipart `archivo` (CSV) → `{ creados:{servidor,hipervisor,vm,credencial}, errores: string[], total }` |
| POST | `/exportar` | inventario.exportar | descarga CSV **en claro** del inventario (round-trip con `/importar`), auditado, `no-store`; excluye vaults |
| GET | `/plantilla.csv` | inventario.gestionar | plantilla CSV de ejemplo (sin secretos) |
