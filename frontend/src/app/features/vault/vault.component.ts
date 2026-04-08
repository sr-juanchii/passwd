import { AsyncPipe, CommonModule } from '@angular/common';
import { Component, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { CredentialsApiService } from '../../core/api/credentials-api.service';
import { AuthService } from '../../core/auth/auth.service';
import { CryptoService } from '../../core/crypto/crypto.service';
import { arrayBufferToBase64, uint8ArrayToBase64 } from '../../core/crypto/encoding.utils';

@Component({
  selector: 'app-vault',
  standalone: true,
  imports: [CommonModule, AsyncPipe, RouterLink],
  template: `
    <section class="panel">
      <div class="panel__eyebrow">Protected area</div>
      <h2>Vault entry point</h2>
      <p>
        The browser already owns the session, and the backend only receives bearer
        tokens on explicit API calls.
      </p>

      <div class="identity" *ngIf="identity$ | async as identity">
        <strong>{{ identity.preferredUsername }}</strong>
        <span>{{ identity.sub }}</span>
        <div class="chips">
          <span class="chip" *ngFor="let role of identity.roles">{{ role }}</span>
        </div>
      </div>

      <div class="token" *ngIf="token$ | async as token">
        <span class="token__label">Access token preview</span>
        <code>{{ token.slice(0, 40) }}{{ token.length > 40 ? '…' : '' }}</code>
      </div>

      <div class="actions">
        <a routerLink="/admin" class="ghost">Open admin console</a>
        <a routerLink="/" class="ghost ghost--soft">Back to shell</a>
      </div>

      <div class="demo">
        <div class="demo__eyebrow">Local crypto demo</div>
        <p>
          Runs the AES-256-GCM + PBKDF2 + AES-KW roundtrip entirely in memory and
          uses the API service to reverse the payload.
        </p>

        <div class="demo__actions">
          <button type="button" class="ghost" (click)="runCryptoDemo()" [disabled]="demoRunning()">
            {{ demoRunning() ? 'Running…' : 'Run roundtrip' }}
          </button>
        </div>

        <code>{{ demoStatus() }}</code>
      </div>
    </section>
  `,
  styles: [
    `
      .panel {
        margin-top: 1.5rem;
        padding: 1.5rem;
        border: 1px solid var(--border);
        border-radius: 1.5rem;
        background: linear-gradient(180deg, rgba(15, 23, 42, 0.76), rgba(8, 12, 24, 0.92));
        box-shadow: 0 24px 80px rgba(2, 6, 23, 0.36);
      }

      .panel__eyebrow {
        display: inline-flex;
        align-items: center;
        gap: 0.5rem;
        margin-bottom: 0.75rem;
        color: var(--accent);
        text-transform: uppercase;
        letter-spacing: 0.24em;
        font-size: 0.72rem;
      }

      h2 {
        margin: 0;
        font-size: 1.6rem;
      }

      p {
        margin: 0.75rem 0 0;
        color: var(--muted);
        line-height: 1.7;
      }

      .identity,
      .token {
        margin-top: 1rem;
        padding: 1rem;
        border-radius: 1rem;
        background: var(--panel);
        border: 1px solid rgba(148, 163, 184, 0.14);
      }

      .identity strong {
        display: block;
        font-size: 1.1rem;
      }

      .identity span,
      .token__label {
        display: block;
        color: var(--muted);
        font-size: 0.88rem;
      }

      .chips {
        display: flex;
        flex-wrap: wrap;
        gap: 0.5rem;
        margin-top: 0.75rem;
      }

      .chip {
        padding: 0.35rem 0.7rem;
        border-radius: 999px;
        background: rgba(96, 165, 250, 0.14);
        color: #bfdbfe;
        font-size: 0.78rem;
        letter-spacing: 0.08em;
      }

      code {
        display: block;
        margin-top: 0.5rem;
        padding: 0.85rem 1rem;
        border-radius: 0.9rem;
        background: rgba(2, 6, 23, 0.75);
        color: #93c5fd;
        word-break: break-all;
      }

      .actions {
        display: flex;
        gap: 0.75rem;
        flex-wrap: wrap;
        margin-top: 1rem;
      }

      .ghost {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-height: 2.75rem;
        padding: 0.65rem 1rem;
        border-radius: 999px;
        border: 1px solid rgba(148, 163, 184, 0.18);
        color: var(--text);
        text-decoration: none;
      }

      .ghost--soft {
        color: #dbeafe;
        background: rgba(96, 165, 250, 0.12);
      }

      .demo {
        margin-top: 1rem;
        padding: 1rem;
        border-radius: 1rem;
        background: rgba(2, 6, 23, 0.55);
        border: 1px solid rgba(148, 163, 184, 0.14);
      }

      .demo__eyebrow {
        color: var(--accent);
        text-transform: uppercase;
        letter-spacing: 0.2em;
        font-size: 0.72rem;
      }

      .demo__actions {
        margin-top: 0.75rem;
      }
    `,
  ],
})
export class VaultComponent {
  private readonly authService = inject(AuthService);
  private readonly cryptoService = inject(CryptoService);
  private readonly credentialsApi = inject(CredentialsApiService);

  readonly identity$ = this.authService.userIdentity$;
  readonly token$ = this.authService.getAccessToken();
  readonly demoStatus = signal('Ready to verify a local zero-knowledge roundtrip.');
  readonly demoRunning = signal(false);

  async runCryptoDemo(): Promise<void> {
    const plainPassword = 'inventory-demo-password';
    const masterPassword = 'vault-master-passphrase';

    this.demoRunning.set(true);
    this.demoStatus.set('Encrypting locally...');

    try {
      const encrypted = await this.cryptoService.encrypt(plainPassword, masterPassword);
      const decrypted = await this.credentialsApi.decryptCredential(
        {
          id: 'demo',
          server_id: '00000000-0000-0000-0000-000000000000',
          credential_username: 'demo',
          cipher_text: arrayBufferToBase64(encrypted.cipherText),
          wrapped_dek: arrayBufferToBase64(encrypted.wrappedDek),
          iv: uint8ArrayToBase64(encrypted.iv),
          auth_tag: uint8ArrayToBase64(encrypted.authTag),
          pbkdf2_salt: uint8ArrayToBase64(encrypted.pbkdf2Salt),
          pbkdf2_iterations: encrypted.pbkdf2Iterations,
        },
        masterPassword,
      );

      this.demoStatus.set(
        decrypted === plainPassword
          ? 'Roundtrip verified: ciphertext decrypts back to the original secret.'
          : 'Roundtrip mismatch: the demo did not reconstruct the original secret.',
      );
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : 'Unknown error';
      this.demoStatus.set(`Demo failed: ${message}`);
    } finally {
      this.demoRunning.set(false);
    }
  }
}