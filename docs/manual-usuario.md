# Manual de usuario

**Sistema:** Gestor de Contraseñas de Servidores
**Audiencia:** todo el personal que usa el sistema (administradores, operadores, auditores y analistas).
**Alcance:** cómo iniciar sesión, navegar y realizar cada tarea del día a día. Las tareas
exclusivas del administrador (usuarios, concesiones, tokens, importación, respaldo) se amplían en
el [`manual-administrador.md`](manual-administrador.md).

> El sistema ofrece **dos interfaces** con la misma funcionalidad y el mismo modelo de seguridad:
> la **web clásica** (servida por la propia aplicación) y el **frontend moderno** (Next.js).
> Este manual describe los flujos; el aspecto concreto puede variar ligeramente entre ambas, pero
> los pasos y los nombres de las acciones son equivalentes.
>
> 📸 ¿Prefiere verlo con **capturas de pantalla** de cada función, junto con la configuración
> óptima y los procedimientos de operación? Vea el
> [`manual-operativo.md`](manual-operativo.md).

---

## 1. Conceptos básicos

El sistema custodia las **credenciales** (usuario + contraseña) de toda la infraestructura,
organizadas en un **inventario** de cuatro tipos de activo:

| Activo | Qué representa |
|---|---|
| 🖥️ **Servidor físico** | Máquina dedicada a una función única (p. ej. la BD de nómina). |
| ⚙️ **Hipervisor** | Máquina física que aloja máquinas virtuales (Proxmox, ESXi, Hyper-V…). |
| 🗔 **Máquina virtual (VM)** | Sistema virtual que corre dentro de un hipervisor. |
| 🔌 **Dispositivo de red** | Switch, router, firewall, punto de acceso, balanceador u otro equipo de red. |

Cada uno de estos activos puede tener **varias credenciales** (una por servicio: SSH, RDP,
iLO/IPMI, panel web, Telnet, SNMP…) y, opcionalmente, una **nota segura cifrada**.

### Su rol determina lo que puede hacer

| Permiso | admin | operador | auditor | analista |
|---|:-:|:-:|:-:|:-:|
| Ver inventario y credenciales (sin contraseña) | ✔ | ✔ (salvo restringidos) | ✔ | solo concedidos |
| Gestionar inventario y credenciales | ✔ | ✔ (salvo restringidos) | ✘ | ✘ |
| Revelar/copiar contraseñas (auditado) | ✔ | ✔ (salvo restringidos) | ✘ | solo concedidas |
| Gestionar usuarios | ✔ | ✘ | ✘ | ✘ |
| Conceder/revocar accesos por activo | ✔ | ✘ | ✘ | ✘ |
| Restringir activos a administradores | ✔ | ✘ | ✘ | ✘ |
| Ver bitácora y métricas | ✔ | ✘ | ✔ | ✘ |

El rol **analista** parte de cero (*default-deny*): no ve ningún activo hasta que un administrador
le **concede** acceso a activos concretos (ver [`control-acceso.md`](control-acceso.md)).

Un administrador puede además **restringir** ciertos activos: quedan ocultos para los operadores
(como si no existieran), mientras que los auditores los siguen viendo sin poder revelar sus
contraseñas. Las máquinas virtuales heredan la restricción de su hipervisor.

---

## 2. Primer acceso (todos los usuarios)

Cuando se crea su cuenta, el administrador le entrega un **usuario** y una **contraseña temporal**.
El primer ingreso le obliga a completar tres pasos, en este orden:

### Paso 1 — Iniciar sesión

1. Abra la dirección del sistema (`https://…`) en el navegador.
2. Escriba su **usuario** y la **contraseña temporal**.
3. Pulse **Entrar**.

> Si falla 5 veces seguidas, la cuenta se **bloquea 15 minutos**. Espere o pida al administrador
> que la restablezca. Los mensajes de error son genéricos a propósito (no revelan si el usuario
> existe).

### Paso 2 — Cambiar la contraseña (obligatorio la primera vez)

La contraseña temporal es de **un solo uso**. El sistema le pide definir una nueva que debe cumplir:

- **Mínimo 12 caracteres.**
- **No** ser una contraseña común ni contener su nombre de usuario.
- Al menos 4 caracteres distintos, sin espacios al principio/final.

Escriba la contraseña actual (la temporal), la nueva dos veces y confirme.

### Paso 3 — Enrolar el MFA (segundo factor, obligatorio)

El sistema **exige** un segundo factor (TOTP) para todas las cuentas, sin excepción.

1. Instale una **app autenticadora** en su móvil: Aegis, FreeOTP, Google Authenticator o
   Microsoft Authenticator.
