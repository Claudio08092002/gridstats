import { RenderMode, ServerRoute } from '@angular/ssr';

export const serverRoutes: ServerRoute[] = [
  // Dynamic route: do not prerender with params
  {
    path: 'race/:year/:round',
    renderMode: RenderMode.Server,
  },
  {
    path: 'race/:year/:round/driver/:code',
    renderMode: RenderMode.Server,
  },
  // Default: prerender other static routes
  {
    path: '**',
    renderMode: RenderMode.Prerender,
  },
];
