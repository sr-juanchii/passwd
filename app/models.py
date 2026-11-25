"""Modelo de datos relacional.

Jerarquía del inventario (segmentación lógica solicitada):

    ServidorFisico  → servidor físico dedicado a una sola función (con sus credenciales)
    Hipervisor      → máquina física que ejecuta un hipervisor (Proxmox, ESXi, Hyper-V…)
        └── MaquinaVirtual (cada una con su sistema y función)
    DispositivoRed  → equipo de red (switch, router, firewall, punto de acceso…)

Servidores dedicados, hipervisores y dispositivos de red son tipos de activo de
**nivel superior** independientes: el hipervisor es la propia máquina física
(con su hardware) y contiene directamente sus máquinas virtuales; el
dispositivo de red cubre la electrónica de red de la infraestructura. Cada
nivel (servidor, hipervisor, máquina virtual o dispositivo de red) puede tener
una o varias credenciales (usuario + contraseña cifrada en reposo + descripción
del sistema o servicio al que da acceso). La integridad se garantiza con claves
foráneas y una restricción CHECK que obliga a que cada credencial pertenezca
exactamente a un activo.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def ahora_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Identidad y control de acceso
# ---------------------------------------------------------------------------

ROL_ADMIN = "admin"
ROL_OPERADOR = "operador"
ROL_AUDITOR = "auditor"
ROL_ANALISTA = "analista"
ROLES_VALIDOS = (ROL_ADMIN, ROL_OPERADOR, ROL_AUDITOR, ROL_ANALISTA)


# Método principal del segundo factor de cada usuario.
MFA_TOTP = "totp"      # aplicación autenticadora (RFC 6238)
MFA_CORREO = "correo"  # código de un solo uso enviado al buzón registrado
MFA_METODOS = (MFA_TOTP, MFA_CORREO)


class Usuario(Base):
    """Cuenta de usuario con MFA obligatorio (CIS 5.x / 6.x)."""

    __tablename__ = "usuarios"
    __table_args__ = (
        CheckConstraint(
            "rol IN ('admin', 'operador', 'auditor', 'analista')", name="ck_usuarios_rol"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    nombre_completo: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    rol: Mapped[str] = mapped_column(String(16), nullable=False, default=ROL_OPERADOR)

    # MFA TOTP — el secreto se guarda cifrado en reposo; el último código
    # aceptado se retiene para impedir su reutilización (RFC 6238 §5.2)
    totp_secret_cifrado: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    mfa_habilitado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ultimo_otp_usado: Mapped[str | None] = mapped_column(String(8), nullable=True)
    # Paso temporal (contador RFC 6238) del último TOTP aceptado: un código de
    # un paso igual o anterior se rechaza aunque siga dentro de la ventana.
    ultimo_totp_paso: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Método principal elegido por el usuario al enrolarse.
    mfa_metodo: Mapped[str] = mapped_column(
        String(8), nullable=False, default=MFA_TOTP, server_default=MFA_TOTP
    )

    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    debe_cambiar_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    intentos_fallidos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bloqueado_hasta: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    password_cambiada_en: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=ahora_utc)
    ultimo_acceso: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=ahora_utc)

    sesiones: Mapped[list[SesionWeb]] = relationship(back_populates="usuario", cascade="all, delete-orphan")

    def esta_bloqueado(self) -> bool:
        return self.bloqueado_hasta is not None and self.bloqueado_hasta > ahora_utc()


ETAPA_CAMBIO_PASSWORD = "cambio_password"  # noqa: S105 — nombre de etapa, no es una contraseña
ETAPA_MFA_ENROLAMIENTO = "mfa_enrolamiento"
ETAPA_MFA_PENDIENTE = "mfa_pendiente"
ETAPA_ACTIVA = "activa"
ETAPAS_VALIDAS = (ETAPA_CAMBIO_PASSWORD, ETAPA_MFA_ENROLAMIENTO, ETAPA_MFA_PENDIENTE, ETAPA_ACTIVA)


class SesionWeb(Base):
    """Sesión gestionada en servidor: revocable y con doble expiración.

    Solo se persiste el hash SHA-256 del token; la cookie lleva el valor
    original, de modo que un volcado de la BD no permite secuestrar sesiones.
    """

    __tablename__ = "sesiones_web"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False)
    etapa: Mapped[str] = mapped_column(String(20), nullable=False, default=ETAPA_MFA_PENDIENTE)
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)

    creada_en: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=ahora_utc)
    ultima_actividad: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=ahora_utc)
    expira_en: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revocada_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    direccion_ip: Mapped[str] = mapped_column(String(45), nullable=False, default="")
    agente_usuario: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    usuario: Mapped[Usuario] = relationship(back_populates="sesiones")


# ---------------------------------------------------------------------------
# Inventario relacional
# ---------------------------------------------------------------------------

# Estado del ciclo de vida de un activo (validado en la aplicación).
ESTADO_ACTIVO = "activo"
ESTADO_MANTENIMIENTO = "mantenimiento"
ESTADO_RETIRADO = "retirado"
ESTADOS_ACTIVO = (ESTADO_ACTIVO, ESTADO_MANTENIMIENTO, ESTADO_RETIRADO)
ETIQUETAS_ESTADO = {
    ESTADO_ACTIVO: "Activo",
    ESTADO_MANTENIMIENTO: "En mantenimiento",
    ESTADO_RETIRADO: "Retirado",
}


def normalizar_etiquetas(texto: str) -> str:
    """Normaliza una lista de etiquetas separadas por coma (minúsculas, sin duplicados)."""
    vistas: list[str] = []
    for parte in texto.split(","):
        etiqueta = parte.strip().lower()
        if etiqueta and etiqueta not in vistas:
            vistas.append(etiqueta)
    return ", ".join(vistas)


class ServidorFisico(Base):
    """Servidor físico dedicado a una sola función (con sus credenciales)."""

    __tablename__ = "servidores_fisicos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sistema_operativo: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    marca_modelo: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    ubicacion: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    ip_gestion: Mapped[str] = mapped_column(String(45), nullable=False, default="")
    # Inventario ampliado (Fase 2): hardware, ciclo de vida y etiquetas.
    ram: Mapped[str] = mapped_column(String(60), nullable=False, default="", server_default="")
    cpu: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    almacenamiento: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    numero_serie: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    garantia_hasta: Mapped[str] = mapped_column(String(40), nullable=False, default="", server_default="")
    proveedor: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default=ESTADO_ACTIVO, server_default=ESTADO_ACTIVO)
    etiquetas: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    # Restringido a administradores: los OPERADORES lo tratan como inexistente
    # (404); el auditor sí lo ve (supervisión, nunca revela contraseñas) y el
    # analista solo con concesión explícita. Cambiar la marca exige el permiso
    # `inventario.restringir` (solo administradores).
    restringido: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("0"))
    # Notas sensibles cifradas en reposo (instrucciones de acceso, tokens, etc.)
    notas_cifradas: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=ahora_utc)
    actualizado_en: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=ahora_utc, onupdate=ahora_utc)

    credenciales: Mapped[list[Credencial]] = relationship(
        back_populates="servidor_fisico", cascade="all, delete-orphan"
    )

    @property
    def lista_etiquetas(self) -> list[str]:
        return [e for e in (self.etiquetas or "").split(", ") if e]


class Hipervisor(Base):
    """Máquina física que ejecuta un hipervisor y aloja máquinas virtuales.

    Es un activo de nivel superior con su propio hardware (no se anida bajo un
    servidor físico). Contiene directamente sus máquinas virtuales.
    """

    __tablename__ = "hipervisores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    plataforma: Mapped[str] = mapped_column(String(60), nullable=False, default="")  # Proxmox, ESXi, Hyper-V…
    version: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    ip_gestion: Mapped[str] = mapped_column(String(45), nullable=False, default="")
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Hardware de la máquina física (el hipervisor ES el servidor físico).
    marca_modelo: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    ubicacion: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    ram: Mapped[str] = mapped_column(String(60), nullable=False, default="", server_default="")
    cpu: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    almacenamiento: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    numero_serie: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    garantia_hasta: Mapped[str] = mapped_column(String(40), nullable=False, default="", server_default="")
    proveedor: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default=ESTADO_ACTIVO, server_default=ESTADO_ACTIVO)
    etiquetas: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    # Restringido a administradores; sus VMs heredan la restricción (deny hereda,
    # a diferencia de las concesiones, que nunca heredan).
    restringido: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("0"))
    notas_cifradas: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=ahora_utc)
    actualizado_en: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=ahora_utc, onupdate=ahora_utc)

    maquinas_virtuales: Mapped[list[MaquinaVirtual]] = relationship(
        back_populates="hipervisor", cascade="all, delete-orphan", order_by="MaquinaVirtual.nombre"
    )
    credenciales: Mapped[list[Credencial]] = relationship(back_populates="hipervisor", cascade="all, delete-orphan")

    @property
    def lista_etiquetas(self) -> list[str]:
        return [e for e in (self.etiquetas or "").split(", ") if e]


class MaquinaVirtual(Base):
    """Máquina virtual alojada dentro de un hipervisor."""

    __tablename__ = "maquinas_virtuales"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hipervisor_id: Mapped[int] = mapped_column(
        ForeignKey("hipervisores.id", ondelete="CASCADE"), nullable=False, index=True
    )
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    sistema_operativo: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    ip: Mapped[str] = mapped_column(String(45), nullable=False, default="")
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Recursos asignados a la VM (texto libre para admitir unidades: "8 GB",
    # "4 vCPU", "120 GB SSD"), coherente con el hardware de servidor/hipervisor.
    ram: Mapped[str] = mapped_column(String(60), nullable=False, default="", server_default="")
    cpu: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    almacenamiento: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default=ESTADO_ACTIVO, server_default=ESTADO_ACTIVO)
    etiquetas: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    notas_cifradas: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=ahora_utc)
    actualizado_en: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=ahora_utc, onupdate=ahora_utc)

    hipervisor: Mapped[Hipervisor] = relationship(back_populates="maquinas_virtuales")
    credenciales: Mapped[list[Credencial]] = relationship(
        back_populates="maquina_virtual", cascade="all, delete-orphan"
    )

    @property
    def lista_etiquetas(self) -> list[str]:
        return [e for e in (self.etiquetas or "").split(", ") if e]


# Clase (rol funcional) de un dispositivo de red, validada en la aplicación
# y con CHECK en la base de datos. «otro» admite equipos no catalogados
# (módems, consolas de gestión OOB, SAN switches…) sin ampliar el esquema.
TIPO_DISPOSITIVO_SWITCH = "switch"
TIPO_DISPOSITIVO_ROUTER = "router"
TIPO_DISPOSITIVO_FIREWALL = "firewall"
TIPO_DISPOSITIVO_AP = "access_point"
TIPO_DISPOSITIVO_BALANCEADOR = "balanceador"
TIPO_DISPOSITIVO_OTRO = "otro"
TIPOS_DISPOSITIVO = (
    TIPO_DISPOSITIVO_SWITCH,
    TIPO_DISPOSITIVO_ROUTER,
    TIPO_DISPOSITIVO_FIREWALL,
    TIPO_DISPOSITIVO_AP,
    TIPO_DISPOSITIVO_BALANCEADOR,
    TIPO_DISPOSITIVO_OTRO,
)
ETIQUETAS_TIPO_DISPOSITIVO = {
    TIPO_DISPOSITIVO_SWITCH: "Switch",
    TIPO_DISPOSITIVO_ROUTER: "Router",
    TIPO_DISPOSITIVO_FIREWALL: "Firewall",
    TIPO_DISPOSITIVO_AP: "Punto de acceso",
    TIPO_DISPOSITIVO_BALANCEADOR: "Balanceador",
    TIPO_DISPOSITIVO_OTRO: "Otro",
}


class DispositivoRed(Base):
    """Dispositivo de red de la infraestructura (switch, router, firewall…).

    Activo de nivel superior independiente, al mismo nivel que los servidores
    dedicados y los hipervisores: así el inventario cubre TODA la
    infraestructura (cómputo y electrónica de red) y cada equipo custodia sus
    credenciales de gestión (SSH, consola, panel web…) con los mismos
    controles: cifrado en reposo, RBAC, acceso por objeto y auditoría.
    """

    __tablename__ = "dispositivos_red"
    __table_args__ = (
        CheckConstraint(
            "tipo_dispositivo IN ('switch', 'router', 'firewall', "
            "'access_point', 'balanceador', 'otro')",
            name="ck_dispositivos_red_tipo",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    tipo_dispositivo: Mapped[str] = mapped_column(
        String(20), nullable=False, default=TIPO_DISPOSITIVO_SWITCH,
        server_default=TIPO_DISPOSITIVO_SWITCH,
    )
    marca_modelo: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    # Versión de firmware/sistema del equipo (IOS, RouterOS, FortiOS…).
    version: Mapped[str] = mapped_column(String(60), nullable=False, default="", server_default="")
    ip_gestion: Mapped[str] = mapped_column(String(45), nullable=False, default="")
    ubicacion: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    # Texto libre para admitir configuraciones mixtas: "48x 1GbE + 4x SFP+".
    puertos: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    numero_serie: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    garantia_hasta: Mapped[str] = mapped_column(String(40), nullable=False, default="", server_default="")
    proveedor: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default=ESTADO_ACTIVO, server_default=ESTADO_ACTIVO)
    etiquetas: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    # Restringido a administradores (ver ServidorFisico.restringido).
    restringido: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("0"))
    notas_cifradas: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=ahora_utc)
    actualizado_en: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=ahora_utc, onupdate=ahora_utc)

    credenciales: Mapped[list[Credencial]] = relationship(
        back_populates="dispositivo_red", cascade="all, delete-orphan"
    )

    @property
    def lista_etiquetas(self) -> list[str]:
        return [e for e in (self.etiquetas or "").split(", ") if e]

    @property
    def tipo_dispositivo_label(self) -> str:
        return ETIQUETAS_TIPO_DISPOSITIVO.get(self.tipo_dispositivo, self.tipo_dispositivo)


ACTIVO_FISICO = "fisico"
ACTIVO_HIPERVISOR = "hipervisor"
ACTIVO_VM = "vm"
ACTIVO_DISPOSITIVO = "dispositivo"


# Vía por la que se rota la contraseña de una credencial.
VIA_ROTACION_MANUAL = "manual"        # la cambia una persona en el activo
VIA_ROTACION_AGENTE = "agente"        # la aplica un agente instalado (v1.4.0+)
VIA_ROTACION_CONECTOR = "conector"    # la aplica el backend por SSH/SNMP (v2.3.0)
VIAS_ROTACION = (VIA_ROTACION_MANUAL, VIA_ROTACION_AGENTE, VIA_ROTACION_CONECTOR)


class Credencial(Base):
    """Credencial de acceso a un activo del inventario.

    La contraseña se cifra en reposo (Fernet/AES) antes de persistirse.
    Exactamente una de las cuatro claves foráneas debe estar presente.
    """

    __tablename__ = "credenciales"
    __table_args__ = (
        CheckConstraint(
            "(CASE WHEN servidor_fisico_id IS NULL THEN 0 ELSE 1 END"
            " + CASE WHEN hipervisor_id IS NULL THEN 0 ELSE 1 END"
            " + CASE WHEN maquina_virtual_id IS NULL THEN 0 ELSE 1 END"
            " + CASE WHEN dispositivo_red_id IS NULL THEN 0 ELSE 1 END) = 1",
            name="ck_credenciales_un_activo",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    servidor_fisico_id: Mapped[int | None] = mapped_column(
        ForeignKey("servidores_fisicos.id", ondelete="CASCADE"), nullable=True, index=True
    )
    hipervisor_id: Mapped[int | None] = mapped_column(
        ForeignKey("hipervisores.id", ondelete="CASCADE"), nullable=True, index=True
    )
    maquina_virtual_id: Mapped[int | None] = mapped_column(
        ForeignKey("maquinas_virtuales.id", ondelete="CASCADE"), nullable=True, index=True
    )
    dispositivo_red_id: Mapped[int | None] = mapped_column(
        ForeignKey("dispositivos_red.id", ondelete="CASCADE"), nullable=True, index=True
    )

    usuario_acceso: Mapped[str] = mapped_column(String(120), nullable=False)
    password_cifrada: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    servicio: Mapped[str] = mapped_column(String(60), nullable=False, default="SSH")  # SSH, RDP, iLO/IPMI, Web…
    puerto: Mapped[int | None] = mapped_column(Integer, nullable=True)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")

    creado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=ahora_utc)
    actualizado_en: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=ahora_utc, onupdate=ahora_utc)
    # Fecha de la última rotación de la contraseña (alertas de antigüedad)
    password_rotada_en: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=ahora_utc)
    # Vía por la que se rota esta credencial. Hasta que existan agentes y
    # conectores, todas son "manual". Sin CHECK a propósito: añadir una
    # restricción a una tabla existente no es un cambio aditivo y el
    # reconciliador de esquema no lo haría; la validación vive en el servicio.
    via_rotacion: Mapped[str] = mapped_column(
        String(20), nullable=False, default=VIA_ROTACION_MANUAL, server_default=VIA_ROTACION_MANUAL
    )
    # Servicios y automatismos que consumen esta cuenta (cron, tareas
    # programadas, respaldos, Ansible, monitorización). Se muestra al solicitar
    # y al autorizar una rotación: es el fallo operativo más probable.
    # String y no Text a propósito: MySQL no admite DEFAULT en columnas TEXT, y
    # esta columna se añade por ALTER TABLE a bases existentes, donde el
    # server_default es lo que permite crearla NOT NULL sobre filas que ya hay.
    usada_por: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")

    servidor_fisico: Mapped[ServidorFisico | None] = relationship(back_populates="credenciales")
    hipervisor: Mapped[Hipervisor | None] = relationship(back_populates="credenciales")
    maquina_virtual: Mapped[MaquinaVirtual | None] = relationship(back_populates="credenciales")
    dispositivo_red: Mapped[DispositivoRed | None] = relationship(back_populates="credenciales")
    creado_por: Mapped[Usuario | None] = relationship()

    @property
    def tipo_activo(self) -> str:
        if self.servidor_fisico_id is not None:
            return ACTIVO_FISICO
        if self.hipervisor_id is not None:
            return ACTIVO_HIPERVISOR
        if self.dispositivo_red_id is not None:
            return ACTIVO_DISPOSITIVO
        return ACTIVO_VM

    @property
    def nombre_activo(self) -> str:
        if self.servidor_fisico is not None:
            return self.servidor_fisico.nombre
        if self.hipervisor is not None:
            return self.hipervisor.nombre
        if self.maquina_virtual is not None:
            return self.maquina_virtual.nombre
        if self.dispositivo_red is not None:
            return self.dispositivo_red.nombre
        return "—"

    @property
    def dias_sin_rotar(self) -> int:
        return max((ahora_utc() - self.password_rotada_en).days, 0)

    historial: Mapped[list[HistorialCredencial]] = relationship(
        back_populates="credencial", cascade="all, delete-orphan",
        order_by="HistorialCredencial.rotada_en.desc()",
    )


class HistorialCredencial(Base):
    """Contraseña anterior de una credencial, conservada cifrada al rotar.

    Permite recuperar una clave ante un error de rotación y auditar el número
    de rotaciones. Se conservan las últimas N (configurable). Nunca en claro.
    """

    __tablename__ = "historial_credenciales"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    credencial_id: Mapped[int] = mapped_column(
        ForeignKey("credenciales.id", ondelete="CASCADE"), nullable=False, index=True
    )
    password_cifrada: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    rotada_en: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=ahora_utc)
    rotada_por_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True
    )

    credencial: Mapped[Credencial] = relationship(back_populates="historial")
    rotada_por: Mapped[Usuario | None] = relationship()


# Niveles de una concesión de acceso por activo (control de acceso por objeto)
NIVEL_VER = "ver"                      # ve el activo y la lista de credenciales (sin contraseñas)
NIVEL_VER_CREDENCIALES = "ver_credenciales"  # además puede revelar/copiar las contraseñas
NIVELES_CONCESION = (NIVEL_VER, NIVEL_VER_CREDENCIALES)


class ConcesionAcceso(Base):
    """Acceso concedido a un usuario (analista) sobre un activo concreto.

    Implementa el control de acceso *por objeto* (least privilege): un analista
    solo ve y usa los activos que un administrador le concede explícitamente.
    Apunta exactamente a un activo (mismo patrón e integridad que ``Credencial``)
    y nunca contiene secretos: solo decide quién puede pedir su descifrado.
    """

    __tablename__ = "concesiones_acceso"
    __table_args__ = (
        CheckConstraint(
            "(CASE WHEN servidor_fisico_id IS NULL THEN 0 ELSE 1 END"
            " + CASE WHEN hipervisor_id IS NULL THEN 0 ELSE 1 END"
            " + CASE WHEN maquina_virtual_id IS NULL THEN 0 ELSE 1 END"
            " + CASE WHEN dispositivo_red_id IS NULL THEN 0 ELSE 1 END) = 1",
            name="ck_concesiones_un_activo",
        ),
        CheckConstraint(
            "nivel IN ('ver', 'ver_credenciales')", name="ck_concesiones_nivel"
        ),
        UniqueConstraint(
            "usuario_id",
            "servidor_fisico_id",
            "hipervisor_id",
            "maquina_virtual_id",
            "dispositivo_red_id",
            name="uq_concesion_usuario_activo",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    usuario_id: Mapped[int] = mapped_column(
        ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True
    )
    servidor_fisico_id: Mapped[int | None] = mapped_column(
        ForeignKey("servidores_fisicos.id", ondelete="CASCADE"), nullable=True, index=True
    )
    hipervisor_id: Mapped[int | None] = mapped_column(
        ForeignKey("hipervisores.id", ondelete="CASCADE"), nullable=True, index=True
    )
    maquina_virtual_id: Mapped[int | None] = mapped_column(
        ForeignKey("maquinas_virtuales.id", ondelete="CASCADE"), nullable=True, index=True
    )
    dispositivo_red_id: Mapped[int | None] = mapped_column(
        ForeignKey("dispositivos_red.id", ondelete="CASCADE"), nullable=True, index=True
    )

    nivel: Mapped[str] = mapped_column(String(20), nullable=False, default=NIVEL_VER)
    concedido_por_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True
    )
    creado_en: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=ahora_utc)
    # Caducidad opcional. La revocación es un borrado de la fila: la traza
    # histórica (quién concedió/revocó y cuándo) vive en la bitácora de
    # auditoría, y así la restricción UNIQUE solo limita las concesiones vivas.
    expira_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    usuario: Mapped[Usuario] = relationship(foreign_keys=[usuario_id])
    concedido_por: Mapped[Usuario | None] = relationship(foreign_keys=[concedido_por_id])
    servidor_fisico: Mapped[ServidorFisico | None] = relationship()
    hipervisor: Mapped[Hipervisor | None] = relationship()
    maquina_virtual: Mapped[MaquinaVirtual | None] = relationship()
    dispositivo_red: Mapped[DispositivoRed | None] = relationship()

    def esta_vigente(self) -> bool:
        return self.expira_en is None or self.expira_en > ahora_utc()

    @property
    def expirada(self) -> bool:
        return self.expira_en is not None and self.expira_en <= ahora_utc()

    @property
    def tipo_activo(self) -> str:
        if self.servidor_fisico_id is not None:
            return ACTIVO_FISICO
        if self.hipervisor_id is not None:
            return ACTIVO_HIPERVISOR
        if self.dispositivo_red_id is not None:
            return ACTIVO_DISPOSITIVO
        return ACTIVO_VM

    @property
    def nombre_activo(self) -> str:
        if self.servidor_fisico is not None:
            return self.servidor_fisico.nombre
        if self.hipervisor is not None:
            return self.hipervisor.nombre
        if self.maquina_virtual is not None:
            return self.maquina_virtual.nombre
        if self.dispositivo_red is not None:
            return self.dispositivo_red.nombre
        return "—"


class CodigoRecuperacionMFA(Base):
    """Código de recuperación de un solo uso para acceso sin dispositivo TOTP.

    Solo se persiste el hash SHA-256; el valor en claro se muestra una única
    vez al usuario durante el enrolamiento del MFA.
    """

    __tablename__ = "codigos_recuperacion_mfa"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    usuario_id: Mapped[int] = mapped_column(
        ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True
    )
    codigo_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    creado_en: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=ahora_utc)
    usado_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    usuario: Mapped[Usuario] = relationship()


class CodigoOtpCorreo(Base):
    """Código OTP de un solo uso enviado al correo, como MFA de respaldo.

    Permite completar el segundo factor cuando el usuario no tiene acceso a su
    aplicación autenticadora. Solo se persiste el hash SHA-256 del código; el
    valor en claro existe únicamente en el correo enviado a su titular.

    Ciclo de vida: se emite desde la etapa ``mfa_pendiente`` (es decir, DESPUÉS de
    validar la contraseña), caduca a los ``PASSWD_EMAIL_OTP_TTL_MINUTES`` minutos,
    se invalida al consumirse (``usado_en``) y también al superar ``MAX_INTENTOS``
    verificaciones fallidas. Emitir un código nuevo invalida los anteriores del
    mismo usuario, de modo que solo hay un código vivo por cuenta.
    """

    __tablename__ = "codigos_otp_correo"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    usuario_id: Mapped[int] = mapped_column(
        ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True
    )
    codigo_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    creado_en: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=ahora_utc)
    expira_en: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    intentos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    usado_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    invalidado_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Contexto de la solicitud, para la bitácora y el propio correo de aviso.
    direccion_ip: Mapped[str] = mapped_column(String(45), nullable=False, default="")

    usuario: Mapped[Usuario] = relationship()

    @property
    def vigente(self) -> bool:
        return (
            self.usado_en is None
            and self.invalidado_en is None
            and self.expira_en > ahora_utc()
        )


class RecuperacionPassword(Base):
    """Desafío de auto-recuperación de contraseña (server-side, efímero).

    Vida del desafío: se crea al superar la identificación (usuario + email),
    se marca ``verificado_en`` al validar el segundo factor (TOTP o código de
    recuperación) y ``consumido_en`` al cambiar la contraseña o al invalidarse
    (caducidad, exceso de intentos o un desafío nuevo). Solo se persiste el
    hash SHA-256 del token; la cookie efímera lleva el valor en claro, de modo
    que un volcado de la BD no permite retomar un desafío. El ``csrf_token``
    protege los pasos de verificación y cambio (doble envío por cabecera).
    """

    __tablename__ = "recuperaciones_password"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Nullable: los desafíos «señuelo» (identidad no coincidente) no tienen usuario.
    # Existen solo para que el paso de verificación responda igual exista o no la
    # cuenta (anti-enumeración), comportándose siempre como un 2.º factor fallido.
    usuario_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=True, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)

    creado_en: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=ahora_utc)
    expira_en: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    intentos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    verificado_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    consumido_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    usuario: Mapped[Usuario | None] = relationship()

    @property
    def vigente(self) -> bool:
        """Ni consumido ni caducado (aún utilizable)."""
        return self.consumido_en is None and self.expira_en > ahora_utc()

    @property
    def verificado(self) -> bool:
        return self.verificado_en is not None


TOKEN_ALCANCE_TODO = "todo"  # noqa: S105 — nombre de alcance, no es un secreto
TOKEN_ALCANCE_AUDITORIA = "auditoria"  # noqa: S105 — nombre de alcance, no es un secreto
TOKEN_ALCANCE_INVENTARIO = "inventario"  # noqa: S105 — nombre de alcance, no es un secreto
TOKEN_ALCANCES = (TOKEN_ALCANCE_TODO, TOKEN_ALCANCE_AUDITORIA, TOKEN_ALCANCE_INVENTARIO)
ETIQUETAS_TOKEN_ALCANCE = {
    TOKEN_ALCANCE_TODO: "Auditoría e inventario",
    TOKEN_ALCANCE_AUDITORIA: "Solo auditoría",
    TOKEN_ALCANCE_INVENTARIO: "Solo inventario",
}


class TokenApi(Base):
    """Token de API de solo lectura (para SIEM/automatización).

    Solo se persiste el hash SHA-256; el valor se muestra una única vez al
    crearlo. El alcance es de lectura: aun filtrado, no permite modificar nada.
    Admite **caducidad** (``expira_en``) y **alcance** (``alcance``) para aplicar
    mínimo privilegio: un token puede limitarse a auditoría o a inventario.
    """

    __tablename__ = "tokens_api"
    __table_args__ = (
        CheckConstraint(
            "alcance IN ('todo', 'auditoria', 'inventario')", name="ck_tokens_alcance"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    alcance: Mapped[str] = mapped_column(
        String(40), nullable=False, default=TOKEN_ALCANCE_TODO, server_default=TOKEN_ALCANCE_TODO
    )
    creado_por_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True
    )
    creado_en: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=ahora_utc)
    expira_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ultimo_uso: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    creado_por: Mapped[Usuario | None] = relationship()

    def esta_vigente(self) -> bool:
        return self.activo and (self.expira_en is None or self.expira_en > ahora_utc())

    @property
    def caducado(self) -> bool:
        return self.expira_en is not None and self.expira_en <= ahora_utc()


CATEGORIA_VAULT_SERVICIO = "servicio"
CATEGORIA_VAULT_APLICACION = "aplicacion"
CATEGORIA_VAULT_CUENTA = "cuenta"
CATEGORIA_VAULT_OTRO = "otro"
CATEGORIAS_VAULT = (
    CATEGORIA_VAULT_SERVICIO,
    CATEGORIA_VAULT_APLICACION,
    CATEGORIA_VAULT_CUENTA,
    CATEGORIA_VAULT_OTRO,
)
ETIQUETAS_CATEGORIA_VAULT = {
    CATEGORIA_VAULT_SERVICIO: "Servicio",
    CATEGORIA_VAULT_APLICACION: "Aplicación",
    CATEGORIA_VAULT_CUENTA: "Cuenta propia",
    CATEGORIA_VAULT_OTRO: "Otro",
}


class EntradaVault(Base):
    """Entrada del vault PERSONAL de un usuario (privado, no del inventario).

    A diferencia de ``Credencial`` (credenciales de la infraestructura, sujetas
    a RBAC y acceso por objeto), una entrada de vault pertenece a UN usuario y
    solo él la ve, la edita y la revela: ni el administrador accede a su
    contenido. Sirve para contraseñas de servicios, aplicaciones o cuentas
    propias, dando versatilidad más allá de los servidores. La contraseña se
    cifra en reposo (Fernet/AES) igual que el resto de secretos del sistema; se
    incluye en los respaldos cifrados, pero nunca en el export en claro.
    """

    __tablename__ = "entradas_vault"
    __table_args__ = (
        CheckConstraint(
            "categoria IN ('servicio', 'aplicacion', 'cuenta', 'otro')",
            name="ck_entradas_vault_categoria",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    usuario_id: Mapped[int] = mapped_column(
        ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True
    )
    titulo: Mapped[str] = mapped_column(String(120), nullable=False)
    usuario_acceso: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    password_cifrada: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    url: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    categoria: Mapped[str] = mapped_column(
        String(20), nullable=False, default=CATEGORIA_VAULT_CUENTA, server_default=CATEGORIA_VAULT_CUENTA
    )
    # Sin server_default: MySQL prohíbe DEFAULT en columnas TEXT/BLOB (error 1101).
    # La tabla se crea completa vía create_all, por lo que no la reconcilia schema_sync
    # (que sí requeriría server_default para ALTER ADD COLUMN). El default Python basta.
    notas: Mapped[str] = mapped_column(Text, nullable=False, default="")

    creado_en: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=ahora_utc)
    actualizado_en: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=ahora_utc, onupdate=ahora_utc)
    password_rotada_en: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=ahora_utc)

    usuario: Mapped[Usuario] = relationship()

    @property
    def dias_sin_rotar(self) -> int:
        return max((ahora_utc() - self.password_rotada_en).days, 0)


class Configuracion(Base):
    """Ajuste de operación editable en tiempo de ejecución (capa de *overrides*).

    Almacena, por clave, el valor que **anula** el valor base (por defecto o de
    variable de entorno) definido en ``app/config.py``. Solo cubre una lista
    blanca curada de parámetros operativos (sesión, política de cuentas, límites
    de tasa, rotación/auditoría, correo/SMTP); las claves criptográficas, la URL
    de la base de datos y el arranque **nunca** se guardan aquí, se definen solo
    por entorno. Los valores marcados ``es_secreto`` (p. ej. la contraseña SMTP)
    se guardan **cifrados** (Fernet) y jamás se devuelven en claro a la interfaz.
    """

    __tablename__ = "configuracion"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    clave: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    valor: Mapped[str] = mapped_column(Text, nullable=False, default="")
    es_secreto: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("0"))
    actualizado_en: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=ahora_utc, onupdate=ahora_utc)
    actualizado_por_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True
    )

    actualizado_por: Mapped[Usuario | None] = relationship()


class EventoTasa(Base):
    """Marca temporal de un intento, para el limitador de tasa con backend en BD.

    Solo se usa cuando ``PASSWD_RATE_LIMIT_BACKEND=bd`` (despliegues con varias
    instancias). No contiene datos sensibles: una clave (p. ej. ``login:<ip>``)
    y el momento del intento.
    """

    __tablename__ = "eventos_tasa"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    clave: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    momento: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=ahora_utc, index=True)


# ---------------------------------------------------------------------------
# Auditoría (CIS 8.x — gestión de registros de auditoría)
# ---------------------------------------------------------------------------


class RegistroAuditoria(Base):
    """Bitácora de eventos de seguridad y acceso a credenciales.

    Encadenada por hash (``hash_anterior`` → ``hash_registro``) para dar
    evidencia de manipulación: alterar o borrar una fila rompe la cadena, lo
    que el comando ``python -m app.cli verificar-auditoria`` detecta.
    """

    __tablename__ = "registros_auditoria"
    __table_args__ = (
        # Consultas de métricas y del SIEM filtran por acción y rango de fechas.
        Index("ix_auditoria_accion_fecha", "accion", "fecha"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fecha: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=ahora_utc, index=True)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, default="", index=True)
    accion: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    objeto_tipo: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    objeto_id: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    detalle: Mapped[str] = mapped_column(Text, nullable=False, default="")
    direccion_ip: Mapped[str] = mapped_column(String(45), nullable=False, default="")
    agente_usuario: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    exito: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Encadenamiento por hash (evidencia de manipulación). Nullable/"" por
    # compatibilidad con filas anteriores a la Fase 7; las nuevas siempre lo fijan.
    hash_anterior: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    hash_registro: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="", index=True)
    # Algoritmo del encadenamiento. Vacío = tramo HEREDADO (SHA-256 sin clave,
    # anterior a la 1.3.0, recalculable por quien escriba en la base de datos);
    # "hmac-sha256" = tramo firmado con la clave de bitácora. ``verificar-auditoria``
    # valida ambos tramos y señala el punto de corte.
    hash_algoritmo: Mapped[str] = mapped_column(String(16), nullable=False, default="", server_default="")


# ---------------------------------------------------------------------------
# Gobernanza de rotación de credenciales (v1.3.0)
# ---------------------------------------------------------------------------

# Estados del ciclo de gobernanza. El camino normal es
# SOLICITADA → AUTORIZADA → DESPACHADA → CERRADA; las salidas laterales son
# RECHAZADA, CANCELADA y EXPIRADA.
ROT_SOLICITADA = "solicitada"
ROT_AUTORIZADA = "autorizada"
ROT_DESPACHADA = "despachada"
ROT_CERRADA = "cerrada"
ROT_RECHAZADA = "rechazada"
ROT_CANCELADA = "cancelada"
ROT_EXPIRADA = "expirada"
ESTADOS_ROTACION = (
    ROT_SOLICITADA, ROT_AUTORIZADA, ROT_DESPACHADA,
    ROT_CERRADA, ROT_RECHAZADA, ROT_CANCELADA, ROT_EXPIRADA,
)
# Estados en los que la solicitud sigue viva (ocupa el turno de la credencial).
ESTADOS_ROTACION_ABIERTOS = (ROT_SOLICITADA, ROT_AUTORIZADA, ROT_DESPACHADA)

# Tipo de rotación: explica POR QUÉ se pidió y rige qué exige el ciclo.
ROT_TIPO_PROGRAMADA = "programada"   # la creó el planificador al vencer la política
ROT_TIPO_MANUAL = "manual"           # la pidió una persona
ROT_TIPO_EMERGENCIA = "emergencia"   # incidente: prioridad, con su propia vía (§2.3.1)
ROT_TIPO_MASIVA = "masiva"           # parte de una solicitud por lote
TIPOS_ROTACION = (ROT_TIPO_PROGRAMADA, ROT_TIPO_MANUAL, ROT_TIPO_EMERGENCIA, ROT_TIPO_MASIVA)

# Resultado final de una rotación cerrada.
ROT_RES_APLICADA = "aplicada"
ROT_RES_REVERTIDA = "revertida"
ROT_RES_FALLADA = "fallada"
ROT_RES_MANUAL = "manual"            # la aplicó una persona en el activo
ROT_RES_CANCELADA = "cancelada"
RESULTADOS_ROTACION = (
    ROT_RES_APLICADA, ROT_RES_REVERTIDA, ROT_RES_FALLADA,
    ROT_RES_MANUAL, ROT_RES_CANCELADA,
)

# Alcance de la comprobación posterior a la rotación. Un agente verifica
# LOCALMENTE (PAM / LogonUser): eso demuestra que la contraseña autentica la
# cuenta en el sistema operativo, no que la credencial siga sirviendo para el
# `servicio` y el `puerto` declarados. La verificación REMOTA llega en la 2.2.0.
ROT_VERIF_NINGUNA = "ninguna"
ROT_VERIF_LOCAL = "local"
ROT_VERIF_REMOTA = "remota"
VERIFICACIONES_ROTACION = (ROT_VERIF_NINGUNA, ROT_VERIF_LOCAL, ROT_VERIF_REMOTA)


class RotacionCredencial(Base):
    """Libro mayor **permanente** de rotaciones de credenciales.

    Registra el ciclo completo de gobernanza de cada rotación: quién la pidió y
    por qué, quién la autorizó y con qué reautenticación, cuándo se ejecutó y
    con cuánta desviación respecto a la fecha de política. Es la evidencia que
    responde «a los dos días o a los noventa exactos» y la base de la detección
    de patrones.

    **Nunca se purga.** La purga de trabajos y la retención de la bitácora no lo
    tocan, y el respaldo cifrado lo incluye entero. Por eso los datos del activo
    se desnormalizan (``activo_nombre``, ``usuario_acceso``): si la credencial se
    elimina, el asiento debe seguir siendo legible.
    """

    __tablename__ = "rotaciones_credencial"
    __table_args__ = (
        CheckConstraint(
            "estado IN ('solicitada', 'autorizada', 'despachada', 'cerrada',"
            " 'rechazada', 'cancelada', 'expirada')",
            name="ck_rotaciones_estado",
        ),
        CheckConstraint(
            "tipo IN ('programada', 'manual', 'emergencia', 'masiva')",
            name="ck_rotaciones_tipo",
        ),
        CheckConstraint(
            "verificacion IN ('ninguna', 'local', 'remota')",
            name="ck_rotaciones_verificacion",
        ),
        # Línea de tiempo por credencial y panel de pendientes.
        Index("ix_rotaciones_credencial_fecha", "credencial_id", "solicitado_en"),
        Index("ix_rotaciones_estado_fecha", "estado", "solicitado_en"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # La credencial puede desaparecer; el asiento no. De ahí SET NULL y la copia
    # desnormalizada de lo que identifica a la credencial.
    credencial_id: Mapped[int | None] = mapped_column(
        ForeignKey("credenciales.id", ondelete="SET NULL"), nullable=True, index=True
    )
    activo_nombre: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    usuario_acceso: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    servicio: Mapped[str] = mapped_column(String(60), nullable=False, default="")

    estado: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ROT_SOLICITADA, server_default=ROT_SOLICITADA, index=True
    )
    tipo: Mapped[str] = mapped_column(String(20), nullable=False, default=ROT_TIPO_MANUAL)

    # --- Solicitud -----------------------------------------------------------
    solicitado_por_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True
    )
    solicitado_por_username: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    solicitado_en: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=ahora_utc, index=True)
    motivo: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Antigüedad de la contraseña en el momento de pedir y de autorizar: el dato
    # que permite ver una rotación temprana sin recalcular nada después.
    dias_al_solicitar: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dias_al_autorizar: Mapped[int | None] = mapped_column(Integer, nullable=True)
    temprana: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("0"))

    # --- Autorización --------------------------------------------------------
    autorizado_por_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True
    )
    autorizado_por_username: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    autorizado_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reautenticado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("0"))
    # Vía de emergencia con un solo administrador (§2.3.1 del plan de rotación):
    # marca imborrable que obliga a una revisión posterior por otro admin.
    emergencia_sin_segundo_par: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    revisada_por_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True
    )
    revisada_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    nota_revision: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # --- Rechazo y cancelación ----------------------------------------------
    rechazado_por_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True
    )
    rechazado_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    motivo_rechazo: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cancelado_por_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True
    )
    cancelado_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # --- Ejecución y cierre --------------------------------------------------
    fecha_programada: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ejecutado_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    confirmado_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Antigüedad real de la contraseña en el instante de rotarla, y desviación
    # respecto a la fecha que marcaba la política (negativa = se rotó antes).
    dias_al_rotar: Mapped[int | None] = mapped_column(Integer, nullable=True)
    desvio_dias: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resultado: Mapped[str] = mapped_column(String(20), nullable=False, default="", server_default="")
    via: Mapped[str] = mapped_column(
        String(20), nullable=False, default=VIA_ROTACION_MANUAL, server_default=VIA_ROTACION_MANUAL
    )
    verificacion: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ROT_VERIF_NINGUNA, server_default=ROT_VERIF_NINGUNA
    )
    detalle_error: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # --- Ejecución por agente (v1.4.0) ---------------------------------------
    # Qué agente ejecutó la rotación y con qué par de claves se le cifró el
    # trabajo. SIN clave foránea a propósito: el reconciliador de esquema añade
    # columnas con ADD COLUMN y no crea FKs, así que una base que viene de la
    # 1.3.0 tendría la columna sin FK y una nueva con ella. Además el libro mayor
    # nunca se purga y el agente puede desaparecer con su activo: `agente_nombre`
    # mantiene el asiento legible, igual que `activo_nombre` con la credencial.
    agente_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    agente_nombre: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    clave_agente_huella: Mapped[str] = mapped_column(
        String(64), nullable=False, default="", server_default=""
    )

    credencial: Mapped[Credencial | None] = relationship()
    solicitado_por: Mapped[Usuario | None] = relationship(foreign_keys=[solicitado_por_id])
    autorizado_por: Mapped[Usuario | None] = relationship(foreign_keys=[autorizado_por_id])
    revisada_por: Mapped[Usuario | None] = relationship(foreign_keys=[revisada_por_id])
    rechazado_por: Mapped[Usuario | None] = relationship(foreign_keys=[rechazado_por_id])
    cancelado_por: Mapped[Usuario | None] = relationship(foreign_keys=[cancelado_por_id])

    @property
    def abierta(self) -> bool:
        return self.estado in ESTADOS_ROTACION_ABIERTOS

    @property
    def revision_pendiente(self) -> bool:
        """Emergencia ejecutada sin segundo par y aún sin revisar por otro admin."""
        return self.emergencia_sin_segundo_par and self.revisada_en is None


# ---------------------------------------------------------------------------
# Agentes de rotación (v1.4.0) — docs/plan-rotacion-agentes.md §3.1
# ---------------------------------------------------------------------------

# Ciclo de vida del agente. Lo que se GUARDA es solo lo que decide una persona
# o el propio enrolamiento; «conectado» y «sin contacto» se DERIVAN de
# `ultimo_contacto_en` y del umbral configurado. Guardarlos exigiría un proceso
# que los mantuviera al día, y una insignia que miente porque ese proceso no
# corrió es justo el «estado fantasma» que el plan prohíbe (§8.2).
AGENTE_PENDIENTE = "pendiente"   # dado de alta en el panel, aún sin enrolar
AGENTE_ACTIVO = "activo"         # enrolado: tiene identidad y puede recibir trabajos
AGENTE_REVOCADO = "revocado"     # sin identidad válida; se conserva como historia
ESTADOS_AGENTE = (AGENTE_PENDIENTE, AGENTE_ACTIVO, AGENTE_REVOCADO)

# Estados de un trabajo despachado a un agente (§3.2). El camino normal es
# PENDIENTE → ENTREGADO → APLICADO; el resto son cierres.
TRABAJO_PENDIENTE = "pendiente"
TRABAJO_ENTREGADO = "entregado"
TRABAJO_APLICADO = "aplicado"
TRABAJO_REVERTIDO = "revertido"
TRABAJO_FALLADO = "fallado"
TRABAJO_EXPIRADO = "expirado"
TRABAJO_CANCELADO = "cancelado"
ESTADOS_TRABAJO = (
    TRABAJO_PENDIENTE, TRABAJO_ENTREGADO, TRABAJO_APLICADO, TRABAJO_REVERTIDO,
    TRABAJO_FALLADO, TRABAJO_EXPIRADO, TRABAJO_CANCELADO,
)
# Estados en los que el trabajo ocupa el único turno de su agente.
ESTADOS_TRABAJO_ACTIVOS = (TRABAJO_PENDIENTE, TRABAJO_ENTREGADO)


def vinculo_activo(tipo: str, activo_id: int) -> str:
    """Valor de `Agente.vinculo_vigente` para un activo (p. ej. ``"fisico:12"``)."""
    return f"{tipo}:{activo_id}"


class Agente(Base):
    """Agente de rotación instalado en un activo Linux (servidor, hipervisor o VM).

    Un agente pertenece a **un** activo y solo ve los trabajos de ese activo. Su
    identidad es un token de vida corta, del que solo se guarda el hash, que se
    renueva en cada latido; el anterior sigue valiendo durante un solapamiento
    corto para no dejar fuera a un agente que no pudo recoger el nuevo (§2.1).

    Los dispositivos de red no llevan agente: los cubrirán los conectores de la
    2.3.0 (§6). De ahí que el vínculo sea uno-de entre TRES activos, no cuatro.
    """

    __tablename__ = "agentes"
    __table_args__ = (
        CheckConstraint(
            "(CASE WHEN servidor_fisico_id IS NULL THEN 0 ELSE 1 END"
            " + CASE WHEN hipervisor_id IS NULL THEN 0 ELSE 1 END"
            " + CASE WHEN maquina_virtual_id IS NULL THEN 0 ELSE 1 END) = 1",
            name="ck_agentes_un_activo",
        ),
        CheckConstraint(
            "estado IN ('pendiente', 'activo', 'revocado')", name="ck_agentes_estado"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)

    servidor_fisico_id: Mapped[int | None] = mapped_column(
        ForeignKey("servidores_fisicos.id", ondelete="CASCADE"), nullable=True, index=True
    )
    hipervisor_id: Mapped[int | None] = mapped_column(
        ForeignKey("hipervisores.id", ondelete="CASCADE"), nullable=True, index=True
    )
    maquina_virtual_id: Mapped[int | None] = mapped_column(
        ForeignKey("maquinas_virtuales.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Un solo agente VIGENTE por activo, garantizado por la base de datos: vale
    # "tipo:id" mientras el agente no está revocado y NULL después. Ni SQLite ni
    # MySQL cuentan los NULL como repetidos en un UNIQUE, y MySQL no admite
    # índices parciales: es la forma portable de que los revocados se conserven
    # como historia sin bloquear al siguiente agente del mismo activo.
    vinculo_vigente: Mapped[str | None] = mapped_column(String(40), unique=True, nullable=True)

    estado: Mapped[str] = mapped_column(
        String(20), nullable=False, default=AGENTE_PENDIENTE, server_default=AGENTE_PENDIENTE, index=True
    )

    # --- Enrolamiento de un solo uso ----------------------------------------
    # Se anula al consumirse: un segundo uso no encuentra nada que validar.
    enrolamiento_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    enrolamiento_expira_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    enrolado_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # --- Identidad de vida corta (§2.1) -------------------------------------
    token_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, index=True)
    token_expira_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    token_anterior_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    token_anterior_expira_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    token_renovado_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Dos renovaciones desde IPs distintas en la misma ventana son anomalía (§3.8).
    ip_ultima_renovacion: Mapped[str] = mapped_column(String(45), nullable=False, default="", server_default="")

    # Par X25519 del agente: el trabajo se le cifra a esta clave pública.
    clave_publica: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    clave_huella: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")

    # --- Lo que informa el propio agente ------------------------------------
    nombre_host: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    version_agente: Mapped[str] = mapped_column(String(40), nullable=False, default="", server_default="")
    ultimo_contacto_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ip_ultimo_contacto: Mapped[str] = mapped_column(String(45), nullable=False, default="", server_default="")

    rotacion_habilitada: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )

    creado_por_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True
    )
    creado_en: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=ahora_utc)
    revocado_por_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True
    )
    revocado_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    servidor_fisico: Mapped[ServidorFisico | None] = relationship()
    hipervisor: Mapped[Hipervisor | None] = relationship()
    maquina_virtual: Mapped[MaquinaVirtual | None] = relationship()
    creado_por: Mapped[Usuario | None] = relationship(foreign_keys=[creado_por_id])
    revocado_por: Mapped[Usuario | None] = relationship(foreign_keys=[revocado_por_id])

    @property
    def tipo_activo(self) -> str:
        if self.servidor_fisico_id is not None:
            return ACTIVO_FISICO
        if self.hipervisor_id is not None:
            return ACTIVO_HIPERVISOR
        return ACTIVO_VM

    @property
    def activo_id(self) -> int:
        return self.servidor_fisico_id or self.hipervisor_id or self.maquina_virtual_id  # type: ignore[return-value]

    @property
    def revocado(self) -> bool:
        return self.estado == AGENTE_REVOCADO


class TrabajoRotacion(Base):
    """Trabajo de rotación despachado a un agente (§2.2, §3.1).

    Lleva la contraseña nueva y la actual (ambas hacen falta para revertir de
    forma determinista), cifradas al par X25519 del agente. **Se purgan al
    cerrar**: el registro sobrevive como traza, los secretos no. Lo permanente
    es el asiento del libro mayor (`rotacion_id`).
    """

    __tablename__ = "trabajos_rotacion"
    __table_args__ = (
        CheckConstraint(
            "estado IN ('pendiente', 'entregado', 'aplicado', 'revertido',"
            " 'fallado', 'expirado', 'cancelado')",
            name="ck_trabajos_estado",
        ),
        CheckConstraint(
            "verificacion IN ('ninguna', 'local', 'remota')",
            name="ck_trabajos_verificacion",
        ),
        Index("ix_trabajos_agente_estado", "agente_id", "estado"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agente_id: Mapped[int] = mapped_column(
        ForeignKey("agentes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    credencial_id: Mapped[int] = mapped_column(
        ForeignKey("credenciales.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rotacion_id: Mapped[int] = mapped_column(
        ForeignKey("rotaciones_credencial.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Un solo trabajo ACTIVO por agente, garantizado por la base de datos: vale
    # el id del agente mientras el trabajo está pendiente o entregado, y NULL al
    # cerrarse. Mismo mecanismo portable que `Agente.vinculo_vigente`.
    activo_agente_id: Mapped[int | None] = mapped_column(Integer, unique=True, nullable=True)

    estado: Mapped[str] = mapped_column(
        String(20), nullable=False, default=TRABAJO_PENDIENTE, server_default=TRABAJO_PENDIENTE
    )

    # Secretos del trabajo, cifrados al agente. Nulos y SIN default: se purgan
    # al cerrar, y MySQL no admite DEFAULT en columnas BLOB.
    nueva_cifrada: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    actual_cifrada: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    clave_huella: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")

    ventana_expira_en: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    intentos: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    disparado_por_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True
    )
    creado_en: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=ahora_utc)
    entregado_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    confirmado_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    verificacion: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ROT_VERIF_NINGUNA, server_default=ROT_VERIF_NINGUNA
    )
    detalle_error: Mapped[str] = mapped_column(Text, nullable=False, default="")

    agente: Mapped[Agente] = relationship()
    credencial: Mapped[Credencial] = relationship()
    rotacion: Mapped[RotacionCredencial] = relationship()
    disparado_por: Mapped[Usuario | None] = relationship()

    @property
    def activo(self) -> bool:
        return self.estado in ESTADOS_TRABAJO_ACTIVOS


class TelemetriaAgente(Base):
    """Latido con métricas agregadas y datos de hardware del host del agente (§4.4).

    Solo agregados del propio host: sin procesos, usuarios ni rutas. El tamaño
    está acotado por contrato; si el agente tuvo que recortar para no pasarse,
    lo dice en `recortada` en vez de que el servidor amplíe su límite.
    """

    __tablename__ = "telemetria_agente"
    __table_args__ = (Index("ix_telemetria_agente_fecha", "agente_id", "fecha"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agente_id: Mapped[int] = mapped_column(
        ForeignKey("agentes.id", ondelete="CASCADE"), nullable=False
    )
    fecha: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=ahora_utc)

    cpu_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ram_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    disco_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uptime_s: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    sistema_operativo: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    kernel: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    cpu_modelo: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    ram_total: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    discos_json: Mapped[str] = mapped_column(Text, nullable=False, default="")
    recortada: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("0"))

    agente: Mapped[Agente] = relationship()
