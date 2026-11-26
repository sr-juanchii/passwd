# Contrato del agente de rotación

| | |
|---|---|
| **Versión del contrato** | 1 |
| **Vigente desde** | passwd 1.4.0 |
| **Carácter** | Normativo |
| **Obliga a** | Toda implementación del agente (hoy, el agente Linux en Go de [`agente/`](../agente/); mañana, p. ej., el agente Windows de la 2.1.0) y todo despliegue del backend que active `/api/agent` |
| **Implementación de referencia** | Backend: [`app/api_agent/__init__.py`](../app/api_agent/__init__.py), [`app/servicios/agentes.py`](../app/servicios/agentes.py), [`app/servicios/rotacion.py`](../app/servicios/rotacion.py), [`app/servicios/cifrado_agente.py`](../app/servicios/cifrado_agente.py). Agente: [`agente/internal/`](../agente/internal/) y [`agente/cmd/`](../agente/cmd/) |
| **El porqué** | [`plan-rotacion-agentes.md`](plan-rotacion-agentes.md) §2, §3 y §4 |

Este documento dice **qué tiene que cumplir** un agente de rotación de passwd y el backend que lo
gobierna. No explica la arquitectura —eso está en [`arquitectura-agentes.md`](arquitectura-agentes.md)—
ni cómo se instala —eso está en [`guia-instalacion-agente-linux.md`](guia-instalacion-agente-linux.md)—,
y no repite las razones de cada decisión, que están en el plan. Los detalles HTTP de cada ruta
están en [`referencia-api-agent.md`](referencia-api-agent.md).

Cuando el plan y este contrato difieren, **rige este contrato**: describe lo que hace el código
de la 1.4.0. El plan es el registro de cómo se llegó aquí.

## 0. Lenguaje normativo

| Palabra | Significado |
|---|---|
| **DEBE** | Requisito. Una implementación que no lo cumple no es conforme y no debe desplegarse. |
| **NO DEBE** | Prohibición. Igual de estricta que DEBE. |
| **PUEDE** | Permitido, no exigido. |

Cada requisito lleva un identificador para citarlo en revisiones y auditorías: **AG-** para el
agente, **BE-** para el backend y su despliegue, **HE-** para el helper con privilegios del agente
Linux. Junto a cada uno se indica dónde se cumple hoy y, cuando existe, la prueba que lo garantiza.

---

## 1. Qué hace el agente, y nada más

Un agente es un binario instalado en **un** activo (servidor físico, hipervisor o máquina virtual)
que aplica las rotaciones de contraseña de cuentas locales **ya autorizadas por dos
administradores** en la gobernanza de la 1.3.0. El agente no decide nada: ejecuta, verifica e
informa.

**AG-01.** El agente **PUEDE** hacer exactamente esto, y **NO DEBE** hacer nada más:

1. Autenticarse con su propia identidad ante **el** backend de su configuración local.
2. Renovar su propia identidad en el saludo (§4).
3. Recoger **un** trabajo de tipo `rotar_cuenta` sellado a su clave (§5, §6).
4. Ejecutarlo en dos fases —aplicar, verificar, confirmar o revertir— (§7).
5. Informar del resultado y enviar telemetría **agregada de su propio host** (§11).
6. Guardar su identidad y un journal cifrado del trabajo en curso; purgar los secretos al cerrar
   el trabajo (§8).

Dónde se cumple: el bucle completo está en [`agente/internal/ejecutor/ejecutor.go`](../agente/internal/ejecutor/ejecutor.go)
(`Ciclo`: saludo → telemetría → recuperación → trabajo); no hay ningún otro camino de ejecución.

### 1.1 Prohibiciones

Son las catorce de [`plan-rotacion-agentes.md`](plan-rotacion-agentes.md) §4.1, en su forma
vigente. Todas son **NO DEBE** para cualquier implementación.

| # | El agente NO DEBE… | Cómo se garantiza hoy | Prueba |
|---|---|---|---|
| 1 | **Crear cuentas.** Una cuenta inexistente es un fallo, nunca un alta. | El helper comprueba que la cuenta existe antes de cualquier acción ([`helper.go`](../agente/internal/helper/helper.go), `Atender`); el instalador se niega a listar cuentas que no existen ([`instalar.sh`](../agente/instalacion/instalar.sh)). | `integracion_test.go::TestIntegracionRechazosDelHelper` |
| 2 | Borrar o deshabilitar cuentas, ni tocar grupos, `sudoers`, `authorized_keys` o llaves SSH. | No existe en el protocolo: el helper solo conoce `verificar`, `aplicar` y `restaurar`. | `helper_test.go::TestRechazos` («acción desconocida») |
| 3 | Ejecutar órdenes o scripts que vengan del backend. | El tipo de trabajo es un enum cerrado de un solo valor (§5.2); cualquier otro se rechaza sin ejecutar nada. | `contrato_test.go::TestRechazosDelContrato` |
| 4 | Conocer contraseñas de otros activos o de otros agentes. | El backend solo despacha al agente vigente del activo de la credencial y solo le entrega su propio trabajo, sellado a su clave (§5, §6). | `test_despacho_agentes.py::test_el_agente_de_otro_activo_no_recibe_el_trabajo` |
| 5 | Decidir rotar por su cuenta. | Solo ejecuta lo que recibe, y solo se despacha lo `AUTORIZADO`. La telemetría no dispara nada. | `test_despacho_agentes.py::test_no_hay_despacho_sin_autorizacion` |
| 6 | Configurarse desde la red. | Backend, CA, *pin*, helper y anti-thrash local se leen de un archivo local ([`config.go`](../agente/internal/config/config.go)); no hay ruta de configuración remota. | `config_test.go` |
| 7 | Escuchar en la red. | Solo conexiones salientes ([`cliente.go`](../agente/internal/cliente/cliente.go)). | — |
| 8 | Salir a cualquier destino. | `IPAddressDeny=any` en la unidad y `IPAddressAllow` con las direcciones del backend en el *drop-in* del instalador. | — |
| 9 | Enviar telemetría invasiva. | Solo agregados y hardware del propio host, con tamaño acotado (§11). | `telemetria_test.go` |
| 10 | Actualizarse solo. | No hay mecanismo de actualización; el instalador comprueba los binarios contra un `SHA256SUMS`. | — |
| 11 | Guardar secretos en claro. | Journal cifrado (§8), identidad `0600`, registro sin contraseñas. | `journal_test.go::TestGuardaCifradoYPurga` |
| 12 | Acumular trabajos. | Un solo trabajo activo por agente en el backend (restricción `UNIQUE`) y en el agente (§5.4). | `ejecutor_test.go::TestSinRedElResultadoEsperaEnElJournalYNoSeAceptaOtroTrabajo` |
| 13 | Martillear rotaciones. | Anti-thrash en el backend y en el agente (§9). Única excepción: la vía de emergencia, registrada. | `test_despacho_agentes.py::test_el_anti_thrash_frena_salvo_en_emergencia`, `ejecutor_test.go::TestElAntiThrashLocalFrenaLaSegundaRotacion` |
| 14 | Seguir recibiendo trabajos desactualizado. | Versión mínima con período de gracia (§13.1). | `test_servicio_agentes.py::test_version_minima_sin_gracia_si_se_fija_por_entorno` |

