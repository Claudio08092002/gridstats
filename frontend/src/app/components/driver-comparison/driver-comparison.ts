import {
  Component, ViewChild, ElementRef, OnDestroy, inject
} from '@angular/core';
import { CommonModule, isPlatformBrowser } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { PLATFORM_ID } from '@angular/core';
import { ApiService, SeasonResponse, DriverSummary } from '../../services/api';

import { Chart, registerables, ChartConfiguration } from 'chart.js';
Chart.register(...registerables);

@Component({
  selector: 'app-driver-comparison',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './driver-comparison.html',
  styleUrls: ['./driver-comparison.css'],
})
export class DriverComparison implements OnDestroy {
  @ViewChild('chartCanvas', { static: true }) chartCanvas!: ElementRef<HTMLCanvasElement>;
  chart?: Chart;

  private platformId = inject(PLATFORM_ID);
  private isBrowser = isPlatformBrowser(this.platformId);
  private api = inject(ApiService);

  currentYear = new Date().getFullYear();
  loading = false;
  errorMsg: string | null = null;

  seasons = Array.from({ length: 2025 - 2018 + 1 }, (_, i) => 2018 + i);
  season: number | null = null;

  driverKeys: string[] = [];
  driverMap: Record<string, DriverSummary> = {};

  driver1: string | null = null;
  driver2: string | null = null;

  color1 = '#6ea8fe';
  color2 = '#f778ba';

  ngOnDestroy(): void {
    this.chart?.destroy();
  }

  onSeasonChange(): void {
    console.log('ddsdsadasd');
    if (!this.season) return;
    this.loading = true;
    this.errorMsg = null;
    this.driverKeys = [];
    this.driverMap = {};
    this.driver1 = null;
    this.driver2 = null;
    this.chart?.destroy();

    this.api.loadSeason(this.season).subscribe({
      next: (resp: SeasonResponse) => {
        this.loading = false;
        this.driverMap = resp.drivers;
        this.driverKeys = Object.keys(resp.drivers).sort();
      },
      error: (err) => {
        this.loading = false;
        this.errorMsg = err?.error?.detail ?? err.message ?? 'Fehler';
      },
    });
  }

  onCompare(): void {
    if (!this.driver1 || !this.driver2) return;
    if (this.driver1 === this.driver2) {
      alert('Bitte zwei verschiedene Fahrer waehlen.');
      return;
    }
    const d1 = this.driverMap[this.driver1];
    const d2 = this.driverMap[this.driver2];
    if (!d1 || !d2) return;

    const labels = ['Punkte', 'Siege', 'Poles', 'Podien', 'Ø Ziel'];
    const d1Data = [d1.total_points, d1.wins, d1.poles, d1.podiums, d1.avg_finish ?? 0];
    const d2Data = [d2.total_points, d2.wins, d2.poles, d2.podiums, d2.avg_finish ?? 0];
    console.log(d1.team, d1.name, d1.total_points)
    console.log(d1, d2)
    console.log(d1Data, d2)    
    this.chart?.destroy();
    const cfg: ChartConfiguration<'bar'> = {
      type: 'bar',
      data: {
        labels,
        datasets: [
          { label: `${d1.name} (${this.driver1})`, data: d1Data, backgroundColor: this.color1 },
          { label: `${d2.name} (${this.driver2})`, data: d2Data, backgroundColor: this.color2 },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: { grid: { color: 'rgba(255,255,255,0.06)' } },
          y: { beginAtZero: true, grid: { color: 'rgba(255,255,255,0.06)' } },
        },
      },
    };
    if (this.isBrowser) {
      this.chart = new Chart(this.chartCanvas.nativeElement.getContext('2d')!, cfg);
    }
  }
}
