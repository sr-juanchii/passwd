# Glosario y preguntas frecuentes

Términos del sistema y respuestas rápidas a dudas habituales. Para procedimientos completos, vea el
[`manual-usuario.md`](manual-usuario.md) y el [`manual-administrador.md`](manual-administrador.md).

---

## Glosario

| Término | Significado |
|---|---|
| **Activo** | Elemento del inventario: servidor físico, hipervisor o máquina virtual. |
| **Servidor físico** | Máquina dedicada a una función única (activo de nivel superior). |
| **Hipervisor** | Máquina física que aloja máquinas virtuales (Proxmox, ESXi, Hyper-V…); activo de nivel superior, no se anida bajo un servidor físico. |
| **Máquina virtual (VM)** | Sistema virtual que corre dentro de un hipervisor. |
| **Credencial** | Usuario + contraseña (cifrada) de acceso a un activo, con servicio, puerto y descripción. |
| **Rol** | Conjunto de permisos: `admin`, `operador`, `auditor`, `analista`. |
| **RBAC** | Control de acceso basado en roles: qué clase de acción permite cada rol ([`app/rbac.py`](../app/rbac.py)). |
| **Acceso por objeto** | Capa extra para el analista: sobre **qué activos concretos** puede operar, según concesiones ([`control-acceso.md`](control-acceso.md)). |
| **Concesión** | Permiso de un administrador a un analista sobre un activo, con nivel (`ver` / `ver_credenciales`) y caducidad opcional. |
| **Default-deny** | El analista no ve nada hasta que se le concede acceso explícito. |
| **MFA / TOTP** | Segundo factor de autenticación: código de 6 dígitos que cambia cada 30 s (RFC 6238), obligatorio para todos. |
| **Códigos de recuperación** | 8 códigos de un solo uso para entrar si se pierde el dispositivo MFA. |
| **Etapa de sesión** | Fase del login: `cambio_password`, `mfa_enrolamiento`, `mfa_pendiente`, `activa`. |
| **CSRF** | Protección contra peticiones falsificadas; token por sesión (cabecera `X-CSRF-Token` en el frontend). |
| **Fernet** | Cifrado simétrico (AES-CBC + HMAC) usado para los secretos en reposo. |
| **Argon2id** | Algoritmo de *hashing* de las contraseñas de usuario. |
| **Rotación** | Cambio de la contraseña de una credencial; reinicia el contador de «días sin rotar». |
| **Anti-exfiltración** | Límite de revelados/copiados por usuario en una ventana de tiempo. |
| **Bitácora / auditoría** | Registro de cada evento de seguridad y acceso, con usuario, IP, agente y resultado. |
| **Token de API** | Credencial Bearer de solo lectura para SIEM/automatización (`/api/v1`). |
| **Web Jinja** | Interfaz HTML servida por el propio backend. |
| **Frontend** | Interfaz moderna en Next.js que consume la API JSON `/api/web`. |
| **Overlay (Compose)** | Archivo `docker-compose.*.yml` adicional que se combina con el base para añadir nginx, frontend, MySQL o certbot. |

---

## Preguntas frecuentes

### Uso general

**¿Por qué me obliga a cambiar la contraseña y a configurar MFA la primera vez?**
La contraseña inicial es de un solo uso y el segundo factor (MFA) es **obligatorio para todos**, sin
excepción. Es un requisito de seguridad del sistema.

**El código MFA siempre se rechaza.**
Casi siempre es la **hora del móvil**: el TOTP depende del reloj. Active la sincronización
automática de hora en el dispositivo.

**Perdí el móvil con la app autenticadora.**
Entre con uno de sus **códigos de recuperación**. Si ya no le quedan, pida a un administrador que
**reinicie su MFA**.

**¿Por qué «Copiar» no muestra la contraseña?**
Es intencionado: la envía al portapapeles **sin mostrarla** (evita que alguien la lea por encima del
hombro) y la borra a los 30 s. Use «Revelar» solo si necesita verla.

**Soy analista y no veo ningún activo.**
Su rol parte de cero: un administrador debe **concederle acceso** a activos concretos.

**La sesión se cierra sola.**
Caduca tras 15 min de inactividad o 8 h de sesión. Es el comportamiento esperado.

### Administración

**¿Cómo doy de baja a una persona?**
Desactive su cuenta (corta el acceso al instante) y **rote las credenciales** que pudo haber
revelado (fíltrelas en la bitácora por `credencial_revelada` y su usuario).

**¿Qué pasa si pierdo `PASSWD_ENCRYPTION_KEY`?**
Las contraseñas cifradas quedan **ilegibles**. El único camino de recuperación es un **respaldo
cifrado** con su frase. Custodie clave y frase fuera del servidor.

**¿Puedo cambiar la clave de cifrado?**
Sí, con un respaldo de por medio: ver [`referencia-cli.md`](referencia-cli.md) («Rotación de la
clave de cifrado»).

### Despliegue

**¿Necesito HTTPS?**
En producción, **sí, obligatorio**. Las cookies se emiten con `Secure`: sin HTTPS el navegador las
descarta y no se puede iniciar sesión. Guía: [`guia-nginx-tls.md`](guia-nginx-tls.md).

**No tengo dominio, solo una IP interna. ¿Funciona el HTTPS?**
Sí. Genere un certificado para la IP (autofirmado o con una CA interna) según
[`ambientes.md`](ambientes.md) §4.

**¿SQLite o MySQL?**
SQLite basta para equipos pequeños (cero administración). Para alta concurrencia o BD corporativa,
use MySQL con el overlay `docker-compose.mysql.yml` (ver [`guia-implementacion.md`](guia-implementacion.md) §4.6).

**La auditoría registra una IP de Docker (172.x).**
La app no está recibiendo las cabeceras de reenvío. Use el overlay de nginx (incluye
`--proxy-headers`) y no exponga la app directamente. Ver [`guia-nginx-tls.md`](guia-nginx-tls.md) §7.

### Integración

**¿Hay API para automatizar?**
Sí, una **API REST de solo lectura** (`/api/v1`) con token Bearer, para SIEM/inventario; **nunca**
expone secretos. Ver [`referencia-api-rest.md`](referencia-api-rest.md).

---

## Documentos relacionados

- [`manual-usuario.md`](manual-usuario.md) y [`manual-administrador.md`](manual-administrador.md)
- [`arquitectura.md`](arquitectura.md) — visión técnica del conjunto.
- [`README.md`](README.md) — índice de toda la documentación.
</content>
