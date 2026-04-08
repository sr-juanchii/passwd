import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, from, switchMap } from 'rxjs';

import { CryptoService, EncryptedPayload } from '../crypto/crypto.service';
import {
  arrayBufferToBase64,
  base64ToArrayBuffer,
  base64ToUint8Array,
  uint8ArrayToBase64,
} from '../crypto/encoding.utils';

export interface CreateCredentialRequest {
  serverId: string;
  credentialUsername: string;
  plainPassword: string;
  masterPassword: string;
}

export interface CredentialResponse {
  id: string;
  server_id: string;
  credential_username: string;
  cipher_text: string;
  wrapped_dek: string;
  iv: string;
  auth_tag: string;
  pbkdf2_salt: string;
  pbkdf2_iterations: number;
  created_at?: string;
  updated_at?: string;
}

@Injectable({ providedIn: 'root' })
export class CredentialsApiService {
  private readonly http = inject(HttpClient);
  private readonly cryptoService = inject(CryptoService);
  private readonly apiUrl = 'http://localhost:8000/api/v1/credentials';

  createCredential(request: CreateCredentialRequest): Observable<{ id: string }> {
    return from(this.cryptoService.encrypt(request.plainPassword, request.masterPassword)).pipe(
      switchMap((encryptedPayload) => {
        const body = {
          server_id: request.serverId,
          credential_username: request.credentialUsername,
          cipher_text: arrayBufferToBase64(encryptedPayload.cipherText),
          wrapped_dek: arrayBufferToBase64(encryptedPayload.wrappedDek),
          iv: uint8ArrayToBase64(encryptedPayload.iv),
          auth_tag: uint8ArrayToBase64(encryptedPayload.authTag),
          pbkdf2_salt: uint8ArrayToBase64(encryptedPayload.pbkdf2Salt),
          pbkdf2_iterations: encryptedPayload.pbkdf2Iterations,
        };

        return this.http.post<{ id: string }>(this.apiUrl, body);
      }),
    );
  }

  async decryptCredential(credential: CredentialResponse, masterPassword: string): Promise<string> {
    const payload: EncryptedPayload = {
      cipherText: base64ToArrayBuffer(credential.cipher_text),
      wrappedDek: base64ToArrayBuffer(credential.wrapped_dek),
      iv: base64ToUint8Array(credential.iv),
      authTag: base64ToUint8Array(credential.auth_tag),
      pbkdf2Salt: base64ToUint8Array(credential.pbkdf2_salt),
      pbkdf2Iterations: credential.pbkdf2_iterations,
    };

    return this.cryptoService.decrypt(payload, masterPassword);
  }
}