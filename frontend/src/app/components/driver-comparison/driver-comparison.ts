import {
  Component, ViewChild, ElementRef, OnInit, OnDestroy, AfterViewInit, inject,
} from '@angular/core';
import { CommonModule, isPlatformBrowser } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { PLATFORM_ID } from '@angular/core';

import { Chart, registerables, ChartConfiguration, TooltipItem } from 'chart.js';
Chart.register(...registerables);

type Stats = { points: number; wins: number; poles: number; podiums: number; avgFinish: number; };
type Driver = { code: string; name: string };

@Component({
  selector: 'app-driver-comparison',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './driver-comparison.html',
  styleUrls: ['./driver-comparison.css'],
})
export class DriverComparison implements OnInit, AfterViewInit, OnDestroy {
  @ViewChild('chartCanvas', { static: false }) chartCanvas!: ElementRef<HTMLCanvasElement>;
  chart?: Chart;

  private platformId = inject(PLATFORM_ID);
  private isBrowser = isPlatformBrowser(this.platformId);

  currentYear = new Date().getFullYear();

  seasons = Array.from({ length: 2025 - 2018 + 1 }, (_, i) => 2018 + i);
  drivers: Driver[] = [
    { code: 'VER', name: 'Max Verstappen' },
    { code: 'HAM', name: 'Lewis Hamilton' },
    { code: 'LEC', name: 'Charles Leclerc' },
    { code: 'VET', name: 'Sebastian Vettel' },
    { code: 'NOR', name: 'Lando Norris' },
    { code: 'RUS', name: 'George Russell' },
    { code: 'PER', name: 'Sergio Perez' },
    { code: 'ALO', name: 'Fernando Alonso' },
    { code: 'SAI', name: 'Carlos Sainz' },
  ];

  // Defaults
  season = 2025;
  driver1 = 'LEC';
  driver2 = 'VER';

  // Legende + Farben (werden bei Render gesetzt)
  driver1Name = 'Fahrer 1';
  driver2Name = 'Fahrer 2';
  color1 = '#6ea8fe';
  color2 = '#f778ba';

  ngOnInit(): void {
    this.updateLegendNames();
  }

  ngAfterViewInit(): void {
    // Nur im Browser rendern (fix für SSR)
    if (this.isBrowser) this.render();
  }

  ngOnDestroy(): void {
    this.chart?.destroy();
  }

  onCompare(): void {
    if (this.driver1 === this.driver2) {
      alert('Bitte zwei unterschiedliche Fahrer waehlen.');
      return;
    }
    this.updateLegendNames();
    if (this.isBrowser) this.render();
  }

  private updateLegendNames(): void {
    this.driver1Name = this.drivers.find(d => d.code === this.driver1)?.name ?? 'Fahrer 1';
    this.driver2Name = this.drivers.find(d => d.code === this.driver2)?.name ?? 'Fahrer 2';
  }

  private resolveColors(): { col1: string; col2: string } {
    // Fallback-Farben, falls SSR oder Variablen fehlen
    let col1 = '#6ea8fe';
    let col2 = '#f778ba';
    if (this.isBrowser && typeof getComputedStyle !== 'undefined') {
      const styles = getComputedStyle(document.documentElement);
      col1 = (styles.getPropertyValue('--accent') || col1).trim() || col1;
      col2 = (styles.getPropertyValue('--accent-2') || col2).trim() || col2;
    }
    // fürs Template
    this.color1 = col1;
    this.color2 = col2;
    return { col1, col2 };
  }

  private render(): void {
    if (!this.chartCanvas) return;

    const d1 = this.drivers.find((d) => d.code === this.driver1)!;
    const d2 = this.drivers.find((d) => d.code === this.driver2)!;

    const s1 = this.makeStats(this.season, d1.code);
    const s2 = this.makeStats(this.season, d2.code);

    const labels = ['Punkte', 'Siege', 'Poles', 'Podien', 'Ø Ziel'];
    const d1Data = [s1.points, s1.wins, s1.poles, s1.podiums, s1.avgFinish];
    const d2Data = [s2.points, s2.wins, s2.poles, s2.podiums, s2.avgFinish];

    const { col1, col2 } = this.resolveColors();

    this.chart?.destroy();

    const cfg: ChartConfiguration<'bar'> = {
      type: 'bar',
      data: {
        labels,
        datasets: [
          { label: `${d1.name} (${d1.code})`, data: d1Data, backgroundColor: col1 },
          { label: `${d2.name} (${d2.code})`, data: d2Data, backgroundColor: col2 },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        aspectRatio: 2.0,
        scales: {
          x: { grid: { color: 'rgba(255,255,255,0.06)' } },
          y: { beginAtZero: true, grid: { color: 'rgba(255,255,255,0.06)' } },
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (ctx: TooltipItem<'bar'>) => `${ctx.dataset.label}: ${ctx.parsed.y}`,
            },
          },
        },
      },
    };

    this.chart = new Chart(this.chartCanvas.nativeElement.getContext('2d')!, cfg);
  }

  // ===== Fake-Daten (stabil pro Saison+Fahrer) =====
  private hashStr(s: string): number {
    let h = 2166136261 >>> 0;
    for (let i = 0; i < s.length; i++) {
      h ^= s.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    return h >>> 0;
  }
  private mulberry32(a: number) {
    return function () {
      let t = (a += 0x6D2B79F5);
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  private rndIn(rng: () => number, min: number, max: number) {
    return Math.round(min + rng() * (max - min));
  }
  private rndFloat(rng: () => number, min: number, max: number, d = 1) {
    return +(min + rng() * (max - min)).toFixed(d);
  }
  private makeStats(season: number, code: string): Stats {
    const seed = this.hashStr(`${season}:${code}`);
    const rng = this.mulberry32(seed);
    const wins = this.rndIn(rng, 0, 16);
    const poles = this.rndIn(rng, 0, 14);
    const podiums = Math.max(wins, this.rndIn(rng, wins, 20));
    const points = this.rndIn(rng, podiums * 4, 575);
    const avgFinish = this.rndFloat(rng, 3.0, 12.0, 1);
    return { points, wins, poles, podiums, avgFinish };
  }
}
