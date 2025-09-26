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

// Track listing and map types
export interface TrackInfo {
  key: string;
  name: string;
  year: number;
  round: number;
  country?: string;
  location?: string;
}

export interface TrackPoint {
  x: number;
  y: number;
  z?: number;
  distance: number;
}

export interface TrackCorner {
  corner_number: string;
  track_position: [number, number];
  text_position: [number, number];
  corner_name?: string;
  distanceFromStart?: number;
}

export interface RaceWinnerInfo {
  year: number;
  round: number;
  driver: string;
  team: string;
  code?: string;
  event?: string;
}

export interface TrackMapResponse {
  track: TrackPoint[];
  corners: TrackCorner[];
  winner?: RaceWinnerInfo | null;
}

@Injectable({ providedIn: 'root' })
export class ApiService {
  constructor(private http: HttpClient) {}

  loadSeason(year: number, refresh: boolean = false) {
    const url = `${environment.apiBase}/f1/season/${year}` + (refresh ? `?refresh=true` : ``);
    return this.http.get<SeasonResponse>(url);
  }

  getTracks() {
    const url = `${environment.apiBase}/f1/tracks`;
    return this.http.get<TrackInfo[]>(url);
  }

  getTrackMap(year: number, round: number) {
    const url = `${environment.apiBase}/f1/trackmap/${year}/${round}`;
    return this.http.get<TrackMapResponse>(url);
  }
}
