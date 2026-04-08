import { AsyncPipe, CommonModule } from '@angular/common';
import { Component, OnInit, inject } from '@angular/core';
import { RouterLink, RouterOutlet } from '@angular/router';

import { AuthService } from './core/auth/auth.service';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, AsyncPipe, RouterLink, RouterOutlet],
  template: `
    <main class="shell">
      <header class="topbar">
        <div>
          <p class="eyebrow">Zero-Knowledge Inventory</p>
          <h1>Session-aware Angular shell.</h1>
        </div>

        <div class="status" *ngIf="isAuthenticated$ | async as isAuthenticated">
          <span class="status__dot" [class.status__dot--live]="isAuthenticated"></span>
          <span>{{ isAuthenticated ? 'Authenticated' : 'Guest session' }}</span>
        </div>
      </header>

      <section class="hero">
        <p class="lede">
          OIDC login, PKCE, session storage, Web Crypto, and guarded routes are
          wired into the shell. The backend only receives tokens and opaque bytes.
        </p>

        <div class="actions">
          <a routerLink="/vault" class="primary">Open vault</a>
          <a routerLink="/admin" class="secondary">Admin console</a>
          <button type="button" class="secondary" (click)="login()">Sign in</button>
          <button type="button" class="ghost" (click)="logout()">Sign out</button>
        </div>
      </section>

      <section class="rail" aria-label="Session summary">
        <article class="card">
          <span>OIDC</span>
          <strong>Code flow + refresh tokens</strong>
          <p>
            Keycloak realm integration is prewired with PKCE and session storage by
            default.
          </p>
        </article>

        <article class="card">
          <span>Crypto</span>
          <strong>Web Crypto only</strong>
          <p>
            AES-256-GCM, PBKDF2, and AES-KW live entirely in the browser runtime.
          </p>
        </article>

        <article class="card">
          <span>Transport</span>
          <strong>Bearer token interceptor</strong>
          <p>
            The HTTP interceptor attaches access tokens only to local API calls.
          </p>
        </article>
      </section>

      <section class="session" *ngIf="identity$ | async as identity; else guestState">
        <div class="session__label">Active identity</div>
        <div class="session__body">
          <strong>{{ identity.preferredUsername }}</strong>
          <span>{{ identity.sub }}</span>
          <div class="chips">
            <span class="chip" *ngFor="let role of identity.roles">{{ role }}</span>
          </div>
        </div>
      </section>

      <ng-template #guestState>
        <section class="session session--guest">
          <div class="session__label">Active identity</div>
          <div class="session__body">
            <strong>Not authenticated</strong>
            <span>The shell will process the OIDC callback automatically on load.</span>
          </div>
        </section>
      </ng-template>

      <router-outlet />
    </main>
  `,
  styles: [
    `
      :host {
        display: block;
        min-height: 100vh;
        position: relative;
      }

      .shell {
        min-height: 100vh;
        width: min(1120px, calc(100% - 2rem));
        margin: 0 auto;
        padding: clamp(1rem, 4vw, 3rem) 0 4rem;
      }

      .topbar {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 1rem;
        padding: 1.25rem 1.25rem 0;
      }

      .eyebrow {
        margin: 0 0 1rem;
        color: var(--accent);
        letter-spacing: 0.3em;
        text-transform: uppercase;
        font-size: 0.75rem;
      }

      h1 {
        margin: 0;
        color: var(--text);
        font-size: clamp(2.5rem, 7.2vw, 5rem);
        line-height: 0.92;
        max-width: 12ch;
      }

      .status {
        display: inline-flex;
        align-items: center;
        gap: 0.6rem;
        padding: 0.75rem 1rem;
        border-radius: 999px;
        border: 1px solid var(--border);
        background: rgba(7, 11, 24, 0.72);
        color: var(--muted);
        white-space: nowrap;
      }

      .status__dot {
        width: 0.65rem;
        height: 0.65rem;
        border-radius: 999px;
        background: rgba(148, 163, 184, 0.65);
        box-shadow: 0 0 0 6px rgba(148, 163, 184, 0.08);
      }

      .status__dot--live {
        background: var(--accent);
        box-shadow: 0 0 0 6px rgba(94, 234, 212, 0.12);
      }

      .hero {
        margin-top: 1.5rem;
        padding: 1.25rem;
        border: 1px solid var(--border);
        border-radius: 1.75rem;
        background: linear-gradient(180deg, rgba(13, 18, 35, 0.86), rgba(8, 12, 24, 0.94));
        box-shadow: 0 28px 90px rgba(2, 6, 23, 0.34);
      }

      .lede {
        max-width: 52rem;
        margin: 1.25rem 0 0;
        color: var(--muted);
        font-size: 1rem;
        line-height: 1.7;
      }

      .actions {
        display: flex;
        flex-wrap: wrap;
        gap: 0.75rem;
        margin-top: 1.5rem;
      }

      .primary,
      .secondary,
      .ghost {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-height: 2.9rem;
        padding: 0.75rem 1.05rem;
        border-radius: 999px;
        border: 1px solid transparent;
        text-decoration: none;
        cursor: pointer;
        font: inherit;
      }

      .primary {
        background: linear-gradient(135deg, rgba(94, 234, 212, 0.95), rgba(96, 165, 250, 0.95));
        color: #06101c;
        font-weight: 700;
      }

      .secondary {
        background: rgba(96, 165, 250, 0.12);
        border-color: rgba(96, 165, 250, 0.22);
        color: var(--text);
      }

      .ghost {
        background: transparent;
        border-color: rgba(148, 163, 184, 0.18);
        color: var(--muted);
      }

      .rail {
        margin-top: 1.5rem;
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 1rem;
      }

      .card {
        padding: 1.25rem;
        border: 1px solid var(--border);
        border-radius: 1.35rem;
        background: var(--panel);
        backdrop-filter: blur(18px);
        box-shadow: 0 20px 60px rgba(2, 6, 23, 0.35);
      }

      .card span {
        display: block;
        margin-bottom: 0.5rem;
        color: var(--accent-2);
        font-size: 0.78rem;
        letter-spacing: 0.18em;
        text-transform: uppercase;
      }

      .card strong {
        display: block;
        margin-bottom: 0.45rem;
        color: var(--text);
        font-size: 1.2rem;
      }

      .card p {
        margin: 0;
        color: var(--muted);
        line-height: 1.6;
      }

      .session {
        margin-top: 1rem;
        padding: 1rem 1.1rem;
        border-radius: 1.25rem;
        border: 1px solid rgba(94, 234, 212, 0.16);
        background: linear-gradient(180deg, rgba(6, 17, 24, 0.85), rgba(8, 12, 24, 0.95));
      }

      .session--guest {
        border-color: rgba(148, 163, 184, 0.16);
      }

      .session__label {
        color: var(--accent);
        text-transform: uppercase;
        letter-spacing: 0.2em;
        font-size: 0.72rem;
      }

      .session__body {
        margin-top: 0.6rem;
      }

      .session__body strong {
        display: block;
        font-size: 1.05rem;
      }

      .session__body span {
        color: var(--muted);
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
        background: rgba(94, 234, 212, 0.14);
        color: #a7f3d0;
        font-size: 0.78rem;
        letter-spacing: 0.08em;
      }

      @media (max-width: 800px) {
        .topbar {
          flex-direction: column;
        }

        .rail {
          grid-template-columns: 1fr;
        }

        .grid {
          grid-template-columns: 1fr;
        }
      }

      @media (max-width: 560px) {
        .shell {
          width: min(100% - 1rem, 1120px);
        }

        .hero,
        .card,
        .session {
          border-radius: 1rem;
        }
      }
    `,
  ],
})
export class AppComponent implements OnInit {
  private readonly authService = inject(AuthService);

  readonly isAuthenticated$ = this.authService.isAuthenticated$;
  readonly identity$ = this.authService.userIdentity$;

  ngOnInit(): void {
    if (this.hasOidcCallbackParams()) {
      void this.authService.checkAuth().subscribe({
        error: (error: unknown) => console.error(error),
      });
    }
  }

  login(): void {
    this.authService.login();
  }

  logout(): void {
    this.authService.logout();
  }

  private hasOidcCallbackParams(): boolean {
    if (typeof window === 'undefined') {
      return false;
    }

    const query = window.location.search;
    return (
      query.includes('code=') ||
      query.includes('state=') ||
      query.includes('error=') ||
      query.includes('session_state=')
    );
  }
}