2. En pantalla aparece un **código QR**. Ábralo desde la app («escanear código») o introduzca el
   **secreto** mostrado manualmente.
3. La app empieza a generar un código de **6 dígitos** que cambia cada 30 segundos. Escriba el
   código actual y confirme.
4. El sistema muestra **8 códigos de recuperación** de un solo uso. **Guárdelos en un lugar
   seguro** (gestor de contraseñas personal, sobre sellado): le permitirán entrar si pierde el
   móvil. **Solo se muestran una vez.**

A partir de aquí su cuenta está lista y entra en la **sesión activa**.

> ⏱️ El reloj de su dispositivo debe estar en hora (el TOTP depende de la hora). Si el código se
> rechaza siempre, revise la sincronización horaria del teléfono.

---

## 3. Accesos posteriores

En cada ingreso posterior:

1. Usuario + contraseña.
2. Código de **6 dígitos** de su app autenticadora.

Si no tiene el móvil a mano, use uno de sus **códigos de recuperación** en lugar del código de 6
dígitos (cada uno sirve **una sola vez**; el sistema le avisa cuántos le quedan).

### ¿Olvidó su contraseña?

Puede restablecerla **usted mismo**, sin intervención del administrador, desde el enlace
**«¿Olvidó su contraseña?»** de la pantalla de inicio de sesión:

1. **Identifíquese**: escriba su **usuario** y su **email registrado** (deben coincidir).
2. **Verifique su identidad** con su segundo factor: el **código de 6 dígitos** de su app
   autenticadora o uno de sus **códigos de recuperación** de un solo uso.
3. **Establezca la nueva contraseña**. Al guardar, se **cierran todas sus sesiones** y se le pide
   iniciar sesión de nuevo con la contraseña recién creada (y su MFA).

Notas de seguridad:

- El enlace **solo funciona si su cuenta ya tiene el MFA enrolado**. Si nunca completó el
  enrolamiento (o perdió a la vez la contraseña, el dispositivo y todos los códigos de
  recuperación), pida al **administrador** que reinicie su acceso.
- Cada solicitud caduca a los **10 minutos** y se bloquea tras varios códigos incorrectos.
- Todo el proceso queda **auditado** y se envía una **alerta** al completar el restablecimiento.

### La sesión caduca sola

- Tras **15 minutos sin actividad**, la sesión expira y deberá volver a entrar.
- La sesión dura como máximo **8 horas** aunque esté activo.
- Puede cerrar sesión en cualquier momento desde el menú de usuario (**Cerrar sesión**).

---

## 4. Navegar el inventario

El **panel principal** (inicio) muestra el inventario:

- Un **resumen** de cuántos servidores, hipervisores, VMs, dispositivos de red y credenciales
  hay y cuántas credenciales tienen la **rotación vencida**.
- El **árbol** de activos: servidores físicos, hipervisores (que se despliegan para mostrar sus
  máquinas virtuales) y dispositivos de red.
- En el frontend moderno, una **«postura de seguridad»** y una **cola de riesgo** que ordena las
  credenciales que más necesitan rotarse.

Pulse el nombre de un activo para abrir su **ficha de detalle**, donde verá:

- Sus datos (SO, IP de gestión, hardware, estado, etiquetas, descripción).
- La lista de **credenciales** del activo.
- La **nota segura** (si la hay).
- En el caso de servidores físicos, sus hipervisores; en hipervisores, sus VMs.

### Buscar

Use **Buscar** (o la **paleta de comandos** con `Ctrl+K` / `⌘K` en el frontend moderno) para
encontrar activos y credenciales por nombre, IP, ubicación, servicio, usuario o etiqueta. La
búsqueda **nunca** busca por contraseña, y un analista solo verá resultados de los activos que
tiene concedidos.

---

## 5. Trabajar con credenciales

> Requiere rol **admin** u **operador** (gestión), o **analista** con concesión del nivel adecuado.
> El **auditor** ve la lista pero **no** puede revelar ni copiar.

### Ver una contraseña sin exponerla — «Copiar» (recomendado)

El botón **📋 Copiar** envía la contraseña **directamente al portapapeles sin mostrarla en
pantalla** (evita que alguien la lea por encima del hombro). El portapapeles se **borra solo a los
30 segundos**. Pegue la contraseña donde la necesite antes de que se limpie.

### Mostrar una contraseña — «Revelar»

El botón **Revelar** muestra la contraseña en pantalla durante **30 segundos** y luego la oculta
de nuevo automáticamente. Úselo solo cuando necesite verla.

