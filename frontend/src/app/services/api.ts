import { inject, Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { environment } from '../../enviroments/enviroments';

@Injectable({ providedIn: 'root' })
export class ApiService {
  private http = inject(HttpClient);
  private base = environment.apiBase;

  getDrivers() {
    return this.http.get<{id:string; name:string}[]>(`${this.base}/drivers`);
  }

  getRaceResults(year: number, round: number) {
    return this.http.get(`${this.base}/f1/race/${year}/${round}`);
  }
}
