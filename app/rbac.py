"""Control de acceso basado en roles (CIS v8.1 safeguard 6.8).

Matriz de permisos documentada y aplicada en código:

    Permiso                  admin  operador  auditor
    ----------------------   -----  --------  -------
    inventario.ver             ✔       ✔         ✔
    inventario.gestionar       ✔       ✔         ✘
    credenciales.ver_lista     ✔       ✔         ✔   (sin contraseñas)
    credenciales.revelar       ✔       ✔         ✘
    credenciales.gestionar     ✔       ✔         ✘
    usuarios.gestionar         ✔       ✘         ✘
    auditoria.ver              ✔       ✘         ✔
"""

from __future__ import annotations

from app.models import ROL_ADMIN, ROL_AUDITOR, ROL_OPERADOR

PERMISOS: dict[str, frozenset[str]] = {
    "inventario.ver": frozenset({ROL_ADMIN, ROL_OPERADOR, ROL_AUDITOR}),
    "inventario.gestionar": frozenset({ROL_ADMIN, ROL_OPERADOR}),
    "credenciales.ver_lista": frozenset({ROL_ADMIN, ROL_OPERADOR, ROL_AUDITOR}),
    "credenciales.revelar": frozenset({ROL_ADMIN, ROL_OPERADOR}),
    "credenciales.gestionar": frozenset({ROL_ADMIN, ROL_OPERADOR}),
    "usuarios.gestionar": frozenset({ROL_ADMIN}),
    "auditoria.ver": frozenset({ROL_ADMIN, ROL_AUDITOR}),
}

ETIQUETAS_ROL = {
    ROL_ADMIN: "Administrador",
    ROL_OPERADOR: "Operador",
    ROL_AUDITOR: "Auditor (solo lectura)",
}


def tiene_permiso(rol: str, permiso: str) -> bool:
    return rol in PERMISOS.get(permiso, frozenset())
