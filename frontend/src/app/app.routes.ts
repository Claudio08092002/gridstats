import { Routes } from '@angular/router';
import { DriverComparison } from './components/driver-comparison/driver-comparison';

export const routes: Routes = [
    { path: 'driver-comparison', component: DriverComparison },
    { path: '', redirectTo: 'driver-comparison', pathMatch: 'full' }

];
