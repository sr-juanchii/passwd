#!/usr/bin/env python3
"""Buzón SMTP en memoria para las pruebas de navegador.

Las pruebas de extremo a extremo necesitan leer los códigos que la aplicación
envía por correo (segundo factor por correo, contraseñas temporales). La
aplicación **no** expone ningún endpoint para consultarlos, y no debe: un
atajo para probar es un atajo para atacar.

En su lugar se levanta aquí un servidor SMTP de verdad, al que la aplicación
envía como enviaría a cualquier otro, y que escribe cada mensaje en un archivo
JSON dentro de un directorio. Las pruebas leen ese directorio. Desde el punto
de vista de la aplicación no hay nada especial: un servidor de correo más.

    python scripts/buzon_pruebas.py --puerto 8025 --directorio .buzon

No tiene autenticación ni TLS y escucha **solo en 127.0.0.1**: es una pieza de
banco de pruebas y no debe ejecutarse en ningún entorno real.
"""

from __future__ import annotations

import argparse
import asyncio
import email
import json
import logging
import time
from email.header import decode_header, make_header
from email.message import Message
from pathlib import Path

from aiosmtpd.controller import Controller

logger = logging.getLogger("buzon")


def _texto_de(mensaje: Message) -> str:
    """Cuerpo en texto plano del mensaje, decodificado."""
    if not mensaje.is_multipart():
        carga = mensaje.get_payload(decode=True)
        if carga is None:
            return str(mensaje.get_payload())
        return carga.decode(mensaje.get_content_charset() or "utf-8", errors="replace")
    for parte in mensaje.walk():
        if parte.get_content_type() == "text/plain":
            carga = parte.get_payload(decode=True) or b""
            return carga.decode(parte.get_content_charset() or "utf-8", errors="replace")
    return ""


class Buzon:
    """Manejador que persiste cada mensaje recibido como un JSON."""

    def __init__(self, directorio: Path) -> None:
        self.directorio = directorio
        self.directorio.mkdir(parents=True, exist_ok=True)
        self._secuencia = 0

    async def handle_DATA(self, server, session, envelope):  # noqa: N802 — API de aiosmtpd
        mensaje = email.message_from_bytes(envelope.content)
        self._secuencia += 1
        registro = {
            "recibido_en": time.time(),
            "de": envelope.mail_from,
            "para": list(envelope.rcpt_tos),
            # El asunto llega codificado en RFC 2047 cuando lleva acentos; se
            # decodifica aquí para que las pruebas puedan buscar texto legible.
            "asunto": str(make_header(decode_header(str(mensaje.get("Subject", ""))))),
            "cuerpo": _texto_de(mensaje),
        }
        destino = self.directorio / f"{int(registro['recibido_en'] * 1000)}-{self._secuencia:04d}.json"
        destino.write_text(json.dumps(registro, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Mensaje para %s guardado en %s", registro["para"], destino.name)
        return "250 Mensaje aceptado por el buzón de pruebas"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--puerto", type=int, default=8025)
    parser.add_argument("--directorio", default=".buzon",
                        help="Dónde escribir los mensajes recibidos (se vacía al arrancar).")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    # aiosmtpd registra cada línea del diálogo SMTP en INFO. Con una tanda
    # entera de pruebas eso sepulta la salida útil; los mensajes recibidos se
    # siguen anunciando por el logger propio.
    logging.getLogger("mail.log").setLevel(logging.WARNING)
    directorio = Path(args.directorio)
    if directorio.exists():
        for antiguo in directorio.glob("*.json"):
            antiguo.unlink()

    controlador = Controller(Buzon(directorio), hostname="127.0.0.1", port=args.puerto)
    controlador.start()
    logger.info("Buzón de pruebas escuchando en 127.0.0.1:%d → %s", args.puerto, directorio)
    try:
        asyncio.new_event_loop().run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        controlador.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
