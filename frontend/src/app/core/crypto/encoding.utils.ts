function encodeBytes(bytes: Uint8Array): string {
  if (typeof btoa === 'function') {
    let binary = '';
    for (const byte of bytes) {
      binary += String.fromCharCode(byte);
    }
    return btoa(binary);
  }

  throw new Error('Base64 encoding is not available in this environment');
}

function decodeBytes(base64: string): Uint8Array {
  if (typeof atob === 'function') {
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) {
      bytes[index] = binary.charCodeAt(index);
    }
    return bytes;
  }

  throw new Error('Base64 decoding is not available in this environment');
}

export function arrayBufferToBase64(buffer: ArrayBuffer): string {
  return encodeBytes(new Uint8Array(buffer));
}

export function uint8ArrayToBase64(bytes: Uint8Array): string {
  return encodeBytes(bytes);
}

export function base64ToArrayBuffer(base64: string): ArrayBuffer {
  return decodeBytes(base64).buffer;
}

export function base64ToUint8Array(base64: string): Uint8Array {
  return decodeBytes(base64);
}