---

## 2. Transporte

**AG-10.** El agente **DEBE** hablar solo con la URL de backend de su configuración local, por
**HTTPS**. **PUEDE** aceptar `http://` únicamente hacia una dirección de *loopback*, para pruebas.
La URL **NO DEBE** llevar usuario ni contraseña.
— [`config.go`](../agente/internal/config/config.go), `Validar`; `config_test.go::TestHttpSoloHaciaLoopback`.

**AG-11.** El agente **DEBE** exigir TLS 1.2 o superior y validar la cadena del servidor contra
las raíces del sistema más, si se configura, una CA propia. **PUEDE** fijar además el SHA-256 de
la clave pública (SPKI) del servidor; si lo hace, **DEBE** comprobarlo **además de** la cadena, no
en su lugar.
— [`cliente.go`](../agente/internal/cliente/cliente.go), `Nuevo`; `cliente_test.go::TestTLSConCAPropiaYPin`.

**AG-12.** El agente **NO DEBE** seguir redirecciones: una redirección es la forma más sencilla de
que un intermediario se lleve el token.
— `cliente_test.go::TestNoSigueRedirecciones`.

**AG-13.** El agente **DEBE** acotar lo que lee de cada respuesta (hoy, 256 KiB) y fijar tiempos
máximos de conexión y respuesta.
— `cliente_test.go::TestLaRespuestaDesmedidaSeCorta`.

**AG-14.** El agente **DEBE** enviar `Accept: application/json`. (Sin esa cabecera, el backend
responde los 403 y 404 con una página HTML, no con JSON.)

**BE-10.** El backend **DEBE** servirse solo por TLS. Si hay un proxy inverso delante, el despliegue
**DEBE** declararlo en `PASSWD_TRUSTED_PROXIES`: los límites por dirección (§12.2) y la detección de
renovación desde otra IP (§4.4) usan la dirección del cliente, y sin esa variable todos los agentes
compartirían la del proxy.

**BE-11.** Con varios procesos o réplicas, el despliegue **DEBE** usar
`PASSWD_RATE_LIMIT_BACKEND=bd`; con el valor por omisión (`memoria`) cada proceso lleva su propio
presupuesto y los límites se multiplican.

**BE-12.** Los relojes del backend y de cada activo **DEBEN** estar sincronizados (NTP). El
vencimiento de un trabajo lo fija el backend y lo comprueba el agente con su propio reloj (§5.3).

---

## 3. Interruptor

**BE-20.** Con `agentes_enabled` apagado (`PASSWD_AGENTES_ENABLED=false`, valor por omisión), el
backend **DEBE** responder **404** a toda petición a `/api/agent/*` con un método existente, no
dar de alta ni enrolar agentes y no despachar trabajos. Una rotación autorizada mientras tanto
**DEBE** conservar su autorización y quedar disponible para la vía manual.
— [`app/api_agent/__init__.py`](../app/api_agent/__init__.py) (`_interruptor`),
[`app/servicios/rotacion.py`](../app/servicios/rotacion.py) (`_intentar_despacho`);
`test_api_agente.py::test_con_los_agentes_apagados_el_prefijo_no_existe`,
`test_despacho_agentes.py::test_con_los_agentes_apagados_la_autorizacion_se_mantiene`.

> **Límite conocido.** Un método que la ruta no admite (p. ej. `GET /api/agent/saludo`) responde
> **405** aunque el interruptor esté apagado: el enrutado resuelve el método antes de evaluar la
> dependencia del interruptor.

---

## 4. Identidad

### 4.1 Enrolamiento de un solo uso

**BE-30.** Un administrador da de alta el agente de un activo desde el panel. El backend **DEBE**:

- admitir como mucho **un agente vigente por activo** (restricción `UNIQUE` sobre
  `Agente.vinculo_vigente`), y ninguno en dispositivos de red;
- emitir un **token de enrolamiento de un solo uso**, mostrarlo una vez y guardar solo su hash
  SHA-256;
- hacer que caduque en **1 hora** (`VIDA_ENROLAMIENTO` en [`agentes.py`](../app/servicios/agentes.py));
- **anularlo al canjearlo**, de modo que un segundo uso no encuentre nada que validar;
- rechazar con **401** un token inexistente, ya usado o caducado, y auditar el rechazo.

— `test_servicio_agentes.py::test_el_enrolamiento_es_de_un_solo_uso`,
`test_un_enrolamiento_caducado_se_rechaza`, `test_api_agente.py::test_el_token_de_enrolamiento_no_sirve_dos_veces`.

**AG-30.** Al enrolarse, el agente **DEBE** generar un par **X25519** nuevo, enviar la clave pública
(32 bytes en base64 estándar), el nombre de su host y su versión, y guardar la identidad recibida.
La clave privada **NO DEBE** salir del activo.
— [`identidad.go`](../agente/internal/identidad/identidad.go), [`cmd/passwd-agente/main.go`](../agente/cmd/passwd-agente/main.go) (`enrolar`).

**AG-31.** El agente **NO DEBE** sustituir una identidad existente sin una orden explícita
(`passwd-agente enrolar --forzar`). Al enrolarse de nuevo, el journal de la identidad anterior deja
de ser legible (§8) y el agente lo retira.

