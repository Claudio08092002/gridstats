// frontend/src/app/services/api.ts
import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
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

export interface ConstructorSummary {
  name: string;
  team_color: string;
  total_points: number;
  wins: number;
  podiums: number;
  poles: number;
  season_count: number;
  seasons: number[];
  total_drivers: number;
  drivers: string[];
  drivers_by_year: Record<string, string[]>;
  origin: string | null;
  points_by_year: Record<string, number>;
  wins_by_year: Record<string, number>;
  podiums_by_year: Record<string, number>;
  standings_by_year: Record<string, number>;
  best_result: {
    year: number;
    round: number;
    event: string;
    points: number;
    drivers: Array<{name: string; points: number; position: any}>;
  } | null;
}

export interface ConstructorListResponse {
  constructors: Record<string, ConstructorSummary>;
  years: number[];
  version?: string;
}

export interface ConstructorComparisonResponse {
  constructor1: ConstructorSummary;
  constructor2: ConstructorSummary;
  years: number[];
}

export interface TrackRoundRef {
  year: number;
  round: number;
  event_name: string;
}

export interface TrackInfo {
  key: string;
  name: string;
  display_name: string;
  country?: string;
  country_code?: string | null;
  location?: string;
  latest_year: number;
  latest_round: number;
  years: number[];
  rounds: TrackRoundRef[];
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
  team_color?: string;
}

export interface TrackLayoutVariant {
  layout_signature: string;
  layout_label?: string;
  layout_length?: number | null;
  circuit_name?: string;
  years: number[];
  rounds: TrackRoundRef[];
}

export interface TrackMapResponse {
  track: TrackPoint[];
  corners: TrackCorner[];
  layout_length?: number | null;
  layout_label?: string;
  layout_signature?: string;
  circuit_name?: string;
  winners?: RaceWinnerInfo[];
  winner?: RaceWinnerInfo | null;
  layout_variants?: TrackLayoutVariant[];
  layout_years?: number[];
}

// Race stats API types
export interface RaceEventInfo {
  name?: string | null;
  location?: string | null;
  country?: string | null;
  date?: string | null; // ISO string
  source?: string | null; // fastf1/ergast/...
}

export interface RaceMetaInfo {
  total_laps: number;
  duration_ms: number | null;
  retirements: number;
  fastest_lap?: { driver?: string | null; lap?: number | null; lap_time_ms?: number | null } | null;
}

export interface RaceClassificationEntry {
  position: number | null;
  driver: string | null; // abbreviation
  team: string | null;
  grid: number | null;
  grid_delta: number | null;
  time: string | null;
  status: string | null;
  status_simple?: string | null;
  points: number;
  dnf: boolean;
  team_color?: string | null;
}

export interface PositionLapPoint { lap: number; position: number; }
export interface PositionSeries { driver: string; team?: string | null; team_color?: string | null; laps: PositionLapPoint[] }

export interface TeamPaceItem { team: string; team_color?: string | null; median_ms: number | null; p25_ms: number | null; count: number }

export interface TeamBoxItem {
  team: string;
  team_color?: string | null;
  min_ms: number | null;
  q1_ms: number | null;
  median_ms: number | null;
  q3_ms: number | null;
  max_ms: number | null;
  count: number;
}

export interface RaceOverviewResponse {
  year: number;
  round: number;
  event: RaceEventInfo;
  meta: RaceMetaInfo;
  classification: RaceClassificationEntry[];
  position_by_lap: { drivers: PositionSeries[] };
  team_pace: TeamPaceItem[];
  team_box?: TeamBoxItem[];
}

// Driver race details
export interface DriverRaceDetails {
  year: number;
  round: number;
  driver: string; // code
  team?: string | null;
  team_color?: string | null;
  grid?: number | null;
  finish?: number | null;
  status?: string | null;
  pits: Array<{ lap: number; pit_in_time_ms: number | null; pit_out_time_ms: number | null; duration_ms: number | null }>;
  stints: Array<{ stint: number | null; start_lap: number; end_lap: number; length: number; compound?: string | null; fresh?: boolean | null; tyre_life_start?: number | null }>;
  laps: Array<{ lap: number; lap_time_ms: number | null; position: number | null; compound?: string | null; tyre_life?: number | null; pit_in?: boolean; pit_out?: boolean; is_accurate?: boolean }>;
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

  getTracks(refresh: boolean = false) {
    const suffix = refresh ? '?refresh=true' : '';
    return this.http.get<TrackInfo[]>(this.buildUrl(`/f1/tracks${suffix}`));
  }

  getTrackMap(
    year: number,
    round: number,
    options: { includeLayouts?: boolean; refresh?: boolean } = {}
  ) {
    let params = new HttpParams();
    if (options.refresh) {
      params = params.set('refresh', 'true');
    }
    if (options.includeLayouts === false) {
      params = params.set('include_layouts', 'false');
    }
    return this.http.get<TrackMapResponse>(this.buildUrl(`/f1/trackmap/${year}/${round}`), {
      params,
    });
  }

  getConstructors(refresh: boolean = false) {
    const suffix = refresh ? '?refresh=true' : '';
    return this.http.get<ConstructorListResponse>(this.buildUrl(`/f1/constructors${suffix}`));
  }

  compareConstructors(constructor1: string, constructor2: string, refresh: boolean = false) {
    let params = new HttpParams()
      .set('constructor1', constructor1)
      .set('constructor2', constructor2);
    if (refresh) {
      params = params.set('refresh', 'true');
    }
    return this.http.get<ConstructorComparisonResponse>(this.buildUrl('/f1/constructors/compare'), {
      params,
    });
  }

  getRaceOverview(year: number, round: number) {
    return this.http.get<RaceOverviewResponse>(this.buildUrl(`/f1/race/${year}/${round}`));
  }

  getDriverRace(year: number, round: number, code: string) {
    return this.http.get<DriverRaceDetails>(this.buildUrl(`/f1/race/${year}/${round}/driver/${code}`));
  }
}
