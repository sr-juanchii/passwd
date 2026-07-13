# Referencia de la API REST de solo lectura (`/api/v1`)

API **de solo lectura** autenticada por **token Bearer**, pensada para **SIEM y automatización**
(ingerir la bitácora, consultar el inventario de forma programática). Está implementada en
[`app/routes/api.py`](../app/routes/api.py) y es independiente de la interfaz web.

> **No hay otra API REST de escritura.** El frontend Next.js usa una API JSON distinta (`/api/web`),
> basada en sesión por cookie y CSRF, documentada en
> [`../frontend/API_CONTRACT.md`](../frontend/API_CONTRACT.md).

## Características de seguridad

- **Autenticación:** cabecera `Authorization: Bearer <token>`. **Sin cookies ni CSRF.**
- **Solo lectura:** únicamente métodos `GET`; no modifica nada.
- **Nunca expone secretos:** no devuelve contraseñas, semillas TOTP ni notas.
- **Límite de tasa por token:** 4× el límite de login (60 peticiones / 5 min con los valores por
  defecto). Al superarlo responde **429**.
- **Tokens revocables:** en la base de datos solo se guarda el **hash SHA-256** del token; un
  administrador puede revocarlo en cualquier momento (deja de funcionar de inmediato).
- **Alcance (scope) por token (mínimo privilegio):** `todo` (auditoría e inventario), `auditoria`
  (solo `/api/v1/auditoria`) o `inventario` (solo `/api/v1/inventario`). Usar el endpoint fuera del
  alcance responde **403**.
- **Caducidad opcional:** un token puede crearse con vencimiento; pasado, responde **401** («Token
  caducado»).
- **Úsese siempre sobre TLS.**

### Obtener un token

Un administrador lo crea en **Tokens** (web) o en `/api/web/tokens` (frontend). El valor se muestra
**una sola vez**; cópielo y guárdelo de forma segura. Ver
[`manual-administrador.md`](manual-administrador.md) §5.

## Autenticación — respuestas

| Situación | Código | Cuerpo |
|---|---|---|
| Falta la cabecera o no empieza por `Bearer ` | `401` | `{"detail":"Token de API requerido."}` (+ `WWW-Authenticate: Bearer`) |
| Token inexistente o revocado | `401` | `{"detail":"Token inválido o revocado."}` |
| Token caducado | `401` | `{"detail":"Token caducado."}` |
| Endpoint fuera del alcance del token | `403` | `{"detail":"El token no tiene alcance «...»."}` |
| Límite de tasa superado | `429` | `{"detail":"Límite de peticiones de API alcanzado."}` |

Cada petición válida actualiza el campo **«último uso»** del token (visible en la consola de admin).

---

## `GET /api/v1/auditoria`

Devuelve eventos de la bitácora en JSON, pensado para **ingestión incremental**.

**Parámetros de consulta:**

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `desde_id` | int | `0` | Devuelve eventos con `id` **mayor** que este valor. Use el último `id` ya ingerido para paginar incrementalmente. |
| `accion` | string | `""` | Filtra por una acción exacta (p. ej. `credencial_revelada`). |
| `limit` | int | `100` | Máximo de eventos a devolver (acotado a **500**). |

**Respuesta:**

```json
{
  "eventos": [
    {
      "id": 1234,
      "fecha": "2026-06-19T10:15:30+00:00",
      "usuario": "operador1",
      "accion": "credencial_revelada",
      "objeto_tipo": "credencial",
      "objeto_id": "57",
      "detalle": "vía concesión",
      "direccion_ip": "203.0.113.7",
      "exito": true
    }
  ],
  "ultimo_id": 1234
}
```

Use `ultimo_id` como `desde_id` de la siguiente llamada para recoger solo los eventos nuevos.

### Ejemplo

```bash
curl -s https://passwd.su-organizacion.tld/api/v1/auditoria?desde_id=0&limit=200 \
  -H "Authorization: Bearer $TOKEN"
```

---

## `GET /api/v1/inventario`

Devuelve el inventario completo en JSON, **sin credenciales ni notas**. Requiere alcance
`inventario` o `todo`. Las máquinas virtuales incluyen `ram`, `cpu` y `almacenamiento` asignados.

**Parámetros de paginación (opcionales):** `limit` (>0, tope **500**) y `offset` paginan cada
colección por separado; omitidos, devuelve todo el inventario.

**Respuesta:**

```json
{
  "servidores_fisicos": [
    {"id": 1, "nombre": "srv-bd-nomina", "estado": "activo",
     "sistema_operativo": "Debian 12", "ip_gestion": "10.0.0.5",
     "etiquetas": ["nomina", "critico"]}
  ],
  "hipervisores": [
    {"id": 2, "nombre": "pve-nodo-01", "plataforma": "Proxmox VE", "version": "8.2",
     "estado": "activo", "ip_gestion": "10.0.0.10", "marca_modelo": "Dell R740",
     "ubicacion": "CPD-1", "ram": "256 GB", "cpu": "2x Xeon", "almacenamiento": "4 TB",
     "numero_serie": "ABC123", "garantia_hasta": "2027-01", "proveedor": "Dell",
     "etiquetas": ["virtualizacion"]}
  ],
  "maquinas_virtuales": [
    {"id": 3, "nombre": "vm-correo", "estado": "activo",
     "sistema_operativo": "Ubuntu 24.04", "ip": "10.0.1.20", "hipervisor_id": 2}
  ]
}
```

### Ejemplo

```bash
curl -s https://passwd.su-organizacion.tld/api/v1/inventario \
  -H "Authorization: Bearer $TOKEN" | jq .
```

---

## Patrón de ingestión para SIEM

1. Guardar el `ultimo_id` recibido (inicialmente `0`).
2. Llamar a `GET /api/v1/auditoria?desde_id=<ultimo_id>&limit=500` periódicamente.
3. Procesar `eventos` y actualizar `ultimo_id` con el campo `ultimo_id` de la respuesta.
4. Repetir. Si una llamada devuelve `429`, esperar y reintentar con espaciado.

---

## Documentos relacionados

- [`manual-administrador.md`](manual-administrador.md) §5 — crear y revocar tokens.
- [`../frontend/API_CONTRACT.md`](../frontend/API_CONTRACT.md) — API JSON del frontend (`/api/web`).
- [`cumplimiento-owasp.md`](cumplimiento-owasp.md) — API Security Top 10.
</content>