### 4.2 Token de vida corta

**BE-31.** El token de identidad **DEBE** ser aleatorio (hoy, 32 bytes de CSPRNG en base64url) y
el backend **DEBE** guardar solo su hash SHA-256: un volcado de la base de datos no permite
suplantar a un agente. Su vida es `agentes_token_vida_horas` (24 h por omisión, mínimo 1 h).

**BE-32.** El backend **DEBE** rechazar con **401** y `WWW-Authenticate: Bearer` un token
inexistente, caducado, de un agente pendiente o de un agente revocado.
— `test_aceptacion_agentes.py::test_un_token_caducado_da_401_y_la_insignia_lo_dice`.

### 4.3 Renovación en el saludo y solapamiento

**BE-33.** En cada saludo, si al token le queda **un cuarto o menos** de su vida, el backend
**DEBE** emitir uno nuevo y devolverlo en `token_nuevo`. El token que estaba vigente **DEBE** seguir
valiendo **30 minutos** de solapamiento (`SOLAPAMIENTO`), para no dejar fuera a un agente que no
llegó a recibir la respuesta.
— `test_servicio_agentes.py::test_la_renovacion_deja_valer_el_token_anterior_solo_durante_el_solapamiento`.

**BE-34.** Si un agente se presenta con el token **anterior** dentro del solapamiento, el backend
**DEBE** emitirle otro token nuevo en ese mismo saludo (solo guarda hashes: no puede reenviar el
que se perdió).
— `test_servicio_agentes.py::test_quien_entra_con_el_token_anterior_recibe_otro_nuevo`.

**AG-32.** Al recibir `token_nuevo`, el agente **DEBE** usarlo desde la petición siguiente y
**DEBE** persistirlo de forma atómica antes del siguiente reinicio. Si no puede guardarlo, **DEBE**
registrarlo como error (lo perderá al reiniciar).
— `ejecutor_test.go::TestLaIdentidadRenovadaSePersisteYSeUsa`, `identidad_test.go::TestLaRenovacionReescribeSinDejarTemporales`.

### 4.4 Anomalía de dirección

**BE-35.** Si una renovación llega desde una IP distinta de la de la renovación anterior, y esta
ocurrió dentro de una vida de token, el backend **DEBE** registrar `agente_anomalia_ip` en la
bitácora y, salvo que `agentes_alertar_ip_distinta` esté apagado, avisar al equipo de seguridad.
El asiento se escribe siempre; el aviso es lo único que se puede desactivar.
— `test_servicio_agentes.py::test_renovar_desde_otra_ip_en_la_misma_ventana_es_una_anomalia`.

### 4.5 Caducidad, re-enrolamiento y revocación

**BE-36.** Una identidad caducada **NO DEBE** poder renovarse por ningún camino del protocolo. Solo
un token de enrolamiento nuevo, emitido desde el panel por un administrador reautenticado, devuelve
el agente al servicio, con un par de claves nuevo; el token viejo sigue sin valer.
— `test_aceptacion_agentes.py::test_la_caducidad_obliga_a_reenrolar`.

**AG-33.** Ante un **401** del saludo, el agente **DEBE** dejar de intentar trabajos, registrar que
su identidad no es válida y seguir reintentando con calma (la implementación de referencia, cada
15 minutos), por si el 401 fue pasajero. **NO DEBE** intentar enrolarse por su cuenta: hacerlo
exige un token de enrolamiento nuevo, emitido por una persona.

**BE-37.** Al revocar un agente, el backend **DEBE** anular toda su identidad, liberar el activo
para otro agente, devolver a la vía manual las credenciales del activo que rotaban por agente, y
cerrar sus trabajos sin estados fantasma: el pendiente se cancela y su rotación vuelve a
`AUTORIZADA`; el entregado queda «sin confirmar» (§10.3). Un agente revocado **NO DEBE** volver a
enrolarse: se da de alta otro.
— `test_servicio_agentes.py::test_revocar_devuelve_las_credenciales_al_flujo_manual`,
`test_despacho_agentes.py::test_un_agente_revocado_no_recibe_trabajos`.

### 4.6 Almacenamiento local de la identidad

**AG-34.** El archivo de identidad (token y clave privada) **DEBE** escribirse con permisos `0600`
y de forma atómica (temporal, `fsync`, renombrado, `fsync` del directorio). El agente **NO DEBE**
leerlo si alguien abrió sus permisos.
— [`archivo.go`](../agente/internal/archivo/archivo.go); `identidad_test.go::TestUnArchivoConPermisosAbiertosNoSeLee`.

---

## 5. El trabajo

### 5.1 Despacho (backend)

**BE-40.** El backend **NO DEBE** crear un trabajo si no se cumplen **todas** estas condiciones
(`despachar` en [`rotacion.py`](../app/servicios/rotacion.py)):

1. la rotación está en `AUTORIZADA` (invariante 1 de la gobernanza);
2. la credencial existe y su vía de rotación es `agente`;
3. el activo de la credencial tiene un agente vigente, `activo`, con identidad sin caducar y con
   las rotaciones habilitadas;
4. la versión del agente está admitida (§13.1);
5. el agente no tiene otro trabajo en curso;
6. la credencial no se rotó hace menos de `rotacion_anti_thrash_horas`, salvo que la rotación sea
   de tipo `emergencia` (§9).

Si el despacho falla tras autorizar, la autorización **DEBE** mantenerse y el motivo **DEBE**
quedar en la bitácora (`rotacion_no_despachada`).

**BE-41.** La contraseña nueva la **DEBE** generar el backend con su CSPRNG y la política vigente.
En reposo, la nueva y la actual del trabajo **DEBEN** guardarse con el cifrado del backend (Fernet),
como cualquier credencial, y **NO DEBEN** pasar a la credencial hasta que el agente confirme
`aplicado` (hallazgo H14 del plan).

### 5.2 Contenido

Una vez abierto el sobre (§6), el trabajo es un objeto JSON con estos campos:

