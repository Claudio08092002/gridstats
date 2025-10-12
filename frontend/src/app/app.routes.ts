import { Routes } from '@angular/router';
import { DriverComparison } from './components/driver-comparison/driver-comparison';
import { TrackComponent } from './components/track/track';
import { ConstructorComponent } from './components/constructor/constructor';
import { RaceStatsComponent } from './components/race-stats/race-stats';
import { DriverRaceComponent } from './components/driver-race/driver-race';

export const routes: Routes = [
    { path: 'driver-comparison', component: DriverComparison },
    { path: 'track', component: TrackComponent },
    { path: 'constructor', component: ConstructorComponent },
    { path: 'race/:year/:round', component: RaceStatsComponent },
    { path: 'race/:year/:round/driver/:code', component: DriverRaceComponent },
    { path: '', redirectTo: 'driver-comparison', pathMatch: 'full' }

];
