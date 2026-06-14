"""Control de acceso basado en roles (CIS v8.1 safeguard 6.8).

Este módulo define la autorización *por tipo de operación* (RBAC estático). La
autorización *por objeto* —qué activos concretos puede ver/usar un analista—
vive en ``app/access.py`` y se evalúa contra las concesiones de cada usuario.

Matriz de permisos (a nivel de ruta):

    Permiso                  admin  operador  auditor  analista
    ----------------------   -----  --------  -------  --------
    inventario.ver             ✔       ✔         ✔        ✔ (*)
    inventario.gestionar       ✔       ✔         ✘        ✘
    credenciales.ver_lista     ✔       ✔         ✔        ✔ (*)
    credenciales.revelar       ✔       ✔         ✘        ✔ (*)
    credenciales.gestionar     ✔       ✔         ✘        ✘
    usuarios.gestionar         ✔       ✘         ✘        ✘
    auditoria.ver              ✔       ✘         ✔        ✘
    accesos.gestionar          ✔       ✘         ✘        ✘

(*) El analista alcanza la ruta, pero ``app/access.py`` restringe la operación
    a los activos que tenga concedidos (default-deny: sin concesiones no ve nada).
"""

from __future__ import annotations

from app.models import ROL_ADMIN, ROL_ANALISTA, ROL_AUDITOR, ROL_OPERADOR

PERMISOS: dict[str, frozenset[str]] = {
    "inventario.ver": frozenset({ROL_ADMIN, ROL_OPERADOR, ROL_AUDITOR, ROL_ANALISTA}),
    "inventario.gestionar": frozenset({ROL_ADMIN, ROL_OPERADOR}),
    "credenciales.ver_lista": frozenset({ROL_ADMIN, ROL_OPERADOR, ROL_AUDITOR, ROL_ANALISTA}),
    "credenciales.revelar": frozenset({ROL_ADMIN, ROL_OPERADOR, ROL_ANALISTA}),
    "credenciales.gestionar": frozenset({ROL_ADMIN, ROL_OPERADOR}),
    "usuarios.gestionar": frozenset({ROL_ADMIN}),
    "auditoria.ver": frozenset({ROL_ADMIN, ROL_AUDITOR}),
    "metricas.ver": frozenset({ROL_ADMIN, ROL_AUDITOR}),
    "accesos.gestionar": frozenset({ROL_ADMIN}),
}

ETIQUETAS_ROL = {
    ROL_ADMIN: "Administrador",
    ROL_OPERADOR: "Operador",
    ROL_AUDITOR: "Auditor (solo lectura)",
    ROL_ANALISTA: "Analista (acceso por concesión)",
}


def tiene_permiso(rol: str, permiso: str) -> bool:
    return rol in PERMISOS.get(permiso, frozenset())