| Campo | Tipo | Regla en el agente |
|---|---|---|
| `trabajo_id` | entero | **DEBE** ser > 0 y coincidir con el `trabajo_id` de la respuesta HTTP que lo trajo. |
| `tipo` | texto | **DEBE** ser exactamente `rotar_cuenta`. Es el **único** tipo de la versión 1 del contrato. |
| `usuario` | texto | **DEBE** cumplir `^[a-z_][a-z0-9_.-]{0,31}$`. |
| `nueva` | texto | **DEBE** ser UTF-8 válido, no vacía, de 256 bytes como mucho y sin `\n`, `\r` ni NUL; **DEBE** ser distinta de `actual`. |
| `actual` | texto | Mismas reglas que `nueva`. Se envía para poder revertir de forma determinista. |
| `expira_en` | texto | Fecha y hora **UTC sin zona**, formato `AAAA-MM-DDTHH:MM:SS`. |

**AG-40.** Un trabajo que incumple **cualquiera** de esas reglas **NO DEBE** ejecutarse: el agente
**DEBE** informarlo como `fallado`, con `verificacion = ninguna` y el motivo en `detalle`, sin tocar
la cuenta ni el journal. El motivo **NO DEBE** contener ninguna contraseña.
— [`contrato.go`](../agente/internal/contrato/contrato.go) (`Validar`), [`ejecutor.go`](../agente/internal/ejecutor/ejecutor.go) (`informarRechazo`);
`contrato_test.go::TestRechazosDelContrato`, `ejecutor_test.go::TestUnTrabajoQueIncumpleElContratoNoSeEjecuta`.

**AG-41.** Un campo desconocido en el contenido **NO DEBE** cambiar lo que hace el agente: o se
ignora o se rechaza el trabajo. Cualquier acción nueva exige un `tipo` nuevo, y eso es un cambio de
versión del contrato (§13.2). La implementación de referencia lo ignora.

### 5.3 Vencimiento

**BE-42.** Todo trabajo **DEBE** tener una ventana de validez de `rotacion_ventana_job_min` minutos
(15 por omisión, mínimo 1) desde el despacho.

**AG-42.** El agente **NO DEBE** aplicar un trabajo cuyo `expira_en` sea igual o anterior a su
reloj. Lo informa como `fallado` (AG-40).
— `contrato_test.go::TestRechazosDelContrato` («vencido», «justo al vencer»), `ejecutor_test.go::TestUnTrabajoVencidoNoSeAplica`.

**AG-43.** El token Fernet del sobre lleva su fecha de creación. El agente **NO DEBE** aplicarle
caducidad: la validez del trabajo la da `expira_en`.

### 5.4 Un solo trabajo a la vez

**BE-43.** El backend **DEBE** garantizar un solo trabajo activo (`pendiente` o `entregado`) por
agente; hoy lo impone la base de datos con `UNIQUE` sobre `TrabajoRotacion.activo_agente_id`.

**AG-44.** El agente **DEBE** ejecutar un trabajo cada vez. Mientras su journal guarde un trabajo
sin cerrar o un resultado sin entregar, **NO DEBE** pedir otro. Si aun así recibe un trabajo
distinto del que tiene en curso, **DEBE** rechazarlo (AG-40).
— `contrato_test.go::TestRechazosDelContrato` («concurrente»),
`ejecutor_test.go::TestSinRedElResultadoEsperaEnElJournalYNoSeAceptaOtroTrabajo`.

### 5.5 Entrega y re-entrega

**BE-44.** El backend **DEBE** entregar cada trabajo **solo al agente que lo tiene asignado**,
sellado a la clave pública registrada en su enrolamiento, y **DEBE** auditar cada entrega. Mientras
la ventana siga abierta, **DEBE** volver a entregar el mismo trabajo si el agente lo pide otra vez
(contando los intentos), con un sobre nuevo.

**AG-45.** Si recibe de nuevo el trabajo que su journal ya tiene en curso, el agente **NO DEBE**
volver a aplicarlo: lo resuelve la recuperación (§8.3).
— `contrato_test.go::TestElMismoTrabajoEnCursoNoEsConcurrente`.

---

## 6. Cifrado del sobre

**BE-50 / AG-50.** El trabajo viaja **sellado al par X25519 del agente**, además de dentro de TLS.
Backend y agente **DEBEN** implementar exactamente este esquema, sin variaciones:

```
compartido = X25519(efímera_privada_del_backend, agente_pub)          # 32 bytes
clave      = HKDF-SHA256(compartido,
                         salt = efímera_pub ‖ agente_pub,              # 32 + 32 bytes, crudos
                         info = "passwd-agente/trabajo/v1",
                         largo = 32)
token      = Fernet(base64url(clave)).encrypt(JSON del trabajo, UTF-8)
sobre      = {"v": 1, "efimera": base64(efímera_pub), "token": token}
```

- El backend **DEBE** usar una clave efímera nueva por sobre
  (`test_servicio_agentes.py::test_cada_sobre_usa_una_clave_efimera_distinta`).
- `efimera` va en base64 **estándar**; `token` es un token Fernet (base64url).
- El agente **DEBE** rechazar un sobre con `v` distinto de 1, una efímera que no mida 32 bytes o un
  token cuyo HMAC no verifique, **sin** distinguir en el error entre «no es para esta clave» y «fue
  alterado». **DEBE** comprobar el HMAC **antes** de quitar el relleno.
- **NO DEBE** usarse un esquema propio: solo primitivas estándar (`cryptography` en el backend;
  biblioteca estándar de Go en el agente, con Fernet según su especificación pública).

**Vector compartido.** [`tests/vectores/cifrado_agente.json`](../tests/vectores/cifrado_agente.json)
contiene una clave privada **de prueba**, un sobre y su contenido esperado. Toda implementación del
agente **DEBE** abrir ese sobre y obtener exactamente ese contenido, y el backend **DEBE** seguir
abriéndolo. Las dos pruebas son `test_servicio_agentes.py::test_el_vector_compartido_con_el_agente_go_se_abre`
y `sobre_test.go::TestElVectorDelBackendSeAbre`.

**Qué no protege** (H14). El sellado protege la **entrega**: un token de agente robado sin la clave
privada no basta para leer un trabajo. No protege la contraseña en reposo en el backend (que la
guarda con su Fernet porque tiene que escribirla al confirmarse) ni frente a un backend comprometido
entero, que ya tiene todas las contraseñas.

