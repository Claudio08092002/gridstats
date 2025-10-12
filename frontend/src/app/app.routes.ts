import { Routes } from '@angular/router';

export const routes: Routes = [
  {
    path: 'driver-comparison',
    loadComponent: () =>
      import('./components/driver-comparison/driver-comparison').then(
        (m) => m.DriverComparison,
      ),
  },
  {
    path: 'track',
    loadComponent: () =>
      import('./components/track/track').then((m) => m.TrackComponent),
  },
  {
    path: 'constructor',
    loadComponent: () =>
      import('./components/constructor/constructor').then(
        (m) => m.ConstructorComponent,
      ),
  },
  {
    path: 'race/:year/:round',
    loadComponent: () =>
      import('./components/race-stats/race-stats').then(
        (m) => m.RaceStatsComponent,
      ),
  },
  {
    path: 'race/:year/:round/driver/:code',
    loadComponent: () =>
      import('./components/driver-race/driver-race').then(
        (m) => m.DriverRaceComponent,
      ),
  },
  { path: '', redirectTo: 'driver-comparison', pathMatch: 'full' },
];
