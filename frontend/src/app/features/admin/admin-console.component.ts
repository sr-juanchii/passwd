import { AsyncPipe, CommonModule } from '@angular/common';
import { Component, inject } from '@angular/core';
import { RouterLink } from '@angular/router';

import { AuthService } from '../../core/auth/auth.service';

@Component({
  selector: 'app-admin-console',
  standalone: true,
  imports: [CommonModule, AsyncPipe, RouterLink],
  template: `
    <section class="panel panel--admin">
      <div class="panel__eyebrow">ADMIN role required</div>
      <h2>Admin console</h2>
      <p>
        This route is protected by a role guard. It is the surface where elevated
        inventory operations will later be added.
      </p>

      <div class="identity" *ngIf="identity$ | async as identity">
        <span>{{ identity.preferredUsername }}</span>
        <div class="chips">
          <span class="chip" *ngFor="let role of identity.roles">{{ role }}</span>
        </div>
      </div>

      <div class="actions">
        <a routerLink="/vault" class="ghost">Back to vault</a>
        <a routerLink="/" class="ghost ghost--soft">Back to shell</a>
      </div>
    </section>
  `,
  styles: [
    `
      .panel {
        margin-top: 1.5rem;
        padding: 1.5rem;
        border-radius: 1.5rem;
        border: 1px solid rgba(245, 158, 11, 0.22);
        background: linear-gradient(180deg, rgba(28, 18, 10, 0.9), rgba(10, 8, 6, 0.96));
      }

      .panel--admin {
        box-shadow: 0 24px 80px rgba(91, 33, 6, 0.22);
      }

      .panel__eyebrow {
        color: var(--accent-3);
        text-transform: uppercase;
        letter-spacing: 0.24em;
        font-size: 0.72rem;
      }

      h2 {
        margin: 0.75rem 0 0;
        font-size: 1.6rem;
      }

      p {
        margin: 0.75rem 0 0;
        color: var(--muted);
        line-height: 1.7;
      }

      .identity {
        margin-top: 1rem;
        padding: 1rem;
        border-radius: 1rem;
        background: rgba(245, 158, 11, 0.08);
        border: 1px solid rgba(245, 158, 11, 0.16);
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
        background: rgba(245, 158, 11, 0.16);
        color: #fde68a;
        font-size: 0.78rem;
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
        color: #fde68a;
        background: rgba(245, 158, 11, 0.12);
      }
    `,
  ],
})
export class AdminConsoleComponent {
  private readonly authService = inject(AuthService);

  readonly identity$ = this.authService.userIdentity$;
}