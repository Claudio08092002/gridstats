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
  private readonly apiBase = this.resolveApiBase(environment.apiBase);

  constructor(private http: HttpClient) {}

  private resolveApiBase(rawBase: string): string {
    if (!rawBase) {
      return '';
    }

    if (rawBase.startsWith('http://')) {
      // Avoid mixed content when the UI runs over HTTPS.
      try {
        if (typeof window !== 'undefined' && window.location.protocol === 'https:') {
          return 'https://' + rawBase.replace(/^https?:\/\//, '');
        }
      } catch {
        // SSR or other non-browser environments; fall back to the provided base.
      }
    }

    return rawBase;
  }

  private buildUrl(path: string): string {
    if (!this.apiBase) {
      return path;
    }
    if (path.startsWith('/')) {
      return `${this.apiBase}${path}`;
    }
    return `${this.apiBase}/${path}`;
  }

  loadSeason(year: number, refresh: boolean = false) {
    const suffix = refresh ? '?refresh=true' : '';
    const url = this.buildUrl(`/f1/season/${year}${suffix}`);
    return this.http.get<SeasonResponse>(url);
  }

  getTracks() {
    return this.http.get<TrackInfo[]>(this.buildUrl('/f1/tracks'));
  }

  getTrackMap(year: number, round: number) {
    return this.http.get<TrackMapResponse>(this.buildUrl(`/f1/trackmap/${year}/${round}`));
  }
}
