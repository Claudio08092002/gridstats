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
  // WICHTIG: static:false, weil die Canvas erst nach *ngIf ins DOM kommen
  @ViewChild('chartCanvas',   { static: false }) chartCanvas?: ElementRef<HTMLCanvasElement>;
  @ViewChild('pointsChart',   { static: false }) pointsChart?: ElementRef<HTMLCanvasElement>;
  @ViewChild('winsChart',     { static: false }) winsChart?: ElementRef<HTMLCanvasElement>;
  @ViewChild('podiumsChart',  { static: false }) podiumsChart?: ElementRef<HTMLCanvasElement>;
  @ViewChild('polesChart',    { static: false }) polesChart?: ElementRef<HTMLCanvasElement>;
  @ViewChild('avgChart',      { static: false }) avgChart?: ElementRef<HTMLCanvasElement>;
  @ViewChild('dnfsChart',    { static: false }) dnfsChart?: ElementRef<HTMLCanvasElement>;


  private platformId = inject(PLATFORM_ID);
  private isBrowser = isPlatformBrowser(this.platformId);
  private api = inject(ApiService);

  private extraCharts: Chart[] = [];
  chart?: Chart;

  currentYear = new Date().getFullYear();
  loading = false;
  errorMsg: string | null = null;

  seasons = Array.from({ length: 2025 - 2018 + 1 }, (_, i) => 2018 + i);
  season: number | null = null;

  driverKeys: string[] = [];
  driverMap: Record<string, DriverSummary> = {};

  driver1: string | null = null;
  driver2: string | null = null;

  compared = false;

  private readonly neutralColors = ['#cbd5f5', '#64748b'];
  color1 = this.neutralColors[0];
  color2 = this.neutralColors[1];

  ngOnDestroy(): void {
    this.chart?.destroy();
    this.destroyExtraCharts();
  }

  private destroyExtraCharts() {
    this.extraCharts.forEach(c => c.destroy());
    this.extraCharts = [];
  }

  onSeasonChange(): void {
    if (!this.season) return;
    this.loading = true;
    this.errorMsg = null;
    this.driverKeys = [];
    this.driverMap = {};
    this.driver1 = null;
    this.driver2 = null;
    this.compared = false;

    this.chart?.destroy();
    this.destroyExtraCharts();

    this.api.loadSeason(this.season).subscribe({
      next: (resp: SeasonResponse) => {
        this.loading = false;
        this.driverMap = resp.drivers ?? {};
        this.driverKeys = Object.keys(this.driverMap).sort();
        console.log('Loaded drivers:', this.driverKeys);
        console.log(this.driverMap);

        // If backend served an empty cached season, try once with refresh=true to rebuild
        if (this.driverKeys.length === 0) {
          this.loading = true;
          this.api.loadSeason(this.season!, true).subscribe({
            next: (fresh: SeasonResponse) => {
              this.loading = false;
              this.driverMap = fresh.drivers ?? {};
              this.driverKeys = Object.keys(this.driverMap).sort();
            },
            error: (err) => {
              this.loading = false;
              this.errorMsg = err?.error?.detail ?? err.message ?? 'Fehler';
            },
          });
        }
      },
      error: (err) => {
        this.loading = false;
        this.errorMsg = err?.error?.detail ?? err.message ?? 'Fehler';
      },
    });
  }

  private chartOptionsCompact(): ChartConfiguration<'bar'>['options'] {
    return {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: {
          grid: { color: 'rgba(255,255,255,0.06)' },
          ticks: { maxRotation: 0, autoSkip: true },
        },
        y: {
          beginAtZero: true,
          grid: { color: 'rgba(255,255,255,0.06)' },
        },
      },
      plugins: {
        legend: { labels: { boxWidth: 12 } },
      },
    };
  }

  private normalizeHex(hex?: string | null): string | null {
    if (!hex) return null;
    let value = hex.trim();
    if (!value) return null;
    if (!value.startsWith('#')) {
      value = `#${value}`;
    }
    if (value.length === 4) {
      value = `#${value[1]}${value[1]}${value[2]}${value[2]}${value[3]}${value[3]}`;
    }
    return value.length === 7 ? value.toUpperCase() : null;
  }

  private adjustColor(hex: string, amount: number): string {
    const normalized = this.normalizeHex(hex) ?? this.neutralColors[0];
    const r = parseInt(normalized.slice(1, 3), 16);
    const g = parseInt(normalized.slice(3, 5), 16);
    const b = parseInt(normalized.slice(5, 7), 16);
    const adjust = (channel: number) => {
      if (amount >= 0) {
        return Math.min(255, Math.round(channel + (255 - channel) * amount));
      }
      return Math.max(0, Math.round(channel * (1 + amount)));
    };
    const r2 = adjust(r);
    const g2 = adjust(g);
    const b2 = adjust(b);
    return `#${r2.toString(16).padStart(2, '0')}${g2.toString(16).padStart(2, '0')}${b2.toString(16).padStart(2, '0')}`.toUpperCase();
  }

  private deriveDriverColors(d1: DriverSummary, d2: DriverSummary) {
    const colorOne = this.normalizeHex(d1.team_color);
    const colorTwo = this.normalizeHex(d2.team_color);
    const sameTeam = d1.team && d2.team && d1.team === d2.team;

    if (sameTeam && colorOne) {
      this.color1 = this.adjustColor(colorOne, 0.25);
      this.color2 = this.adjustColor(colorOne, -0.2);
      return;
    }

    if (colorOne && colorTwo) {
      this.color1 = colorOne;
      this.color2 = colorTwo !== colorOne ? colorTwo : this.adjustColor(colorTwo, -0.25);
      return;
    }

    if (colorOne) {
      this.color1 = colorOne;
      this.color2 = this.adjustColor(colorOne, -0.3);
      return;
    }

    if (colorTwo) {
      this.color2 = colorTwo;
      this.color1 = this.adjustColor(colorTwo, 0.3);
      return;
    }

    [this.color1, this.color2] = this.neutralColors;
  }

  private makeBar(ctx: CanvasRenderingContext2D, title: string, d1: number, d2: number, label1: string, label2: string) {
    const cfg: ChartConfiguration<'bar'> = {
      type: 'bar',
      data: {
        labels: [title],
        datasets: [
          {
            label: label1,
            data: [Number(d1 ?? 0)],
            backgroundColor: this.color1,
            barPercentage: 0.55,
            categoryPercentage: 0.55,
          },
          {
            label: label2,
            data: [Number(d2 ?? 0)],
            backgroundColor: this.color2,
            barPercentage: 0.55,
            categoryPercentage: 0.55,
          },
        ],
      },
      options: this.chartOptionsCompact(),
    };
    const c = new Chart(ctx, cfg);
    this.extraCharts.push(c);
  }

  private getCtx(ref?: ElementRef<HTMLCanvasElement>): CanvasRenderingContext2D | null {
    return ref?.nativeElement?.getContext('2d') ?? null;
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

  this.deriveDriverColors(d1, d2);

    const labels = ['Punkte', 'Siege', 'Poles', 'Podien', 'Ø Ziel'];
    const d1Data = [d1.total_points, d1.wins, d1.poles, d1.podiums, d1.avg_finish ?? 0] as number[];
    const d2Data = [d2.total_points, d2.wins, d2.poles, d2.podiums, d2.avg_finish ?? 0] as number[];

    // UI zeigen
    this.compared = true;

    // Charts erst IM NÄCHSTEN TICK erstellen, wenn die Canvas da sind
    // (Alternativ: NgZone.onStable oder ChangeDetectorRef.detectChanges() + setTimeout)
    setTimeout(() => {
      // Gesamt-Chart neu zeichnen
      this.chart?.destroy();
      const ctxMain = this.getCtx(this.chartCanvas);
      if (this.isBrowser && ctxMain) {
        const d1Label = d1.full_name;
        const d2Label = d2.full_name;
        const cfg: ChartConfiguration<'bar'> = {
          type: 'bar',
          data: {
            labels,
            datasets: [
              {
                label: `${d1Label} (${this.driver1})`,
                data: d1Data,
                backgroundColor: this.color1,
                barPercentage: 0.5,
                categoryPercentage: 0.5,
              },
              {
                label: `${d2Label} (${this.driver2})`,
                data: d2Data,
                backgroundColor: this.color2,
                barPercentage: 0.5,
                categoryPercentage: 0.5,
              },
            ],
          },
          options: this.chartOptionsCompact(),
        };
        this.chart = new Chart(ctxMain, cfg);
      }

      // Einzel-Charts
      this.destroyExtraCharts();
      if (!this.isBrowser) return;

      const ctxPoints  = this.getCtx(this.pointsChart);
      const ctxWins    = this.getCtx(this.winsChart);
      const ctxPodiums = this.getCtx(this.podiumsChart);
      const ctxPoles   = this.getCtx(this.polesChart);
      const ctxAvg     = this.getCtx(this.avgChart);
      const ctxDnfs   = this.getCtx(this.dnfsChart);


      if (ctxPoints)  this.makeBar(ctxPoints,  'Punkte', d1.total_points,    d2.total_points, d1.code, d2.code);
      if (ctxWins)    this.makeBar(ctxWins,    'Siege',  d1.wins,            d2.wins,        d1.code, d2.code);
      if (ctxPodiums) this.makeBar(ctxPodiums, 'Podien', d1.podiums,         d2.podiums,     d1.code, d2.code);
      if (ctxPoles)   this.makeBar(ctxPoles,   'Poles',  d1.poles,           d2.poles,       d1.code, d2.code);
      if (ctxAvg)     this.makeBar(ctxAvg,     'Ø Ziel', d1.avg_finish ?? 0, d2.avg_finish ?? 0, d1.code, d2.code);
      if (ctxDnfs)    this.makeBar(ctxDnfs,    'Dnfs',   d1.dnfs,            d2.dnfs,        d1.code, d2.code);

    });
  }
}