---

## 7. Protocolo de dos fases

**AG-60.** Para un trabajo válido, el agente **DEBE** seguir este orden
([`ejecutor.go`](../agente/internal/ejecutor/ejecutor.go), `Procesar` y `decidir`):

1. **Journal primero.** Escribir el trabajo en el journal en fase `aplicando` **antes** de tocar la
   cuenta. Si no puede escribirlo, **NO DEBE** tocar la cuenta: informa `fallado`.
   — `ejecutor_test.go::TestElJournalSeEscribeAntesDeTocarLaCuenta`.
2. **Aplicar** `actual → nueva`. Quien aplica **DEBE** comprobar antes que `actual` autentica la
   cuenta; si no, no cambia nada (HE-05). Si quien aplica **rechaza sin tocar la cuenta** (cuenta
   fuera de la lista, `actual` que no autentica…; en el helper, la marca `sin_cambios`), el agente
   **DEBE** informar `fallado` con ese motivo en el `detalle` y **NO DEBE** restaurar ni deducir
   nada. — `ejecutor_test.go::TestSiElHelperRechazaSinTocarNadaSeInformaSuMotivo`,
   `helper_test.go::TestLosRechazosDicenQueNoSeTocoNadaYUnFalloAlFijarNo`.
3. **Decidir** qué contraseña vale de verdad, verificando en el propio sistema:

   | Verificación | Acción | Resultado que informa |
   |---|---|---|
   | `nueva` autentica | — | `aplicado`, `verificacion = local` |
   | `nueva` no, `actual` sí | Ninguna: la cuenta conserva la anterior | `fallado`, `ninguna` |
   | Ninguna de las dos | Restaurar `actual` y verificarla | `revertido`, `ninguna` |
   | Tras restaurar, `actual` sigue sin autenticar | — | `fallado`, `ninguna`, «requiere intervención manual» |

   Un «no autentica» es una **respuesta**. Si quien verifica **no contesta** (socket caído, tiempo
   agotado), el agente **NO DEBE** concluir nada ni restaurar: deja el journal en `aplicando` y la
   recuperación (AG-74) lo reintenta. — `ejecutor_test.go::TestSinHelperNoSeConcluyeNadaYSeReintenta`.

4. **Cerrar en el journal**: fase `cerrada` con el resultado decidido.
5. **Informar** al backend (§10).
6. **Purgar** el trabajo del journal **solo después** de que el backend acepte el resultado, o de
   que responda que ya no lo admite (§8.3).

— `ejecutor_test.go::TestAplicaVerificaYConfirma`, `TestSiLaNuevaNoVerificaRevierte`;
`integracion_test.go::TestIntegracionCicloCompletoSobreUnaCuentaReal`, `TestIntegracionRevierteSiLaNuevaNoVerifica`.

**AG-61.** El agente **solo PUEDE** declarar verificación `local` (o `ninguna`). La verificación
`remota` la hará el backend (versión 2.2.0), y el backend **DEBE** rechazar con 400 que un agente
la declare. `local` prueba que la contraseña autentica la cuenta en el sistema operativo, no que la
credencial siga sirviendo para su servicio (plan, §2.2.1).
— `test_despacho_agentes.py::test_el_agente_no_puede_declarar_verificacion_remota`.

**AG-62.** El agente **NO DEBE** escribir ninguna contraseña en su registro, en el `detalle` del
resultado ni en mensajes de error.

---

## 8. Journal y recuperación

### 8.1 Contenido y cifrado

**AG-70.** El journal **DEBE** contener solo el trabajo en curso (con su fase, y su resultado si ya
se decidió) y, **sin secretos**, la fecha de la última rotación aplicada de cada cuenta, que usa el
anti-thrash local (§9.2).

**AG-71.** El journal **DEBE** ir cifrado con una clave que dependa de la identidad del agente, de
modo que solo sirva en ese activo y con esa identidad. La implementación de referencia usa
AES-256-GCM con una clave HKDF-SHA256 de la clave privada X25519 (`info = "passwd-agente/journal/v1"`).
Este formato es local al agente y no forma parte del intercambio con el backend.
— [`journal.go`](../agente/internal/journal/journal.go); `journal_test.go::TestOtraIdentidadNoLeeElJournal`.

**AG-72.** El journal **DEBE** escribirse con permisos `0600` y de forma atómica, y el agente **NO
DEBE** leerlo si sus permisos están abiertos.
— `journal_test.go::TestUnJournalConPermisosAbiertosNoSeLee`.

> **Limitación conocida.** Al purgar, el archivo nuevo sustituye al anterior por renombrado, pero
> los bloques antiguos del disco no se sobrescriben. Por eso el contenido va cifrado y la clave
> depende de la identidad: re-enrolar deja ilegible cualquier resto.

### 8.2 Purga

**AG-73.** Al cerrar un trabajo, el agente **DEBE** retirar del journal el trabajo y sus
contraseñas.

**BE-70.** Al cerrar un trabajo por cualquier vía (resultado, vencimiento sin recoger, cancelación,
resolución manual), el backend **DEBE** purgar `nueva_cifrada` y `actual_cifrada`. La única
excepción es el trabajo entregado y sin confirmar (§10.3), que conserva sus secretos hasta que una
persona lo resuelva, porque la nueva puede ser la que vale en el activo. El asiento del libro mayor
(`rotaciones_credencial`) **NO DEBE** purgarse nunca. El respaldo **NO DEBE** reponer trabajos.
— `test_despacho_agentes.py::test_aplicado_escribe_la_contrasena_archiva_la_anterior_y_purga`,
`test_el_respaldo_repone_agentes_revocados_y_nunca_trabajos`;
`test_aceptacion_agentes.py::test_tras_un_ciclo_completo_ninguna_contrasena_queda_en_claro`.

### 8.3 Recuperación tras un reinicio

**AG-74.** En cada ciclo, **antes** de pedir trabajo —y aunque su versión ya no esté admitida
(AG-111)—, el agente **DEBE** resolver lo que el journal dejó a medias (`Recuperar`):

- **Fase `aplicando`** (murió durante o justo después de aplicar): **NO DEBE** volver a aplicar.
  **DEBE** decidir con la tabla de AG-60 (paso 3) qué contraseña vale, cerrar e informar.
