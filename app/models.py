"""Modelo de datos relacional.

Jerarquía del inventario (segmentación lógica solicitada):

    ServidorFisico (tipo = funcion_unica)      → servidor físico dedicado a un solo sistema
    ServidorFisico (tipo = host_virtualizacion) → servidor físico sin función única que aloja
        └── Hipervisor (Proxmox, ESXi, Hyper-V, …)
                └── MaquinaVirtual (cada una con su sistema y función)

Cada nivel (servidor físico, hipervisor o máquina virtual) puede tener una o
varias credenciales (usuario + contraseña cifrada en reposo + descripción del
sistema o servicio al que da acceso). La integridad se garantiza con claves
foráneas y una restricción CHECK que obliga a que cada credencial pertenezca
exactamente a un activo.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
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

TIPO_FUNCION_UNICA = "funcion_unica"
TIPO_HOST_VIRTUALIZACION = "host_virtualizacion"
TIPOS_SERVIDOR = (TIPO_FUNCION_UNICA, TIPO_HOST_VIRTUALIZACION)

ETIQUETAS_TIPO_SERVIDOR = {
    TIPO_FUNCION_UNICA: "Servidor físico de función única",
    TIPO_HOST_VIRTUALIZACION: "Servidor físico host de virtualización",
}

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
    """Servidor físico: dedicado a una sola función o host de hipervisores."""

    __tablename__ = "servidores_fisicos"
    __table_args__ = (
        CheckConstraint(
            f"tipo IN ('{TIPO_FUNCION_UNICA}', '{TIPO_HOST_VIRTUALIZACION}')",
            name="ck_servidores_tipo",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    tipo: Mapped[str] = mapped_column(String(32), nullable=False, default=TIPO_FUNCION_UNICA)
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
    # Notas sensibles cifradas en reposo (instrucciones de acceso, tokens, etc.)
    notas_cifradas: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=ahora_utc)
    actualizado_en: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=ahora_utc, onupdate=ahora_utc)

    hipervisores: Mapped[list[Hipervisor]] = relationship(
        back_populates="servidor_fisico", cascade="all, delete-orphan", order_by="Hipervisor.nombre"
    )
    credenciales: Mapped[list[Credencial]] = relationship(
        back_populates="servidor_fisico", cascade="all, delete-orphan"
    )

    @property
    def etiqueta_tipo(self) -> str:
        return ETIQUETAS_TIPO_SERVIDOR.get(self.tipo, self.tipo)

    @property
    def lista_etiquetas(self) -> list[str]:
        return [e for e in (self.etiquetas or "").split(", ") if e]


class Hipervisor(Base):
    """Hipervisor instalado en un servidor físico host de virtualización."""

    __tablename__ = "hipervisores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    servidor_fisico_id: Mapped[int] = mapped_column(
        ForeignKey("servidores_fisicos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    plataforma: Mapped[str] = mapped_column(String(60), nullable=False, default="")  # Proxmox, ESXi, Hyper-V…
    version: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    ip_gestion: Mapped[str] = mapped_column(String(45), nullable=False, default="")
    descripcion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default=ESTADO_ACTIVO, server_default=ESTADO_ACTIVO)
    etiquetas: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    notas_cifradas: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=ahora_utc)
    actualizado_en: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=ahora_utc, onupdate=ahora_utc)

    servidor_fisico: Mapped[ServidorFisico] = relationship(back_populates="hipervisores")
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


ACTIVO_FISICO = "fisico"
ACTIVO_HIPERVISOR = "hipervisor"
ACTIVO_VM = "vm"


class Credencial(Base):
    """Credencial de acceso a un activo del inventario.

    La contraseña se cifra en reposo (Fernet/AES) antes de persistirse.
    Exactamente una de las tres claves foráneas debe estar presente.
    """

    __tablename__ = "credenciales"
    __table_args__ = (
        CheckConstraint(
            "(CASE WHEN servidor_fisico_id IS NULL THEN 0 ELSE 1 END"
            " + CASE WHEN hipervisor_id IS NULL THEN 0 ELSE 1 END"
            " + CASE WHEN maquina_virtual_id IS NULL THEN 0 ELSE 1 END) = 1",
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

    servidor_fisico: Mapped[ServidorFisico | None] = relationship(back_populates="credenciales")
    hipervisor: Mapped[Hipervisor | None] = relationship(back_populates="credenciales")
    maquina_virtual: Mapped[MaquinaVirtual | None] = relationship(back_populates="credenciales")
    creado_por: Mapped[Usuario | None] = relationship()

    @property
    def tipo_activo(self) -> str:
        if self.servidor_fisico_id is not None:
            return ACTIVO_FISICO
        if self.hipervisor_id is not None:
            return ACTIVO_HIPERVISOR
        return ACTIVO_VM

    @property
    def nombre_activo(self) -> str:
        if self.servidor_fisico is not None:
            return self.servidor_fisico.nombre
        if self.hipervisor is not None:
            return self.hipervisor.nombre
        if self.maquina_virtual is not None:
            return self.maquina_virtual.nombre
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
            " + CASE WHEN maquina_virtual_id IS NULL THEN 0 ELSE 1 END) = 1",
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
        return ACTIVO_VM

    @property
    def nombre_activo(self) -> str:
        if self.servidor_fisico is not None:
            return self.servidor_fisico.nombre
        if self.hipervisor is not None:
            return self.hipervisor.nombre
        if self.maquina_virtual is not None:
            return self.maquina_virtual.nombre
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
    """Bitácora inmutable de eventos de seguridad y acceso a credenciales."""

    __tablename__ = "registros_auditoria"

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
