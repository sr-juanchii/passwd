"""Modelo de datos relacional.

Jerarquía del inventario (segmentación lógica solicitada):

    ServidorFisico  → servidor físico dedicado a una sola función (con sus credenciales)
    Hipervisor      → máquina física que ejecuta un hipervisor (Proxmox, ESXi, Hyper-V…)
        └── MaquinaVirtual (cada una con su sistema y función)

Servidores dedicados e hipervisores son dos tipos de activo de **nivel superior**
independientes: el hipervisor es la propia máquina física (con su hardware) y
contiene directamente sus máquinas virtuales. Cada nivel (servidor, hipervisor o
máquina virtual) puede tener una o varias credenciales (usuario + contraseña
cifrada en reposo + descripción del sistema o servicio al que da acceso). La
integridad se garantiza con claves foráneas y una restricción CHECK que obliga a
que cada credencial pertenezca exactamente a un activo.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
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
