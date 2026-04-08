import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { map, take } from 'rxjs';

import { AuthService } from './auth.service';

export const authGuard: CanActivateFn = () => {
  const authService = inject(AuthService);

  return authService.isAuthenticated$.pipe(
    take(1),
    map((isAuthenticated) => {
      if (!isAuthenticated) {
        authService.login();
        return false;
      }

      return true;
    }),
  );
};

export function roleGuard(...allowedRoles: string[]): CanActivateFn {
  return () => {
    const authService = inject(AuthService);
    const router = inject(Router);

    return authService.userIdentity$.pipe(
      take(1),
      map((identity) => {
        if (!identity) {
          authService.login();
          return false;
        }

        const hasRole = identity.roles.some((role) => allowedRoles.includes(role));
        if (!hasRole) {
          void router.navigate(['/unauthorized']);
          return false;
        }

        return true;
      }),
    );
  };
}