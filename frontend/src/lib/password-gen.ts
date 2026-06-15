// Generador de contraseñas robustas con CSPRNG del navegador.
// 20 caracteres, alfabeto sin ambigüedades (idéntico al de la web Jinja).

const ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!#$%&*+-=?@_";

export function generarPassword(longitud = 20): string {
  const valores = new Uint32Array(longitud);
  crypto.getRandomValues(valores);
  let salida = "";
  for (let i = 0; i < longitud; i++) {
    salida += ALFABETO[valores[i] % ALFABETO.length];
  }
  return salida;
}
