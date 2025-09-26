// frontend/src/app/services/api.ts
import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { environment } from '../../enviroments/enviroments';

export interface DriverSummary {
  full_name: string;
  code: string;
  team: string;
  team_color: string;
  total_points: number;
  wins: number;
  podiums: number;
  dnfs: number;
  avg_finish: number | null;
  poles: number;
  pole_rounds: number[];
}


export interface SeasonResponse {
  season: number;
  drivers: Record<string, DriverSummary>;
}

@Injectable({ providedIn: 'root' })
export class ApiService {
  constructor(private http: HttpClient) {}

  loadSeason(year: number, refresh: boolean = false) {
    const url = `${environment.apiBase}/f1/season/${year}` + (refresh ? `?refresh=true` : ``);
    return this.http.get<SeasonResponse>(url);
  }
}