- **Fase `cerrada`** (el resultado estaba decidido pero no se entregó): **DEBE** reintentar la
  entrega.

**AG-75.** Mientras quede un resultado sin entregar, el agente **NO DEBE** aceptar trabajo nuevo y
**DEBE** reintentar en el ciclo siguiente. Si el backend responde **409**, **404** o **403** (ya
cerrado —por ejemplo, resuelto a mano—, inexistente o ajeno) o **400** o **422** (un resultado que
nunca admitirá), **DEBE** dar el resultado por descartado y purgar: reintentarlo bloquearía al
agente para siempre, y el backend lo verá «sin confirmar» (§10.3). Cualquier otro error (red, 5xx,
429, 401) **DEBE** conservar el journal para reintentar.
— `ejecutor_test.go::TestUnResultadoQueElBackendNuncaAdmitiraNoBloqueaAlAgente`.

— `ejecutor_test.go::TestTrasUnaCaidaRecuperaYConfirmaLoAplicado`,
`TestTrasUnaCaidaAntesDeAplicarInformaQueNoSeAplico`;
`integracion_test.go::TestIntegracionRecuperaTrasUnReinicio`.

**Nunca un estado indeterminado en silencio.** Si el agente no llega a informar, el backend lo
detecta por su lado (§10.3) y pide a una persona que lo resuelva.

---

## 9. Anti-thrash

### 9.1 En el backend

**BE-80.** El backend **NO DEBE** despachar a un agente la rotación de una credencial rotada hace
menos de `rotacion_anti_thrash_horas` (24 por omisión). La **única** excepción es una rotación de
tipo `emergencia`: se despacha, y el salto **DEBE** quedar en la bitácora
(`rotacion_anti_thrash_saltado`) y, por el tipo y la antigüedad al rotar, en el libro mayor.
— `test_despacho_agentes.py::test_el_anti_thrash_frena_salvo_en_emergencia`.

### 9.2 En el agente

**AG-80.** El agente **DEBE** aplicar además un intervalo mínimo **local** entre dos rotaciones
aplicadas de la misma cuenta, como defensa ante un backend que martillee. Un trabajo que lo
incumple se informa como `fallado` (AG-40) y no se ejecuta. El intervalo es configuración local
(`anti_thrash_min`, 60 minutos por omisión); el backend **NO PUEDE** cambiarlo.
— `contrato_test.go::TestRechazosDelContrato` («anti-thrash»), `TestPasadoElIntervaloLocalSePuedeRotar`;
`ejecutor_test.go::TestElAntiThrashLocalFrenaLaSegundaRotacion`.

> En la implementación de referencia, `anti_thrash_min: 0` equivale al valor por omisión (60), no
> a desactivarlo, y un valor negativo impide arrancar ([`config.go`](../agente/internal/config/config.go)).
> Como el intervalo local es mucho menor que el del backend, no interfiere con la vía de
> emergencia salvo que se rote la misma cuenta dos veces en menos de una hora.

---

## 10. Resultado y cierre

### 10.1 Lo que informa el agente

**AG-90.** El agente **DEBE** informar exactamente uno de `aplicado`, `revertido` o `fallado` por
trabajo, con `verificacion` `local` (solo con `aplicado`) o `ninguna`, y un `detalle` opcional de
2000 caracteres como mucho y sin secretos.

### 10.2 Lo que hace el backend

**BE-90.** El backend **DEBE** aceptar **un único resultado por trabajo**, solo del agente al que
pertenece y solo si el trabajo está `entregado` (anti-replay). Un segundo resultado responde 409;
el de otro agente, 403; ambos se auditan.
— `test_despacho_agentes.py::test_un_segundo_resultado_se_rechaza`, `test_un_agente_no_cierra_el_trabajo_de_otro`,
`test_un_trabajo_sin_entregar_no_admite_resultado`.

**BE-91.** Con `aplicado`, el backend **DEBE** escribir la contraseña nueva **por el punto único de
escritura** de la credencial —el mismo de la vía manual—, archivar la anterior en el historial,
reiniciar la antigüedad y cerrar la rotación. Con `revertido` o `fallado` **NO DEBE** tocar la
contraseña registrada y **DEBE** alertar.

### 10.3 Vencimiento y «sin confirmar»

**BE-92.** Al entregar, al consultar el panel y en el mantenimiento periódico, el backend **DEBE**:

- cerrar como `expirado` el trabajo **pendiente** cuya ventana venció, purgarlo y devolver su
  rotación a `AUTORIZADA` (la decisión de dos personas sigue en pie);
- marcar como **sin confirmar** el trabajo **entregado** sin resultado cuando han pasado su ventana
  y un margen de **15 minutos** (`MARGEN_CONFIRMACION`), conservar sus secretos y alertar. Mientras
  esté así, la credencial no admite otra rotación.
— `test_despacho_agentes.py::test_un_pendiente_vencido_vuelve_a_quedar_autorizado`,
`test_un_entregado_sin_respuesta_queda_sin_confirmar_con_sus_secretos`.

**BE-93.** Un trabajo sin confirmar, o entregado a un agente revocado, solo lo **PUEDE** resolver un
administrador, diciendo si la contraseña nueva quedó aplicada en el activo; nadie **PUEDE**
resolverlo a mano mientras el agente aún puede confirmarlo.
— `test_despacho_agentes.py::test_no_se_resuelve_a_mano_lo_que_el_agente_aun_puede_confirmar`.

> El resultado tardío del agente sigue siendo admisible mientras el trabajo continúe `entregado`,
> también después de marcarse «sin confirmar»: es la mejor evidencia de lo que quedó en el activo.

**BE-94.** Un trabajo **entregado** no se **PUEDE** cancelar: el agente puede estar aplicándolo.
Uno pendiente, sí.
— `test_despacho_agentes.py::test_cancelar_retira_un_pendiente_pero_no_un_entregado`.

---

## 11. Telemetría

**AG-100.** La telemetría **DEBE** limitarse a métricas agregadas y datos de hardware del propio
host: uso de CPU, memoria y disco en porcentaje, tiempo encendido, sistema operativo, kernel, modelo
de CPU, memoria total y, por disco, punto de montaje, sistema de archivos, tamaño y porcentaje usado.
**NO DEBE** incluir procesos, usuarios, sesiones, pulsaciones ni rutas más allá del punto de montaje.
— [`telemetria.go`](../agente/internal/telemetria/telemetria.go).

