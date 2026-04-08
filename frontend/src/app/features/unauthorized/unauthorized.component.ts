import { Component } from '@angular/core';
import { RouterLink } from '@angular/router';

@Component({
  selector: 'app-unauthorized',
  standalone: true,
  imports: [RouterLink],
  template: `
    <section class="panel">
      <div class="panel__eyebrow">Access denied</div>
      <h2>Unauthorized</h2>
      <p>
        The current identity does not have permission to open this section. Go
        back to the shell or authenticate with a role that matches the route.
      </p>

      <a routerLink="/" class="ghost">Return to shell</a>
    </section>
  `,
  styles: [
    `
      .panel {
        margin-top: 1.5rem;
        padding: 1.5rem;
        border-radius: 1.5rem;
        border: 1px solid rgba(239, 68, 68, 0.22);
        background: linear-gradient(180deg, rgba(34, 11, 11, 0.9), rgba(9, 5, 6, 0.96));
      }

      .panel__eyebrow {
        color: #fca5a5;
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

      .ghost {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-height: 2.75rem;
        margin-top: 1rem;
        padding: 0.65rem 1rem;
        border-radius: 999px;
        border: 1px solid rgba(148, 163, 184, 0.18);
        color: #fecaca;
        text-decoration: none;
      }
    `,
  ],
})
export class UnauthorizedComponent {}