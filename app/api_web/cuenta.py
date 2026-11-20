"""«Mi seguridad»: gestión del segundo factor por el propio usuario (`/api/web`).

Permite al titular, con la sesión ya activa:

* Ver su método principal y cuántos códigos de recuperación le quedan.
* Cambiar de método: de aplicación autenticadora a correo, o al revés.
* Regenerar sus códigos de recuperación.

Todas las operaciones que alteran el segundo factor exigen **reautenticación**
(la contraseña actual) además de una prueba del factor implicado, de modo que
una sesión abierta y desatendida no baste para debilitar la cuenta. Los fallos
cuentan para el bloqueo de la cuenta y hay un límite de tasa propio.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, avisos
from app.api_web.deps import sesion_activa_json, usuario_actual_json, verificar_csrf_json
from app.database import get_db
from app.models import MFA_CORREO, MFA_TOTP, SesionWeb, Usuario
from app.notifications import enviar_alerta
from app.security import mfa, otp_correo, ratelimit, recovery, segundo_factor
from app.security.crypto import cifrar, descifrar
from app.security.passwords import verificar_password
from app.security.sessions import borrar_cookie, revocar_sesion
from app.servicios import autenticacion
from app.servicios.autenticacion import ErrorAutenticacion

router = APIRouter()

CSRF = Depends(verificar_csrf_json)


class Reautenticacion(BaseModel):
    password: str = ""


class ReautenticacionConCodigo(BaseModel):
    password: str = ""
    codigo: str = ""


class SoloCodigo(BaseModel):
    codigo: str = ""


def _limitar(db: Session, usuario: Usuario) -> None:
    if not ratelimit.permitir_intento(f"cuenta-seguridad:{usuario.id}", db=db):
        db.commit()
        raise HTTPException(status_code=429, detail="Demasiados intentos; espere unos minutos.")


def _fallo(db: Session, request: Request, usuario: Usuario, sesion: SesionWeb,
           detalle: str, mensaje: str):
    """Fallo de reautenticación: cuenta para el bloqueo; si bloquea, cierra la sesión."""
    autenticacion.registrar_fallo(db, usuario, request)
    audit.registrar(db, audit.MFA_FALLIDO, request=request, usuario=usuario,
                    detalle=detalle, exito=False)
    if usuario.esta_bloqueado():
        revocar_sesion(sesion)
        db.commit()
        respuesta = JSONResponse({"detail": "Cuenta bloqueada; vuelva a iniciar sesión."},
                                 status_code=423)
        borrar_cookie(respuesta)
        return respuesta
    db.commit()
    raise HTTPException(status_code=400, detail=mensaje)


def _revocar_otras_sesiones(db: Session, usuario: Usuario, actual: SesionWeb) -> None:
    otras = db.scalars(select(SesionWeb).where(
        SesionWeb.usuario_id == usuario.id, SesionWeb.revocada_en.is_(None),
        SesionWeb.id != actual.id)).all()
    for sesion in otras:
        revocar_sesion(sesion)


def _estado(db: Session, usuario: Usuario) -> dict:
    correo_disponible = segundo_factor.correo_principal_disponible(usuario)
    return {
        "metodo": usuario.mfa_metodo,
        "codigos_restantes": recovery.codigos_restantes(db, usuario),
        "destino": avisos.enmascarar_correo(usuario.email),
        "puede_cambiar_a_correo": usuario.mfa_metodo == MFA_TOTP and correo_disponible,
        "motivo_correo": "" if correo_disponible
        else segundo_factor.motivo_correo_no_disponible(usuario),
        "puede_cambiar_a_totp": usuario.mfa_metodo == MFA_CORREO,
        "correo_operativo": segundo_factor.correo_en_login(usuario)
        if usuario.mfa_metodo == MFA_CORREO else correo_disponible,
    }


@router.get("/cuenta/seguridad")
def seguridad(
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, Depends(usuario_actual_json)],
):
    return _estado(db, usuario)


@router.post("/cuenta/mfa/correo/enviar", dependencies=[CSRF])
def enviar_codigo(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[Usuario, Depends(usuario_actual_json)],
):
    """Envía un código al buzón del usuario: para activar el correo como método
    o, si ya lo es, para acreditar el segundo factor en esta pantalla."""
    if usuario.mfa_metodo == MFA_CORREO:
        if not segundo_factor.correo_en_login(usuario):
            raise HTTPException(status_code=409, detail="El servicio de correo no está disponible.")
    elif not segundo_factor.correo_principal_disponible(usuario):
        raise HTTPException(status_code=409,
                            detail=segundo_factor.motivo_correo_no_disponible(usuario))
    try:
        return autenticacion.enviar_codigo_correo(
            db, usuario=usuario, proposito="Mi seguridad", request=request,
        )
    except ErrorAutenticacion as exc:
        raise HTTPException(status_code=exc.codigo, detail=exc.mensaje) from exc


@router.post("/cuenta/mfa/correo/activar", dependencies=[CSRF])
def activar_correo(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    sesion: Annotated[SesionWeb, Depends(sesion_activa_json)],
    usuario: Annotated[Usuario, Depends(usuario_actual_json)],
    cuerpo: ReautenticacionConCodigo,
):
    """Pasa de aplicación autenticadora a código por correo.

    Exige la contraseña y un código recibido en el buzón (prueba de que el
    usuario lo controla). El secreto TOTP se elimina."""
    if usuario.mfa_metodo != MFA_TOTP:
        raise HTTPException(status_code=409, detail="El correo ya es su método principal.")
    if not segundo_factor.correo_principal_disponible(usuario):
        raise HTTPException(status_code=409,
                            detail=segundo_factor.motivo_correo_no_disponible(usuario))
    _limitar(db, usuario)
    if not verificar_password(usuario.password_hash, cuerpo.password):
        return _fallo(db, request, usuario, sesion, "Contraseña incorrecta al cambiar de método MFA.",
                      "La contraseña no es correcta.")
    if not otp_correo.consumir(db, usuario, cuerpo.codigo):
        return _fallo(db, request, usuario, sesion, "Código por correo incorrecto al cambiar de método MFA.",
                      "Código incorrecto o caducado. Revise su correo o pida uno nuevo.")
    otp_correo.invalidar_codigos(db, usuario.id)

    usuario.mfa_metodo = MFA_CORREO
    usuario.totp_secret_cifrado = None
    usuario.ultimo_totp_paso = None
    usuario.ultimo_otp_usado = None
    usuario.intentos_fallidos = 0
    _revocar_otras_sesiones(db, usuario, sesion)
    audit.registrar(db, audit.MFA_METODO_CAMBIADO, request=request, usuario=usuario,
                    detalle="Método principal: aplicación autenticadora → correo.")
    enviar_alerta(
        "Cambio de método de verificación en dos pasos",
        f"La cuenta «{usuario.username}» cambió su segundo factor de aplicación "
        "autenticadora a código por correo.",
    )
    avisos.aviso_cambio_metodo_mfa(
        usuario, "aplicación autenticadora → código por correo",
        request.client.host if request.client else "")
    db.commit()
    return _estado(db, usuario)


@router.post("/cuenta/mfa/totp/iniciar", dependencies=[CSRF])
def iniciar_totp(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    sesion: Annotated[SesionWeb, Depends(sesion_activa_json)],
    usuario: Annotated[Usuario, Depends(usuario_actual_json)],
    cuerpo: Reautenticacion,
):
    """Empieza el paso de correo a aplicación autenticadora: genera el secreto
    (inerte hasta confirmarlo) y devuelve el QR. Exige la contraseña."""
    if usuario.mfa_metodo != MFA_CORREO:
        raise HTTPException(
            status_code=409,
            detail="Ya usa una aplicación autenticadora. Para cambiar de dispositivo, "
                   "pida al administrador que reinicie su verificación en dos pasos.")
    _limitar(db, usuario)
    if not verificar_password(usuario.password_hash, cuerpo.password):
        return _fallo(db, request, usuario, sesion, "Contraseña incorrecta al cambiar de método MFA.",
                      "La contraseña no es correcta.")
    # Mientras el método siga siendo «correo» este secreto no autentica nada.
    usuario.totp_secret_cifrado = cifrar(mfa.generar_secreto())
    secreto = descifrar(usuario.totp_secret_cifrado)
    db.commit()
    return JSONResponse(
        {"qr_data_uri": mfa.qr_svg_data_uri(secreto, usuario.username), "secreto": secreto},
        headers={"Cache-Control": "no-store"},
    )


@router.post("/cuenta/mfa/totp/activar", dependencies=[CSRF])
def activar_totp(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    sesion: Annotated[SesionWeb, Depends(sesion_activa_json)],
    usuario: Annotated[Usuario, Depends(usuario_actual_json)],
    cuerpo: SoloCodigo,
):
    """Confirma el código de la aplicación y la deja como método principal."""
    if usuario.mfa_metodo != MFA_CORREO or usuario.totp_secret_cifrado is None:
        raise HTTPException(status_code=409, detail="Inicie de nuevo el cambio de método.")
    _limitar(db, usuario)
    valido, _reutilizado = segundo_factor.aceptar_totp(usuario, cuerpo.codigo)
    if not valido:
        return _fallo(db, request, usuario, sesion, "Código TOTP incorrecto al cambiar de método MFA.",
                      "Código incorrecto. Verifique su aplicación autenticadora.")
    usuario.mfa_metodo = MFA_TOTP
    usuario.intentos_fallidos = 0
    otp_correo.invalidar_codigos(db, usuario.id)
    _revocar_otras_sesiones(db, usuario, sesion)
    audit.registrar(db, audit.MFA_METODO_CAMBIADO, request=request, usuario=usuario,
                    detalle="Método principal: correo → aplicación autenticadora.")
    avisos.aviso_cambio_metodo_mfa(
        usuario, "código por correo → aplicación autenticadora",
        request.client.host if request.client else "")
    db.commit()
    return _estado(db, usuario)


@router.post("/cuenta/mfa/codigos", dependencies=[CSRF])
def regenerar_codigos(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    sesion: Annotated[SesionWeb, Depends(sesion_activa_json)],
    usuario: Annotated[Usuario, Depends(usuario_actual_json)],
    cuerpo: ReautenticacionConCodigo,
):
    """Sustituye los códigos de recuperación (los anteriores dejan de valer).

    Exige la contraseña y un código vigente del segundo factor."""
    _limitar(db, usuario)
    if not verificar_password(usuario.password_hash, cuerpo.password):
        return _fallo(db, request, usuario, sesion,
                      "Contraseña incorrecta al regenerar códigos de recuperación.",
                      "La contraseña no es correcta.")
    if not segundo_factor.comprobar(db, usuario, cuerpo.codigo).valido:
        return _fallo(db, request, usuario, sesion,
                      "Segundo factor incorrecto al regenerar códigos de recuperación.",
                      "Código de verificación incorrecto.")
    usuario.intentos_fallidos = 0
    codigos = recovery.emitir_codigos(db, usuario)
    audit.registrar(db, audit.MFA_CODIGOS_REGENERADOS, request=request, usuario=usuario,
                    detalle=f"{len(codigos)} códigos de recuperación nuevos; los anteriores quedan anulados.")
    db.commit()
    return JSONResponse({"codigos_recuperacion": codigos}, headers={"Cache-Control": "no-store"})
