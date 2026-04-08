import { Injectable } from '@angular/core';

export interface EncryptedPayload {
  cipherText: ArrayBuffer;
  iv: Uint8Array;
  authTag: Uint8Array;
  wrappedDek: ArrayBuffer;
  pbkdf2Salt: Uint8Array;
  pbkdf2Iterations: number;
}

const AES_KEY_LENGTH = 256;
const IV_LENGTH = 12;
const SALT_LENGTH = 32;
const AUTH_TAG_LENGTH_BITS = 128;
const AUTH_TAG_LENGTH_BYTES = AUTH_TAG_LENGTH_BITS / 8;
const DEFAULT_PBKDF2_ITERATIONS = 600_000;

@Injectable({ providedIn: 'root' })
export class CryptoService {
  async encrypt(plainPassword: string, masterPassword: string): Promise<EncryptedPayload> {
    const cryptoApi = this.getCryptoApi();

    const dek = await cryptoApi.subtle.generateKey(
      { name: 'AES-GCM', length: AES_KEY_LENGTH },
      true,
      ['encrypt', 'decrypt'],
    );

    const iv = cryptoApi.getRandomValues(new Uint8Array(IV_LENGTH));
    const plainBytes = new TextEncoder().encode(plainPassword);

    const cipherBuffer = await cryptoApi.subtle.encrypt(
      {
        name: 'AES-GCM',
        iv,
        tagLength: AUTH_TAG_LENGTH_BITS,
      },
      dek,
      plainBytes,
    );

    const cipherBytes = new Uint8Array(cipherBuffer);
    const tagIndex = cipherBytes.length - AUTH_TAG_LENGTH_BYTES;
    const actualCipherText = cipherBuffer.slice(0, tagIndex);
    const authTag = cipherBytes.slice(tagIndex);

    const pbkdf2Salt = cryptoApi.getRandomValues(new Uint8Array(SALT_LENGTH));
    const kek = await this.deriveKeyEncryptionKey(masterPassword, pbkdf2Salt, DEFAULT_PBKDF2_ITERATIONS);

    const wrappedDek = await cryptoApi.subtle.wrapKey('raw', dek, kek, { name: 'AES-KW' });

    return {
      cipherText: actualCipherText,
      iv,
      authTag,
      wrappedDek,
      pbkdf2Salt,
      pbkdf2Iterations: DEFAULT_PBKDF2_ITERATIONS,
    };
  }

  async decrypt(payload: EncryptedPayload, masterPassword: string): Promise<string> {
    const cryptoApi = this.getCryptoApi();

    const kek = await this.deriveKeyEncryptionKey(
      masterPassword,
      payload.pbkdf2Salt,
      payload.pbkdf2Iterations,
    );

    const dek = await cryptoApi.subtle.unwrapKey(
      'raw',
      payload.wrappedDek,
      kek,
      { name: 'AES-KW' },
      { name: 'AES-GCM', length: AES_KEY_LENGTH },
      false,
      ['decrypt'],
    );

    const cipherBytes = new Uint8Array(payload.cipherText);
    const fullCipher = new Uint8Array(cipherBytes.length + payload.authTag.length);
    fullCipher.set(cipherBytes, 0);
    fullCipher.set(payload.authTag, cipherBytes.length);

    const plainBuffer = await cryptoApi.subtle.decrypt(
      {
        name: 'AES-GCM',
        iv: payload.iv,
        tagLength: AUTH_TAG_LENGTH_BITS,
      },
      dek,
      fullCipher,
    );

    return new TextDecoder().decode(plainBuffer);
  }

  private async deriveKeyEncryptionKey(
    masterPassword: string,
    salt: Uint8Array,
    iterations: number,
  ): Promise<CryptoKey> {
    const cryptoApi = this.getCryptoApi();
    const passwordBytes = new TextEncoder().encode(masterPassword);

    const baseKey = await cryptoApi.subtle.importKey(
      'raw',
      passwordBytes,
      'PBKDF2',
      false,
      ['deriveKey'],
    );

    return cryptoApi.subtle.deriveKey(
      {
        name: 'PBKDF2',
        salt,
        iterations,
        hash: 'SHA-256',
      },
      baseKey,
      { name: 'AES-KW', length: AES_KEY_LENGTH },
      false,
      ['wrapKey', 'unwrapKey'],
    );
  }

  private getCryptoApi(): Crypto {
    const cryptoApi = globalThis.crypto;
    if (!cryptoApi?.subtle) {
      throw new Error('Web Crypto API is not available');
    }

    return cryptoApi;
  }
}