import { Routes } from '@angular/router';

import { authGuard, roleGuard } from './core/auth/auth.guard';
import { AdminConsoleComponent } from './features/admin/admin-console.component';
import { UnauthorizedComponent } from './features/unauthorized/unauthorized.component';
import { VaultComponent } from './features/vault/vault.component';

export const appRoutes: Routes = [
  {
    path: 'vault',
    component: VaultComponent,
    canActivate: [authGuard],
    title: 'Vault',
  },
  {
    path: 'admin',
    component: AdminConsoleComponent,
    canActivate: [authGuard, roleGuard('ADMIN')],
    title: 'Admin Console',
  },
  {
    path: 'unauthorized',
    component: UnauthorizedComponent,
    title: 'Unauthorized',
  },
  {
    path: '**',
    redirectTo: '',
  },
];