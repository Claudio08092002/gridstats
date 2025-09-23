// frontend/src/app/services/api.ts
import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../enviroments/enviroments';

export interface DriverSummary {
  name: string;
  team: string | null;
  total_points: number;
  wins: number;
  podiums: number;
  dnfs: number;
  avg_finish: number | null;
  poles: number;
}

export interface SeasonResponse {
  season: number;
  drivers: Record<string, DriverSummary>;
}

@Injectable({ providedIn: 'root' })
export class ApiService {
  constructor(private http: HttpClient) {}

loadSeason(year: number) {
  return this.http.get<SeasonResponse>(`${environment.apiBase}/f1/season/${year}`);
}

}
