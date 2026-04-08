import { Injectable, inject } from '@angular/core';
import { OidcSecurityService, type LoginResponse } from 'angular-auth-oidc-client';
import { Observable, distinctUntilChanged, map, shareReplay } from 'rxjs';

export interface UserIdentity {
  sub: string;
  preferredUsername: string;
  roles: readonly string[];
}

function normalizeRoles(value: unknown): readonly string[] {
  if (Array.isArray(value)) {
    return value.filter((entry): entry is string => typeof entry === 'string');
  }

  if (typeof value === 'string' && value.trim().length > 0) {
    return [value];
  }

  return [];
}

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly oidc = inject(OidcSecurityService);

  readonly isAuthenticated$: Observable<boolean> = this.oidc.isAuthenticated$.pipe(
    map((result) => result.isAuthenticated),
    distinctUntilChanged(),
    shareReplay({ bufferSize: 1, refCount: true }),
  );

  readonly userIdentity$: Observable<UserIdentity | null> = this.oidc.userData$.pipe(
    map(({ userData }) => this.toUserIdentity(userData)),
    shareReplay({ bufferSize: 1, refCount: true }),
  );

  readonly accessToken$: Observable<string> = this.oidc.getAccessToken().pipe(
    shareReplay({ bufferSize: 1, refCount: true }),
  );

  checkAuth(url: string = this.currentUrl()): Observable<LoginResponse> {
    return this.oidc.checkAuth(url);
  }

  login(): void {
    this.oidc.authorize();
  }

  logout(): void {
    void this.oidc.logoff().subscribe();
  }

  getAccessToken(): Observable<string> {
    return this.oidc.getAccessToken();
  }

  hasRole(role: string): Observable<boolean> {
    return this.userIdentity$.pipe(
      map((identity) => identity?.roles.includes(role) ?? false),
      distinctUntilChanged(),
    );
  }

  private toUserIdentity(userData: unknown): UserIdentity | null {
    if (!userData || typeof userData !== 'object') {
      return null;
    }

    const payload = userData as Record<string, unknown>;
    const sub = this.readString(payload, 'sub');
    const roles = this.readRoles(payload);

    if (!sub) {
      return null;
    }

    const preferredUsername = this.readString(payload, 'preferred_username') ?? sub;

    return {
      sub,
      preferredUsername,
      roles,
    };
  }

  private readString(payload: Record<string, unknown>, key: string): string | null {
    const value = payload[key];
    return typeof value === 'string' && value.trim().length > 0 ? value : null;
  }

  private readRoles(payload: Record<string, unknown>): readonly string[] {
    const directRoles = normalizeRoles(payload['realm_roles']);
    if (directRoles.length > 0) {
      return directRoles;
    }

    const realmAccess = payload['realm_access'];
    if (realmAccess && typeof realmAccess === 'object') {
      const nestedRoles = normalizeRoles(
        (realmAccess as Record<string, unknown>)['roles'],
      );
      if (nestedRoles.length > 0) {
        return nestedRoles;
      }
    }

    return [];
  }

  private currentUrl(): string {
    return typeof window !== 'undefined' ? window.location.href : '';
  }
}