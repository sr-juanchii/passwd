# Visión futura: rotación remota de contraseñas (evolución a PAM)

> **Estado: candidata futura, sin priorizar y NO implementada.** Este documento registra la
> visión, el valor y —sobre todo— las condiciones de seguridad para evolucionar el sistema desde
> una **bóveda de credenciales** hacia la **rotación remota** (cambiar la contraseña directamente
> en el servidor desde esta plataforma). No es un compromiso de implementación: es el mapa para
> hacerlo bien el día que se priorice.

## 1. La visión

Cerrar el ciclo de la gestión de contraseñas: que el sistema pueda **generar una contraseña
nueva, aplicarla en el servidor objetivo, verificarla y guardarla**, todo en una operación
auditada — manual o programada. Hoy el sistema custodia secretos (bóveda pasiva); la visión es
que también pueda **aplicar el cambio**, eliminando la deriva del proceso manual ("la cambié en
el servidor pero olvidé actualizarla aquí").

## 2. Por qué es valioso

- **Rotación de ciclo cerrado**: sin desincronización entre el servidor y la bóveda.
- **Cumplimiento de la política de rotación**: ya alertamos por antigüedad (>90 días); esto
  permite *actuar* sobre esa alerta, incluso de forma **programada**.
- **Trazabilidad de punta a punta**: cada rotación queda auditada (quién, cuándo, resultado).
- Es la evolución natural de un gestor de contraseñas hacia un **PAM** (Privileged Access
  Management).

## 3. El cambio de paradigma (y por qué exige cuidado)

| Hoy (bóveda) | Con rotación remota (PAM) |
|---|---|
| Pasiva: guarda secretos cifrados en reposo | Activa: se **conecta y autentica** en los servidores |
| Sin conexiones salientes | Necesita **alcance de red** a SSH/RDP/WinRM/IPMI de toda la flota |
| Un compromiso expone secretos (cifrados, auditados, limitados) | Un compromiso permite **pivotar o bloquear toda la flota** |
| Encaja con segmentación de red estricta | Tiende a **romper** la segmentación si se hace mal |

**Conclusión:** la plataforma pasaría a ser un **objetivo de altísimo valor y un posible punto de
compromiso catastrófico.** Por eso no se improvisa: requiere arquitectura y modelo de amenazas
propios.

## 4. Principios de diseño no negociables

1. **La app central NO se conecta a la flota.** Modelo **agente/worker**: un componente
   endurecido e independiente (idealmente uno por segmento de red) toma trabajos de rotación,
   ejecuta el cambio *dentro* de la red del objetivo y reporta el resultado. La bóveda nunca abre
   alcance saliente a todos los servidores.
2. **Mínimo privilegio**: cuentas de rotación dedicadas por servidor, limitadas a cambiar
   contraseñas (p. ej. una regla `sudo` acotada), nunca root/admin completo.
3. **Verificar-luego-confirmar (atómico)**: cambiar en el servidor → reautenticar con la clave
   nueva → solo entonces guardar en la bóveda. Si algo falla, no se confirma y se alerta. El
   **historial de contraseñas** (ya implementado) es la red de recuperación.
4. **Gating reforzado**: solo rol admin + **re-MFA (step-up)** al rotar + límite de tasa +
   auditoría completa; **doble aprobación** (dos personas) para producción.
5. **Confianza del canal**: fijación de *host key* SSH por activo (nunca auto-aceptar), validación
   TLS estricta en paneles web/WinRM, tiempos de espera acotados.
6. **Segmentación de red**: el worker vive en un segmento controlado, con firewall explícito por
   destino y egreso por defecto denegado.
7. **Break-glass**: una vía de recuperación fuera de banda para que un fallo de rotación nunca
   deje a nadie sin acceso a la flota.
8. **Secretos efímeros**: las credenciales vivas existen en memoria del worker el mínimo tiempo,
   jamás se registran en logs.
9. **Empezar estrecho**: un solo protocolo bien entendido (SSH/Linux) antes que "todo".

## 5. Arquitectura objetivo (boceto)

```
   Plataforma (bóveda)                 Segmento controlado            Flota
   ┌────────────────────┐  trabajo    ┌────────────────────┐  SSH    ┌──────────┐
   │ cola de rotación   │ ──────────► │ worker de rotación │ ──────► │ servidor │
   │ (cifrada, auditada)│ ◄────────── │ (mínimo privilegio)│  verif. │  objetivo│
   └────────────────────┘  resultado  └────────────────────┘ ◄────── └──────────┘
        │  verify-then-commit + historial (rollback)        firewall por destino
        ▼
   guarda la nueva clave SOLO si la verificación tuvo éxito
```

La plataforma encola; el worker ejecuta y verifica; la bóveda confirma solo ante éxito.

## 6. Alternativa recomendada de menor riesgo

En lugar de construir conectividad propia, **integrar con el orquestador que la organización ya
usa y en el que ya confía** (Ansible/AWX, Salt, etc.): la plataforma **genera y encola** la nueva
contraseña y el orquestador —que **ya tiene** el acceso, las credenciales y la segmentación— la
aplica. La bóveda sigue siendo bóveda, se mantiene la **separación de funciones** y no se crea un
pivote hacia toda la flota. Suele dar el grueso del beneficio con una fracción del riesgo.

## 7. Hoja de fases para llegar

- **Fase A — Generar y encolar (sin conexión):** la plataforma genera la clave nueva y crea un
  "trabajo de rotación" pendiente; un humano o el orquestador lo aplica y marca como hecho. Riesgo
  mínimo; valor inmediato (deja de perderse la sincronización).
- **Fase B — Worker SSH/Linux:** worker independiente, cuenta de rotación de mínimo privilegio,
  *verify-then-commit*, fijación de host key, step-up MFA, auditoría. Un solo protocolo.
- **Fase C — Programación y más protocolos:** rotación programada por política de antigüedad;
  soporte WinRM/RDP, IPMI/iLO; doble aprobación en producción.
- **Fase D — Escala y observabilidad:** workers por segmento, alta disponibilidad, envío de
  eventos de rotación al SIEM (ya existe la API de auditoría).

## 8. Cimientos que el sistema ya aporta

- **Historial de contraseñas** → recuperación/rollback ante un fallo de rotación.
- **Auditoría** con IP/usuario/resultado y **API de solo lectura** para SIEM.
- **Generador de contraseñas** robustas (CSPRNG).
- **Control de acceso por objeto**, **MFA obligatorio** y **alertas por correo**.
- **Cifrado en reposo** (Fernet) y límite anti-exfiltración.

## 9. Decisiones a confirmar antes de empezar

1. ¿Vía **agente propio** o **integración con orquestador** existente?
2. Protocolo(s) inicial(es) y alcance (recomendado: SSH/Linux primero).
3. Modelo de cuentas de rotación (mínimo privilegio por servidor).
4. Política de aprobación (¿doble control en producción?) y ventanas de cambio.
5. Topología de red/segmentos y reglas de firewall por destino.
6. Procedimiento break-glass y pruebas de recuperación.

## 10. Lo que NO se hará

- No conectar la **app central** directamente a todos los servidores.
- No usar **root/admin completo** para rotar.
- No **auto-aceptar** claves de host SSH ni saltarse la validación TLS.
- No **romper la segmentación** de red ni guardar la clave nueva sin verificarla antes.

---

*Referencia desde la hoja de ruta (`docs/hoja-de-ruta.md`). Cuando se priorice, se abordará con un
diseño dedicado y su propia revisión de seguridad, igual que el resto de cambios sensibles.*