> 🔒 Tanto **Copiar** como **Revelar** quedan **registrados en la bitácora** (con su usuario, IP y
> hora) y comparten un **límite anti-exfiltración**: como máximo 20 accesos cada 5 minutos por
> usuario (configurable). Si lo supera, se bloquea temporalmente y queda constancia.

### Crear una credencial

1. Abra la ficha del activo y pulse **+ Nueva credencial**.
2. Rellene: **usuario de acceso**, **contraseña**, **servicio** (SSH, RDP…), **puerto** (opcional)
   y una **descripción** de a qué da acceso.
3. ¿No tiene una contraseña? Pulse **🎲 Generar** para crear una aleatoria robusta de 20
   caracteres (CSPRNG).
4. Guarde.

### Editar y rotar

- **Editar:** cambie usuario, servicio, puerto o descripción. Si deja el campo de contraseña
  **vacío**, la contraseña **se conserva** (no la borra).
- **Rotar:** al introducir una contraseña nueva, la anterior se guarda en el **historial** (se
  conservan las últimas N) y el contador de «días sin rotar» se reinicia.

### Alerta de rotación

Cuando una credencial supera los **90 días** (configurable) sin cambiarse, aparece una **insignia
de aviso** en su ficha y en el panel. Rotarla hace desaparecer el aviso. Esto le ayuda a mantener
las contraseñas frescas.

### Historial de contraseñas

Desde la edición de una credencial puede ver el **historial** de contraseñas anteriores (quién y
cuándo la rotó). Revelar una versión histórica también queda auditado.

---

## 6. Notas seguras por activo

Cada activo admite **una nota segura cifrada** (p. ej. instrucciones de acceso, peculiaridades del
sistema). El contenido se cifra en reposo y **nunca** se muestra en los listados.

- **Ver nota:** pulse «Ver nota»; se muestra unos segundos y queda auditado el acceso.
- **Editar nota:** escriba el contenido y guarde. Dejarla vacía la elimina.

Gestionar la nota requiere permiso de gestión de inventario; revelarla requiere el mismo permiso
que revelar credenciales.

---

## 6 bis. Mi vault personal

Además del inventario de servidores, **cada usuario** dispone de un **vault personal** (menú
**«Mi vault»**) para guardar contraseñas de **servicios, aplicaciones o cuentas propias**. Es
**privado**: solo tú ves y revelas su contenido; ni el administrador accede a él.

- **Añadir:** «Nueva entrada» → título, usuario/cuenta, contraseña (puedes **generarla**),
  categoría (servicio/aplicación/cuenta/otro), URL y notas opcionales.
- **Usar:** «Copiar» pasa la contraseña al portapapeles sin mostrarla (se limpia a los 30 s) y
  «Revelar» la muestra y se re-oculta sola. Ambas quedan registradas en tu auditoría y están
  limitadas para frenar extracciones masivas.
- **Editar/eliminar:** desde cada entrada. Al editar, deja la contraseña en blanco para conservarla.

La contraseña se cifra antes de guardarse y el vault se incluye en el respaldo cifrado del sistema,
pero **nunca** en la exportación en claro de migración.

---

## 7. Tema claro / oscuro

Use el botón de **tema** (sol/luna) para alternar entre modo claro y oscuro. La preferencia se
recuerda en su navegador.

---

## 8. Problemas frecuentes

| Situación | Qué hacer |
|---|---|
| «Usuario o contraseña incorrectos» repetido | Verifique mayúsculas; tras 5 fallos la cuenta se bloquea 15 min. |
| El código MFA siempre se rechaza | Compruebe la **hora** del móvil (debe estar sincronizada por red). |
| Perdí el móvil del MFA | Entre con un **código de recuperación**; si no le quedan, pida al admin **Reiniciar MFA**. |
| Olvidé la contraseña | Pida al admin **Restablecer contraseña** (le dará una temporal). |
| «Copiar» no copia | La función de portapapeles requiere HTTPS; en pruebas sin TLS puede no estar disponible. |
| No veo ningún activo (soy analista) | Aún no le han concedido acceso; pida al administrador la concesión necesaria. |
| La sesión se cierra sola | Es normal tras 15 min de inactividad o 8 h de sesión; vuelva a entrar. |

---

## 9. Documentos relacionados

- [`manual-administrador.md`](manual-administrador.md) — tareas de administración (usuarios, accesos, tokens, auditoría, importación, respaldo).
- [`control-acceso.md`](control-acceso.md) — roles y concesiones de acceso por activo.
- [`../README.md`](../README.md) — visión general y arranque.
</content>
</invoke>
