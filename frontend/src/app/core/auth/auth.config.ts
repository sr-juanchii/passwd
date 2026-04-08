import { LogLevel, PassedInitialConfig } from 'angular-auth-oidc-client';

const appOrigin = typeof window !== 'undefined' ? window.location.origin : 'http://localhost:4200';

export const authConfig: PassedInitialConfig = {
  config: {
    configId: 'inventory-spa',
    authority: 'http://localhost:8080/realms/inventory',
    authWellknownEndpointUrl: '/assets/mock-openid-configuration.json',
    redirectUrl: appOrigin,
    postLogoutRedirectUri: appOrigin,
    postLoginRoute: '/',
    clientId: 'inventory-spa',
    scope: 'openid profile email',
    responseType: 'code',
    silentRenew: true,
    useRefreshToken: true,
    renewTimeBeforeTokenExpiresInSeconds: 30,
    tokenRefreshInSeconds: 4,
    secureRoutes: ['http://localhost:8000/api/'],
    logLevel: LogLevel.None,
  },
};