**AG-101.** El agente **DEBE** recortar antes de enviar y marcar `recortada: true` si recortó algo:

| Tope | Agente (referencia) | Backend |
|---|---|---|
| Cuerpo de la petición | 12 KiB | **16 KiB**; por encima, 413 |
| Discos | 32 | Guarda 32 y marca `recortada`; más de 256 en la petición, 422 |
| Textos (SO, kernel, CPU, montaje) | 120 caracteres | Guarda 120; más de 255 en la petición, 422 |
| `sistema_archivos` de un disco | 120 caracteres | Guarda 120; más de 255 en la petición, 422 |
| Porcentajes | — | Se acotan a 0–100 |
| Enteros (bytes, segundos) | — | Negativos pasan a 0 |

— `telemetria_test.go::TestAcotarRecortaYLoDice`, `test_servicio_agentes.py::test_la_telemetria_se_acota_y_refresca_el_contacto`,
`test_api_agente.py::test_la_telemetria_tiene_su_propio_tope`.

**AG-102.** Una métrica que no se puede leer **DEBE** enviarse vacía (`null`), no impedir el latido.

**BE-100.** La telemetría **NO DEBE** disparar ninguna acción. El backend la guarda, refresca el
último contacto del agente y la purga pasada `agentes_retencion_telemetria_dias` (30 por omisión).
Ante un exceso, el backend **DEBE** rechazar, no ampliar su límite.

---

## 12. Superficie del backend

**BE-110.** `/api/agent` **DEBE** ser la única superficie que habla con los agentes, autenticada por
el Bearer de cada agente, sin cookies ni CSRF. **NO DEBE** existir ninguna ruta por la que un agente
lea un secreto fuera de su propio trabajo.
— `test_api_agente.py::test_toda_ruta_del_agente_exige_su_identidad`.

### 12.1 Topes de cuerpo

**BE-111.** El backend **DEBE** rechazar con **413**, antes de autenticar, un cuerpo de más de
**4 KiB** en cualquier ruta del agente y de más de **16 KiB** en la telemetría. El rechazo cuenta
para el límite por dirección y se audita.
— `test_api_agente.py::test_toda_ruta_del_agente_tiene_tope_de_cuerpo`.

### 12.2 Límites de tasa

**BE-112.** El backend **DEBE** limitar, en ventanas de 5 minutos, **300 peticiones por dirección**
(antes de autenticar) y **120 por agente**; y, en ventanas de 15 minutos, **10 intentos de
enrolamiento por dirección**. Al superarlos responde **429**.
— `test_api_agente.py::test_el_limite_de_tasa_del_agente`.

### 12.3 Auditoría

**BE-113.** El backend **DEBE** auditar todo cambio de estado (enrolamiento, renovación de
identidad, entrega de un trabajo, su resultado, vencimientos) y **todo rechazo** de la API, que
debe sobrevivir a la anulación de la transacción de la petición fallida. **NO DEBE** auditar el
latido rutinario, la consulta sin trabajo ni la telemetría: quedan como «último contacto». Un 429
repetido se audita **una vez por ventana y dirección**, para que nadie pueda llenar la bitácora a
base de peticiones.
— `test_api_agente.py::test_sin_identidad_el_rechazo_queda_en_la_bitacora`,
`test_un_agente_no_cierra_el_trabajo_de_otro_y_queda_auditado`.

> **Límite conocido.** Dos rechazos no pasan por el registro de la API y por tanto no se auditan:
> el **422** de validación del cuerpo (campos de más longitud de la admitida, JSON roto) y el
> **413** del límite global de la aplicación (`PASSWD_MAX_REQUEST_BYTES`, 64 KiB por omisión), que
> corta antes de llegar al enrutado. Detalle en [`referencia-api-agent.md`](referencia-api-agent.md).

---

## 13. Helper con privilegios (agente Linux, hallazgo H15)

El agente Linux corre **sin privilegios** y no puede ganarlos: no hay `sudo` ni binarios `setuid`
(con `NoNewPrivileges` y sin capacidades no funcionarían). Quien cambia una contraseña es un helper
root aparte, de una sola acción. Esta sección obliga a toda implementación Linux; la de Windows
(2.1.0) definirá su equivalente con las mismas garantías.

