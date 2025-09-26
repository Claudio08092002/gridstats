import { Routes } from '@angular/router';
import { DriverComparison } from './components/driver-comparison/driver-comparison';
import { TrackComponent } from './components/track/track';

export const routes: Routes = [
    { path: 'driver-comparison', component: DriverComparison },
    { path: 'track', component: TrackComponent },
    { path: '', redirectTo: 'driver-comparison', pathMatch: 'full' }

];
