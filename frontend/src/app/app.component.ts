import { Component } from '@angular/core';

@Component({
  selector: 'app-root',
  standalone: true,
  template: `
    <main class="shell">
      <section class="hero">
        <p class="eyebrow">Zero-Knowledge Inventory</p>
        <h1>Infrastructure baseline ready.</h1>
        <p class="lede">
          The foundation is in place: isolated services, strict transport, and a
          security-first delivery pipeline.
        </p>
      </section>

      <section class="grid" aria-label="Phase zero controls">
        <article class="card">
          <span>Backend</span>
          <strong>FastAPI scaffold</strong>
          <p>Settings, structured logging, and database session plumbing.</p>
        </article>

        <article class="card">
          <span>Infrastructure</span>
          <strong>Docker Compose</strong>
          <p>MySQL, Keycloak, backend, and frontend on segmented networks.</p>
        </article>

        <article class="card">
          <span>Delivery</span>
          <strong>Security pipeline</strong>
          <p>Static analysis, dependency scanning, and container checks.</p>
        </article>
      </section>
    </main>
  `,
  styles: [
    `
      :host {
        display: block;
        min-height: 100vh;
      }

      .shell {
        min-height: 100vh;
        display: grid;
        place-items: center;
        padding: clamp(1.5rem, 4vw, 4rem);
      }

      .hero {
        max-width: 56rem;
        text-align: center;
      }

      .eyebrow {
        margin: 0 0 1rem;
        color: #67e8f9;
        letter-spacing: 0.35em;
        text-transform: uppercase;
        font-size: 0.75rem;
      }

      h1 {
        margin: 0;
        color: #f8fafc;
        font-size: clamp(2.6rem, 8vw, 5.5rem);
        line-height: 0.95;
      }

      .lede {
        max-width: 42rem;
        margin: 1.5rem auto 0;
        color: #cbd5e1;
        font-size: 1.05rem;
        line-height: 1.7;
      }

      .grid {
        width: min(100%, 64rem);
        margin-top: 3rem;
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 1rem;
      }

      .card {
        padding: 1.25rem;
        border: 1px solid rgba(148, 163, 184, 0.18);
        border-radius: 1.25rem;
        background: rgba(15, 23, 42, 0.55);
        backdrop-filter: blur(18px);
        box-shadow: 0 20px 60px rgba(2, 6, 23, 0.35);
      }

      .card span {
        display: block;
        margin-bottom: 0.5rem;
        color: #38bdf8;
        font-size: 0.78rem;
        letter-spacing: 0.2em;
        text-transform: uppercase;
      }

      .card strong {
        display: block;
        margin-bottom: 0.45rem;
        color: #f8fafc;
        font-size: 1.2rem;
      }

      .card p {
        margin: 0;
        color: #cbd5e1;
        line-height: 1.6;
      }

      @media (max-width: 800px) {
        .grid {
          grid-template-columns: 1fr;
        }
      }
    `,
  ],
})
export class AppComponent {}