| ID | Requisito | Dónde | Prueba |
|---|---|---|---|
| HE-01 | El agente **NO DEBE** tener capacidades ni poder ganar privilegios (`NoNewPrivileges`, `CapabilityBoundingSet=` vacío, `RestrictSUIDSGID`). | [`passwd-agente.service`](../agente/instalacion/passwd-agente.service) | — |
| HE-02 | El helper **DEBE** activarse por un **socket local de systemd** (`Accept=yes`), abrir una instancia por conexión, atender **una** petición y terminar. **NO DEBE** tener red (`PrivateNetwork=yes`). | [`passwd-agente-helper.socket`](../agente/instalacion/passwd-agente-helper.socket), [`passwd-agente-helper@.service`](../agente/instalacion/passwd-agente-helper@.service) | — |
| HE-03 | El helper **DEBE** comprobar por **`SO_PEERCRED`** que quien llama por el socket es el usuario del agente, y rechazar a cualquier otro (root incluido). Fuera del socket, solo **PUEDE** atender a root (uso manual). Un socket sin credenciales legibles no identifica a nadie. | [`cmd/passwd-agente-helper/main.go`](../agente/cmd/passwd-agente-helper/main.go) (`llamante`), [`helper.go`](../agente/internal/helper/helper.go) | `helper_test.go::TestRechazos`, `TestRootPuedeInvocarloAManoFueraDelSocket`; `integracion_test.go::TestIntegracionSoloAtiendeAlUsuarioDelAgente` |
| HE-04 | El helper **DEBE** atender solo cuentas de **su lista**, en `/etc/passwd-agente/helper.json`, propiedad de **root** y no escribible por grupo ni otros (si no, no arranca), y solo si la cuenta **existe**. **NUNCA DEBE** crear una cuenta. | `CargarConfig`, `Atender` | `helper_test.go::TestLaConfiguracionDebeSerDeRootYNoEscribiblePorOtros`; `integracion_test.go::TestIntegracionRechazosDelHelper` |
| HE-05 | Antes de **aplicar**, el helper **DEBE** comprobar que la contraseña `actual` del inventario autentica la cuenta; si no, **NO DEBE** cambiar nada. | `Atender` (`aplicar`) | `helper_test.go::TestSiLaActualNoCoincideNoSeTocaNada` |
| HE-06 | El helper **DEBE** verificar por **PAM** con un servicio propio (`/etc/pam.d/passwd-agente-helper`) que use **solo `pam_unix`**: sin `faillock` ni otros factores. Si falta ese archivo, **NO DEBE** arrancar (PAM caería en `other`). | [`passwd-agente-helper.pam`](../agente/instalacion/passwd-agente-helper.pam), `main.go` | — |
| HE-07 | El helper **DEBE** fijar la contraseña con **`chpasswd`** por ruta absoluta, con entorno limpio y la contraseña por la entrada estándar, **nunca** en la línea de órdenes. | `main.go` (`Fijar`) | `helper_test.go::TestAplicarCompruebaLaActualYFijaLaNueva` |
| HE-08 | El protocolo del helper **DEBE** ser cerrado: tres acciones (`verificar`, `aplicar`, `restaurar`), una línea JSON de 4 KiB como mucho, campos desconocidos rechazados. | `leer` | `helper_test.go::TestUnaPeticionDesmedidaOConCamposExtraSeRechaza` |
| HE-09 | La respuesta y el registro del helper **NUNCA DEBEN** contener una contraseña. | `Respuesta` | `helper_test.go::TestLaRespuestaNuncaLlevaUnaContrasena` |

> **Alcance de HE-05.** La comprobación de la contraseña actual protege `aplicar`. `restaurar` —el
> paso de reversión, que se usa precisamente cuando ni la nueva ni la actual autentican— fija el
> valor recibido sin comprobación previa, y `verificar` responde sin retardo ni bloqueo por
> fallos. Ambas solo están al alcance del usuario del agente y solo sobre las cuentas de la lista
> de root; esa lista es, por tanto, el límite real de lo que un agente comprometido puede tocar.

---

## 14. Versiones

### 14.1 Versión del agente

**AG-110.** El agente **DEBE** informar de su versión al enrolarse y en cada saludo, con formato
`X.Y.Z` (admite prefijo `v` y sufijo de pre-release en el último número).

**BE-120.** Con `agentes_version_minima` fijada, el backend **NO DEBE** despachar ni entregar
trabajos a un agente de versión inferior (o ilegible) una vez vencida la gracia de
`agentes_gracia_version_dias` (14 por omisión), contada desde que el mínimo se fijó **en el panel**.
Fijado por variable de entorno, rige sin gracia. El saludo **DEBE** informar al agente de
`version_minima`, `version_admitida` y `version_en_gracia`.
— `test_servicio_agentes.py::test_version_minima_sin_gracia_si_se_fija_por_entorno`.

**AG-111.** Con `version_admitida: false`, el agente **NO DEBE** pedir trabajos; **PUEDE** seguir
latiendo y enviando telemetría, y **DEBE** entregar el resultado que tuviera pendiente (AG-74): el
backend lo acepta, y callarlo dejaría la rotación «sin confirmar».
— `ejecutor_test.go::TestConLaVersionNoAdmitidaSeEntregaLoPendiente`.

### 14.2 Versión del contrato

Este documento es la **versión 1**. Sus marcas en el protocolo son `"v": 1` en el sobre, la
etiqueta HKDF `passwd-agente/trabajo/v1` y el `tipo` `rotar_cuenta`.

**CO-01.** Un cambio **compatible** —un campo nuevo y opcional en una respuesta o en una petición,
un dato más de telemetría— **PUEDE** hacerse sin cambiar la versión del contrato. Backend y agente
**DEBEN** ignorar los campos que no conocen en los cuerpos JSON del API (hoy lo hacen: Pydantic los
descarta y Go no los decodifica). Se anota en este documento y en las notas de la versión.

**CO-02.** Un cambio **incompatible** —un `tipo` de trabajo nuevo, un campo nuevo que cambie lo que
hace el agente, otro esquema de sellado, otro significado de un estado— **DEBE** subir la versión
del contrato. Si afecta al sobre, **DEBE** subir a la vez `v` y la etiqueta HKDF (`…/v2`). El
backend **DEBE** seguir sirviendo la versión anterior a los agentes que no la superen, usando la
versión que informan en el saludo y la versión mínima (§14.1) para retirarla de forma ordenada.

**CO-03.** Un agente que reciba un sobre de versión desconocida **NO DEBE** intentar abrirlo con
otro esquema: lo informa como `fallado`.

**CO-04.** Todo cambio de este contrato **DEBE** ir acompañado de sus pruebas en ambos lados y, si
toca el sellado, de un vector nuevo en `tests/vectores/`.

---

## 15. Trazabilidad

La tabla criterio → prueba de la versión 1.4.0 está en la cabecera de
[`tests/test_aceptacion_agentes.py`](../tests/test_aceptacion_agentes.py). Las pruebas del agente
Go viven junto a cada paquete en [`agente/internal/`](../agente/internal/); las de integración
(`integracion_test.go`) necesitan root, PAM y `chpasswd` reales y corren en el job «agente» de la CI.

## Documentos relacionados

- [`referencia-api-agent.md`](referencia-api-agent.md) — cada ruta de `/api/agent`, con códigos y ejemplos.
- [`arquitectura-agentes.md`](arquitectura-agentes.md) — piezas, flujos y modelo de amenaza.
- [`guia-instalacion-agente-linux.md`](guia-instalacion-agente-linux.md) — instalación, helper y unidades systemd.
- [`plan-rotacion-agentes.md`](plan-rotacion-agentes.md) — el porqué: §1.7 (H14, H15), §2, §3, §4, §8.2.
- [`notas-version-1.3.0.md`](notas-version-1.3.0.md) — la gobernanza de dos administradores sobre la que se apoya.
- [`versionado.md`](versionado.md) — política de versiones del producto.
