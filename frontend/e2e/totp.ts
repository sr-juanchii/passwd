import { createHmac } from "node:crypto";

/**
 * Generador TOTP (RFC 6238) para las pruebas de navegador.
 *
 * Son veinticinco líneas con el `crypto` de Node y cero dependencias. La
 * alternativa era arrastrar una biblioteca con su propio sistema de plugins
 * criptográficos para esto mismo.
 *
 * No hace falta confiar en que esté bien: lo verifica la propia aplicación. Si
 * el código generado aquí no fuera válido, el enrolamiento del segundo factor
 * fallaría en la primera prueba y de forma evidente.
 */

const ALFABETO_BASE32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";

function decodificarBase32(secreto: string): Buffer {
  const limpio = secreto.replace(/[\s=]/g, "").toUpperCase();
  let bits = "";
  for (const caracter of limpio) {
    const valor = ALFABETO_BASE32.indexOf(caracter);
    if (valor < 0) throw new Error(`Carácter no válido en el secreto base32: ${caracter}`);
    bits += valor.toString(2).padStart(5, "0");
  }
  const bytes: number[] = [];
  for (let i = 0; i + 8 <= bits.length; i += 8) {
    bytes.push(parseInt(bits.slice(i, i + 8), 2));
  }
  return Buffer.from(bytes);
}

/** Código de 6 dígitos para el paso temporal actual (ventana de 30 s). */
export function generarTotp(secreto: string, enSegundos = Date.now() / 1000): string {
  const paso = Math.floor(enSegundos / 30);
  const contador = Buffer.alloc(8);
  contador.writeBigUInt64BE(BigInt(paso));

  const resumen = createHmac("sha1", decodificarBase32(secreto)).update(contador).digest();
  // Truncamiento dinámico (RFC 4226 §5.3): el nibble bajo del último byte dice
  // dónde empiezan los cuatro bytes que forman el código.
  const desplazamiento = resumen[resumen.length - 1] & 0x0f;
  const binario =
    ((resumen[desplazamiento] & 0x7f) << 24) |
    ((resumen[desplazamiento + 1] & 0xff) << 16) |
    ((resumen[desplazamiento + 2] & 0xff) << 8) |
    (resumen[desplazamiento + 3] & 0xff);
  return (binario % 1_000_000).toString().padStart(6, "0");
}
