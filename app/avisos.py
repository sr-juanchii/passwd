"""Avisos dinámicos por usuario, resueltos desde la matriz de permisos.

A diferencia de ``notifications.enviar_alerta`` —que escribe a una lista fija
(``PASSWD_NOTIFY_TO``) pensada para el equipo de seguridad—, este módulo decide
los destinatarios **en tiempo de ejecución** preguntando quién tiene acceso a
cada activo (``app.access.usuarios_con_acceso_a_activo``). Cubre tres familias:

1. **Actividad propia y permisos propios**: cada usuario recibe aviso del inicio
   de sesión (con IP y agente) y de los cambios en sus propias concesiones de
   acceso o en su rol.
2. **Credenciales compartidas**: al actualizar la contraseña de un activo, se
   avisa a los DEMÁS usuarios con acceso a ese activo de que hubo un cambio.
3. **Caducidad de rotación**: aviso preventivo a quienes usan la credencial
   cuando se acerca la fecha del cambio obligatorio.

Regla inviolable de contenido
-----------------------------
Estos correos comunican **el hecho, no el secreto**. Nunca incluyen la
contraseña de un servidor, ni el valor anterior, ni el nuevo, ni ninguna pista
sobre ellos (longitud, prefijos, si «se parece» a la anterior). Un aviso de
cambio dice qué activo cambió, quién lo cambió y cuándo — nada más. El motivo es
directo: el correo es un canal que la aplicación no controla (buzones ajenos,
reenvíos, copias en servidores intermedios, backups de correo), de modo que
cualquier secreto que salga por ahí queda fuera del modelo de custodia del vault.
``tests/test_avisos_dinamicos.py`` verifica esta propiedad de forma explícita.

Todo el envío es de mejor esfuerzo: un fallo de SMTP se registra y nunca rompe
la operación que lo originó.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.access import usuarios_con_acceso_a_activo, usuarios_con_acceso_a_credencial
from app.config import get_settings
from app.models import (
    ACTIVO_DISPOSITIVO,
    ACTIVO_FISICO,
    ACTIVO_HIPERVISOR,
    ACTIVO_VM,
    Credencial,
    Usuario,
    ahora_utc,
)
from app.notifications import correo_operativo, enviar_a_usuario, enviar_a_usuarios
from app.security import ratelimit

logger = logging.getLogger("passwd.avisos")

ETIQUETAS_ACTIVO = {
    ACTIVO_FISICO: "servidor físico",
    ACTIVO_HIPERVISOR: "hipervisor",
    ACTIVO_VM: "máquina virtual",
    ACTIVO_DISPOSITIVO: "dispositivo de red",
}

_PIE = (
    "\n\n---\n"
    "Aviso automático del Gestor de Contraseñas de Servidores.\n"
    "Este mensaje NUNCA incluye contraseñas del inventario.\n"
    "Si no reconoce esta actividad, contacte de inmediato al administrador."
)


def avisos_activos() -> bool:
    """¿Están habilitados los avisos dinámicos por usuario?"""
    return bool(correo_operativo() and get_settings().notify_users_enabled)


def _una_vez_por(db: Session, clave: str, ventana_minutos: int) -> bool:
    """True la PRIMERA vez que se pide ``clave`` dentro de la ventana.

    Deduplicación construida sobre el limitador de tasa ya existente (límite 1):
    evita convertir la actividad normal de una sesión en una lluvia de correos.
    Con ``PASSWD_RATE_LIMIT_BACKEND=bd`` la deduplicación es compartida entre
    workers y réplicas; con el backend en memoria es por proceso, de modo que con
    varios workers podría salir un aviso por proceso (ver la nota de despliegue en
    ``docs/notificaciones-y-mfa-correo.md``).
    """
    return ratelimit.permitir_intento(clave, limite=1, ventana_minutos=ventana_minutos, db=db)


# ---------------------------------------------------------------------------
# 1. Actividad propia y cambios en los permisos propios
# ---------------------------------------------------------------------------


def aviso_inicio_sesion(db: Session, usuario: Usuario, ip: str, agente: str) -> None:
    """Avisa al usuario de que se abrió una sesión con su cuenta.

    Es el aviso de actividad de mayor valor defensivo: si alguien entra con una
    contraseña robada, el titular lo ve aunque el atacante borre su rastro en la
    interfaz. Se envía una vez por sesión (no por petición).
    """
    if not avisos_activos():
        return
    cuerpo = (
        f"Se inició una sesión con su cuenta «{usuario.username}».\n\n"
        f"  Fecha y hora (UTC): {ahora_utc():%Y-%m-%d %H:%M:%S}\n"
        f"  Dirección IP:       {ip or 'desconocida'}\n"
        f"  Navegador/cliente:  {(agente or 'desconocido')[:200]}\n"
        f"  Rol activo:         {usuario.rol}\n\n"
        "Si fue usted, no hace falta ninguna acción."
    ) + _PIE
    enviar_a_usuario(usuario, "Inicio de sesión en su cuenta", cuerpo)


def aviso_actividad_sensible(
    db: Session,
    usuario: Usuario,
    sesion_id: int,
    categoria: str,
    detalle: str,
) -> None:
    """Avisa al usuario de una acción sensible que realizó en su sesión.

    Se deduplica por (sesión, categoría): la primera vez que en una sesión se
    revela una credencial, se exporta el inventario o se modifica una credencial,
    el titular recibe un aviso; las repeticiones de esa misma categoría dentro de
    la misma sesión no generan más correo. Así el aviso conserva su valor de
    detección sin que un usuario que trabaja normalmente reciba decenas de
    mensajes (que además acabaría filtrando, perdiendo la señal).
    """
    if not avisos_activos():
        return
    if not _una_vez_por(db, f"aviso-sesion:{sesion_id}:{categoria}", ventana_minutos=24 * 60):
        return
    cuerpo = (
        f"Se registró actividad sensible en su sesión actual:\n\n"
        f"  Actividad:          {detalle}\n"
        f"  Fecha y hora (UTC): {ahora_utc():%Y-%m-%d %H:%M:%S}\n\n"
        "Recibirá un único aviso por tipo de actividad y sesión. La bitácora de "
        "auditoría conserva el registro completo."
    ) + _PIE
    enviar_a_usuario(usuario, "Actividad sensible en su sesión", cuerpo)


def aviso_cambio_permisos_propios(
    db: Session, usuario: Usuario, accion: str, detalle: str
) -> None:
    """Avisa al usuario de un cambio en sus PROPIOS permisos de acceso.

    Cubre la concesión y la revocación de acceso a activos y el cambio de rol: el
    titular debe saber siempre qué puede y qué ya no puede hacer, y un cambio de
    permisos que no reconozca es un indicio de compromiso de una cuenta
    administrativa.
    """
    if not avisos_activos():
        return
    cuerpo = (
        f"Sus permisos de acceso han cambiado.\n\n"
        f"  Cambio:             {accion}\n"
        f"  Detalle:            {detalle}\n"
        f"  Fecha y hora (UTC): {ahora_utc():%Y-%m-%d %H:%M:%S}\n\n"
        "El cambio ya está en vigor. Si tenía una sesión abierta, puede que deba "
        "volver a iniciarla."
    ) + _PIE
    enviar_a_usuario(usuario, "Cambio en sus permisos de acceso", cuerpo)


# ---------------------------------------------------------------------------
# 2. Auditoría de credenciales compartidas
# ---------------------------------------------------------------------------


def aviso_credencial_compartida_actualizada(
    db: Session,
    credencial: Credencial,
    autor: Usuario,
    *,
    password_cambiada: bool,
) -> int:
    """Avisa a los DEMÁS usuarios con acceso de que la credencial fue modificada.

    Devuelve el número de avisos enviados.

    El cuerpo comunica **únicamente que hubo una actualización**: activo, servicio,
    usuario de acceso, quién la hizo y cuándo. No incluye la contraseña nueva, ni
    la anterior, ni ninguna característica de ellas. Quien necesite la contraseña
    vigente entra en la aplicación y la revela allí, con su permiso comprobado, su
    límite de tasa y su registro en la bitácora — que es precisamente el control
    que un correo con el secreto dentro eludiría.

    Se excluye al autor del cambio: ya sabe lo que hizo.
    """
    if not avisos_activos():
        return 0
    destinatarios = [
        u for u in usuarios_con_acceso_a_credencial(db, credencial) if u.id != autor.id
    ]
    if not destinatarios:
        return 0

    etiqueta = ETIQUETAS_ACTIVO.get(credencial.tipo_activo, "activo")
    que_cambio = (
        "Se actualizó la CONTRASEÑA de esta credencial."
        if password_cambiada
        else "Se actualizaron datos de esta credencial (sin cambiar la contraseña)."
    )
    cuerpo = (
        f"Una credencial a la que usted tiene acceso fue modificada.\n\n"
        f"  {que_cambio}\n\n"
        f"  Activo:             {credencial.nombre_activo} ({etiqueta})\n"
        f"  Servicio:           {credencial.servicio}\n"
        f"  Usuario de acceso:  {credencial.usuario_acceso}\n"
        f"  Modificada por:     {autor.username}\n"
        f"  Fecha y hora (UTC): {ahora_utc():%Y-%m-%d %H:%M:%S}\n\n"
        "Si utiliza esta credencial en scripts, tareas programadas o herramientas "
        "propias, actualícela para evitar fallos de autenticación o bloqueos de "
        "cuenta por intentos fallidos.\n\n"
        "Para obtener la contraseña vigente, entre en la aplicación y revélela "
        "desde la ficha del activo. Por seguridad, este aviso no la incluye."
    ) + _PIE
    asunto = (
        f"Contraseña actualizada: {credencial.nombre_activo}"
        if password_cambiada
        else f"Credencial modificada: {credencial.nombre_activo}"
    )
    enviados = enviar_a_usuarios(destinatarios, asunto, cuerpo)
    logger.info(
        "Aviso de credencial %s (activo %s) enviado a %d de %d usuarios con acceso",
        credencial.id, credencial.nombre_activo, enviados, len(destinatarios),
    )
    return enviados


# ---------------------------------------------------------------------------
# 3. Alertas preventivas de caducidad (rotación)
# ---------------------------------------------------------------------------


def dias_para_rotacion(credencial: Credencial) -> int:
    """Días que faltan para el cambio obligatorio (negativo si ya venció)."""
    return get_settings().rotation_max_days - credencial.dias_sin_rotar


def aviso_rotacion_proxima(db: Session, credencial: Credencial) -> int:
    """Avisa a quienes USAN la credencial de que su rotación obligatoria se acerca.

    Se dirige solo a quienes pueden revelar la contraseña
    (``solo_con_revelado=True``): son los que pueden rotarla. El auditor ve el
    activo pero nunca sus secretos, así que un aviso de rotación no le
    corresponde.

    Deduplicado por credencial y umbral con una ventana de 7 días, de modo que una
    tarea programada diaria no repita el mismo aviso cada día. Devuelve el número
    de avisos enviados.
    """
    if not avisos_activos():
        return 0
    settings = get_settings()
    restantes = dias_para_rotacion(credencial)
    if restantes > settings.rotation_warning_days:
        return 0  # todavía no entra en la ventana de preaviso

    umbral = "vencida" if restantes < 0 else "proxima"
    if not _una_vez_por(db, f"aviso-rotacion:{credencial.id}:{umbral}", ventana_minutos=7 * 24 * 60):
        return 0

    destinatarios = usuarios_con_acceso_a_credencial(db, credencial, solo_con_revelado=True)
    if not destinatarios:
        return 0

    etiqueta = ETIQUETAS_ACTIVO.get(credencial.tipo_activo, "activo")
    if restantes < 0:
        titular = (
            f"La rotación obligatoria de esta contraseña VENCIÓ hace {abs(restantes)} día(s)."
        )
        asunto = f"Rotación VENCIDA: {credencial.nombre_activo}"
    else:
        titular = (
            f"La rotación obligatoria de esta contraseña vence en {restantes} día(s)."
        )
        asunto = f"Rotación próxima ({restantes} d): {credencial.nombre_activo}"

    cuerpo = (
        f"{titular}\n\n"
        f"  Activo:             {credencial.nombre_activo} ({etiqueta})\n"
        f"  Servicio:           {credencial.servicio}\n"
        f"  Usuario de acceso:  {credencial.usuario_acceso}\n"
        f"  Última rotación:    {credencial.password_rotada_en:%Y-%m-%d} "
        f"({credencial.dias_sin_rotar} días)\n"
        f"  Política vigente:   cambio cada {settings.rotation_max_days} días\n\n"
        "Actualice la contraseña en el servidor y regístrela en la aplicación para "
        "que el inventario siga reflejando la credencial vigente. Al hacerlo, los "
        "demás usuarios con acceso recibirán aviso del cambio."
    ) + _PIE
    enviados = enviar_a_usuarios(destinatarios, asunto, cuerpo)
    logger.info(
        "Aviso de rotación (%s) de la credencial %s enviado a %d usuarios",
        umbral, credencial.id, enviados,
    )
    return enviados


def revisar_rotaciones(db: Session) -> dict[str, int]:
    """Recorre el inventario y emite los avisos de rotación que correspondan.

    Pensada para una tarea programada diaria (``python -m app.cli avisar-rotacion``).
    La deduplicación de ``aviso_rotacion_proxima`` hace que ejecutarla a diario sea
    seguro: cada credencial genera como máximo un aviso por umbral cada 7 días.
    """
    from sqlalchemy import select

    resumen = {"credenciales_revisadas": 0, "avisos_enviados": 0, "credenciales_avisadas": 0}
    if not avisos_activos():
        return resumen
    credenciales = db.scalars(select(Credencial)).all()
    for credencial in credenciales:
        resumen["credenciales_revisadas"] += 1
        enviados = aviso_rotacion_proxima(db, credencial)
        if enviados:
            resumen["avisos_enviados"] += enviados
            resumen["credenciales_avisadas"] += 1
    return resumen


# ---------------------------------------------------------------------------
# Utilidad compartida por los avisos de concesión (admin → usuario)
# ---------------------------------------------------------------------------


def aviso_concesion(
    db: Session, usuario: Usuario, tipo: str, activo_id: int, *, concedida: bool, nivel: str = ""
) -> None:
    """Avisa a un usuario de que se le concedió o revocó acceso a un activo."""
    if not avisos_activos():
        return
    etiqueta = ETIQUETAS_ACTIVO.get(tipo, "activo")
    nombres = _nombre_de_activo(db, tipo, activo_id)
    if concedida:
        accion = "Acceso CONCEDIDO"
        detalle = f"{etiqueta} «{nombres}»" + (f", nivel: {nivel}" if nivel else "")
    else:
        accion = "Acceso REVOCADO"
        detalle = f"{etiqueta} «{nombres}»"
    aviso_cambio_permisos_propios(db, usuario, accion, detalle)


def _nombre_de_activo(db: Session, tipo: str, activo_id: int) -> str:
    from app.models import DispositivoRed, Hipervisor, MaquinaVirtual, ServidorFisico

    modelo = {
        ACTIVO_FISICO: ServidorFisico,
        ACTIVO_HIPERVISOR: Hipervisor,
        ACTIVO_VM: MaquinaVirtual,
        ACTIVO_DISPOSITIVO: DispositivoRed,
    }.get(tipo)
    if modelo is None:
        return f"#{activo_id}"
    activo = db.get(modelo, activo_id)
    return getattr(activo, "nombre", f"#{activo_id}") if activo is not None else f"#{activo_id}"


def usuarios_con_acceso(db: Session, tipo: str, activo_id: int) -> list[Usuario]:
    """Reexportación de conveniencia (usada por las vistas y las pruebas)."""
    return usuarios_con_acceso_a_activo(db, tipo, activo_id)


# ---------------------------------------------------------------------------
# Restablecimiento administrativo de contraseña
# ---------------------------------------------------------------------------


def enviar_password_temporal(usuario: Usuario, password_temporal: str, admin_username: str) -> bool:
    """Envía la contraseña TEMPORAL al buzón de su titular. True si se entregó.

    Es la segunda excepción deliberada a «los correos no llevan secretos» (la otra
    es el OTP del MFA de respaldo), y se sostiene por tres razones: la credencial
    es de un solo uso —el sistema fuerza cambiarla en el primer acceso—, no da
    acceso a nada por sí sola (el MFA sigue exigiéndose) y viaja al buzón de su
    propio titular. La alternativa que sustituye es peor: que el administrador vea
    la contraseña en pantalla y la reenvíe a mano por chat o correo personal, donde
    queda fuera de toda auditoría y sin caducidad.

    No se envía con ``enviar_a_usuario`` a propósito: ese camino exige
    ``notify_users_enabled``, y el restablecimiento debe funcionar aunque los
    avisos dinámicos estén apagados.
    """
    from app.notifications import enviar_a_direccion

    asunto = "Su contraseña ha sido restablecida"
    cuerpo = (
        f"Un administrador ({admin_username}) restableció la contraseña de su "
        f"cuenta «{usuario.username}».\n\n"
        f"    CONTRASEÑA TEMPORAL:  {password_temporal}\n\n"
        "Al iniciar sesión con ella, el sistema le exigirá definir una contraseña "
        "nueva de inmediato. Su segundo factor (MFA) sigue siendo necesario para "
        "entrar, así que esta contraseña por sí sola no da acceso a la cuenta.\n\n"
        f"  Fecha y hora (UTC): {ahora_utc():%Y-%m-%d %H:%M:%S}\n\n"
        "Todas sus sesiones abiertas se cerraron como parte del restablecimiento.\n\n"
        "Si no esperaba este cambio, avise al administrador de inmediato: podría "
        "indicar un uso indebido de una cuenta administrativa.\n\n"
        "---\n"
        "Aviso automático del Gestor de Contraseñas de Servidores.\n"
        "No comparta esta contraseña con nadie, ni siquiera con personal de soporte."
    )
    return enviar_a_direccion(usuario.email, asunto, cuerpo)


def enmascarar_correo(correo: str) -> str:
    """``ana.perez@ejemplo.com`` → ``a*******z@ejemplo.com``.

    Permite confirmar a qué buzón salió un envío sin exponer la dirección completa
    en respuestas de API ni en pantalla.
    """
    correo = (correo or "").strip()
    if "@" not in correo:
        return "su correo registrado"
    local, dominio = correo.rsplit("@", 1)
    oculto = "*" * len(local) if len(local) <= 2 else f"{local[0]}{'*' * (len(local) - 2)}{local[-1]}"
    return f"{oculto}@{dominio}"
