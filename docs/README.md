# Documentación — Gestor de Contraseñas de Servidores

Índice de toda la documentación del proyecto, organizada por propósito. Empiece por la sección que
corresponda a su rol.

> Visión general y arranque rápido: [`../README.md`](../README.md).

## 🧭 Entender el sistema

| Documento | Para qué |
|---|---|
| [`arquitectura.md`](arquitectura.md) | **Cómo está construido y de qué se compone**: componentes, capas, modelo de seguridad y flujos. |
| [`modelo-datos.md`](modelo-datos.md) | Esquema relacional (entidades, relaciones, reglas de integridad). |
| [`control-acceso.md`](control-acceso.md) | Roles (RBAC) y control de acceso por objeto (concesiones a analistas). |
| [`glosario-faq.md`](glosario-faq.md) | Glosario de términos y preguntas frecuentes. |

## 👤 Manuales de uso

| Documento | Audiencia |
|---|---|
| [`manual-usuario.md`](manual-usuario.md) | Todo el personal: primer acceso, MFA, inventario, credenciales, notas, búsqueda. |
| [`manual-uso-ilustrado.md`](manual-uso-ilustrado.md) | **Recorrido visual con capturas** de cada pantalla, paso a paso. |
| [`manual-administrador.md`](manual-administrador.md) | Administradores: usuarios, concesiones, auditoría, métricas, tokens, importación, respaldo. |

## 🚀 Despliegue y operación

| Documento | Para qué |
|---|---|
| [`guia-implementacion.md`](guia-implementacion.md) | Instalación, plan de pruebas (UAT), paso a producción y operación continua. |
| [`guia-nginx-tls.md`](guia-nginx-tls.md) | HTTPS con nginx, certificados y rotación sin caída. |
| [`ambientes.md`](ambientes.md) | Plantillas por ambiente (dev/QA/preprod/prod) y TLS sin dominio (por IP). |

## 📚 Referencias técnicas

| Documento | Para qué |
|---|---|
| [`referencia-configuracion.md`](referencia-configuracion.md) | Todas las variables de entorno `PASSWD_*` con sus valores por defecto. |
| [`referencia-cli.md`](referencia-cli.md) | Comandos de la CLI (`init-db`, `crear-admin`, `respaldo`, `restaurar`). |
| [`referencia-api-rest.md`](referencia-api-rest.md) | API REST de solo lectura (`/api/v1`) para SIEM/automatización. |
| [`../frontend/API_CONTRACT.md`](../frontend/API_CONTRACT.md) | Contrato de la API JSON del frontend (`/api/web`). |
| [`guia-desarrollo.md`](guia-desarrollo.md) | Entorno de desarrollo, pruebas, CI y convenciones. |

## ✅ Cumplimiento y verificación

| Documento | Para qué |
|---|---|
| [`cumplimiento-cis-v8.1.md`](cumplimiento-cis-v8.1.md) | Matriz CIS Controls v8.1. |
| [`cumplimiento-iso-27003.md`](cumplimiento-iso-27003.md) | Alineación ISO/IEC 27001:2022 (Anexo A) e ISO/IEC 27003. |
| [`cumplimiento-owasp.md`](cumplimiento-owasp.md) | OWASP Top 10 (2021) y API Security Top 10 (2023). |
| [`verificacion-cumplimiento.md`](verificacion-cumplimiento.md) | Informe de verificación con evidencia (pruebas, SAST, dinámica). |

## 🗺️ Evolución

| Documento | Para qué |
|---|---|
| [`hoja-de-ruta.md`](hoja-de-ruta.md) | Estado de las mejoras y plan de evolución por fases. |

---

### ¿Por dónde empiezo?

- **Soy usuario nuevo** → [`manual-usuario.md`](manual-usuario.md).
- **Administro el sistema** → [`manual-administrador.md`](manual-administrador.md).
- **Voy a instalarlo/desplegarlo** → [`guia-implementacion.md`](guia-implementacion.md) + [`ambientes.md`](ambientes.md).
- **Quiero entender el código** → [`arquitectura.md`](arquitectura.md) + [`guia-desarrollo.md`](guia-desarrollo.md).
- **Necesito integrarlo con un SIEM** → [`referencia-api-rest.md`](referencia-api-rest.md).
- **Me piden la evidencia de cumplimiento** → [`verificacion-cumplimiento.md`](verificacion-cumplimiento.md).
</content>
