import { bootstrapApplication } from '@angular/platform-browser';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { provideRouter } from '@angular/router';
import { provideAuth } from 'angular-auth-oidc-client';

import { AppComponent } from './app/app.component';
import { authConfig } from './app/core/auth/auth.config';
import { authInterceptor } from './app/core/auth/auth.interceptor';
import { appRoutes } from './app/app.routes';


bootstrapApplication(AppComponent, {
  providers: [
    provideRouter(appRoutes),
    provideHttpClient(withInterceptors([authInterceptor])),
    provideAuth(authConfig),
  ],
}).catch((error: unknown) => {
  console.error(error);
});
