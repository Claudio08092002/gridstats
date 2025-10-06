import { Component, OnInit, OnDestroy, AfterViewInit, ViewChild, ElementRef, inject, PLATFORM_ID, ChangeDetectorRef, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule, isPlatformBrowser } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService, ConstructorSummary, ConstructorListResponse, ConstructorComparisonResponse } from '../../services/api';
import { Chart, registerables, ChartConfiguration } from 'chart.js';

Chart.register(...registerables);

@Component({
  selector: 'app-constructor',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './constructor.html',
  styleUrl: './constructor.css',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class ConstructorComponent implements OnInit, OnDestroy, AfterViewInit {
  @ViewChild('pointsChart', { static: false }) pointsChart?: ElementRef<HTMLCanvasElement>;
  @ViewChild('winsChart', { static: false }) winsChart?: ElementRef<HTMLCanvasElement>;
  @ViewChild('podiumsChart', { static: false }) podiumsChart?: ElementRef<HTMLCanvasElement>;

  private api = inject(ApiService);
  private platformId = inject(PLATFORM_ID);
  private cdr = inject(ChangeDetectorRef);
  private isBrowser = isPlatformBrowser(this.platformId);
  
  private charts: Chart[] = [];

  currentYear = new Date().getFullYear();
  loading = false;
  errorMsg: string | null = null;
  
  constructorKeys: string[] = [];
  constructorMap: Record<string, ConstructorSummary> = {};
  
  constructor1: string | null = null;
  constructor2: string | null = null;
  
  constructor1Data: ConstructorSummary | null = null;
  constructor2Data: ConstructorSummary | null = null;
  
  showDriversList1 = false;
  showDriversList2 = false;
  
  compared = false;
  years: number[] = [];

  ngOnInit(): void {
    this.loadConstructors();
  }

  ngAfterViewInit(): void {
    console.log('View initialized, canvas elements available');
  }

  ngOnDestroy(): void {
    this.destroyCharts();
  }

  private destroyCharts(): void {
    this.charts.forEach(c => c.destroy());
    this.charts = [];
  }

  loadConstructors(): void {
    console.log('loadConstructors() called');
    
    // Prevent multiple simultaneous calls
    if (this.loading) {
      console.warn('Already loading constructors, skipping...');
      return;
    }
    
    this.loading = true;
    this.errorMsg = null;
    
    this.api.getConstructors().subscribe({
      next: (resp: ConstructorListResponse) => {
        console.log('Constructors loaded successfully');
        this.loading = false;
        this.constructorMap = resp.constructors ?? {};
        this.years = resp.years ?? [];
        
        // Sort constructors alphabetically by name
        this.constructorKeys = Object.keys(this.constructorMap).sort((a, b) => {
          const nameA = this.constructorMap[a]?.name || a;
          const nameB = this.constructorMap[b]?.name || b;
          return nameA.localeCompare(nameB);
        });
        
        console.log('Loaded constructors:', this.constructorKeys.length, 'items');
        this.cdr.markForCheck();
      },
      error: (err) => {
        console.error('Error loading constructors:', err);
        this.loading = false;
        this.errorMsg = err?.error?.detail ?? err.message ?? 'Failed to load constructors';
        this.cdr.markForCheck();
      }
    });
  }

  onCompare(): void {
    let cardDiv = document.querySelector('.card');
    cardDiv?.setAttribute('style', 'padding: 2rem;');
    if (!this.constructor1 || !this.constructor2) {
      this.errorMsg = 'Please select both constructors';
      return;
    }

    if (this.constructor1 === this.constructor2) {
      this.errorMsg = 'Please select different constructors';
      return;
    }

    this.loading = true;
    this.errorMsg = null;
    this.compared = false;
    this.destroyCharts();

    this.api.compareConstructors(this.constructor1, this.constructor2).subscribe({
      next: (resp: ConstructorComparisonResponse) => {
        this.loading = false;
        this.constructor1Data = resp.constructor1;
        this.constructor2Data = resp.constructor2;
        this.years = resp.years;
        this.compared = true;
        this.cdr.markForCheck();

        // Wait longer for view to fully render
        setTimeout(() => {
          console.log('Creating charts...');
          try {
            this.createCharts();
            this.cdr.markForCheck();
          } catch (error) {
            console.error('Error creating charts:', error);
            this.errorMsg = 'Failed to create charts';
            this.cdr.markForCheck();
          }
        }, 500);
      },
      error: (err) => {
        this.loading = false;
        this.errorMsg = err?.error?.detail ?? err.message ?? 'Failed to compare constructors';
        console.error('Error comparing constructors:', err);
        this.cdr.markForCheck();
      }
    });
  }

  private createCharts(): void {
    if (!this.isBrowser || !this.constructor1Data || !this.constructor2Data) {
      console.warn('Cannot create charts: missing browser or data');
      return;
    }

    console.log('Canvas elements:', {
      points: !!this.pointsChart?.nativeElement,
      wins: !!this.winsChart?.nativeElement,
      podiums: !!this.podiumsChart?.nativeElement
    });

    console.log('Constructor data:', {
      c1Name: this.constructor1Data?.name,
      c2Name: this.constructor2Data?.name,
      c1PointsByYear: this.constructor1Data?.points_by_year,
      c2PointsByYear: this.constructor2Data?.points_by_year
    });

    this.createPointsChart();
    this.createWinsChart();
    this.createPodiumsChart();
  }

  private createPointsChart(): void {
    if (!this.pointsChart?.nativeElement) {
      console.warn('Points chart canvas not found');
      return;
    }
    console.log('Creating points chart...');

    try {
      const c1 = this.constructor1Data!;
      const c2 = this.constructor2Data!;

      // Combine all years from both constructors
      const allYears = new Set<number>();
      Object.keys(c1.points_by_year).forEach(y => allYears.add(parseInt(y)));
      Object.keys(c2.points_by_year).forEach(y => allYears.add(parseInt(y)));
      const years = Array.from(allYears).sort();

      const data1 = years.map(y => c1.points_by_year[y.toString()] || 0);
      const data2 = years.map(y => c2.points_by_year[y.toString()] || 0);

      // Get standings positions by year
      const c1Standings = c1.standings_by_year || {};
      const c2Standings = c2.standings_by_year || {};

      // Larger radius for championship years (position 1)
      const pointRadius1 = years.map(y => c1Standings[y.toString()] === 1 ? 8 : 4);
      const pointRadius2 = years.map(y => c2Standings[y.toString()] === 1 ? 8 : 4);

      // Use actual team colors
      const color1 = c1.team_color || '#3b82f6';
      const color2 = c2.team_color || '#ef4444';

      console.log('Points chart data:', {
        years,
        c1Data: data1,
        c2Data: data2,
        c1Standings,
        c2Standings,
        color1,
        color2
      });

      // Resolve accent from CSS variables for consistent theming
      const accentCss = this.isBrowser
        ? getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#38bdf8'
        : '#38bdf8';
      const accentCrosshair = this.hexToRgba(accentCss, 0.40);

      // Lightweight vertical crosshair plugin for the hover index
      const crosshairPlugin = {
        id: 'verticalHoverLine',
        afterDraw(chart: any) {
          try {
            const active = typeof chart.getActiveElements === 'function' ? chart.getActiveElements() : [];
            if (!active || !active.length) return;
            const xScale = chart.scales?.x;
            const yScale = chart.scales?.y;
            if (!xScale || !yScale) return;
            const index = active[0].index;
            const x = xScale.getPixelForValue(index);
            const ctx = chart.ctx;
            ctx.save();
            ctx.strokeStyle = accentCrosshair;
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(x, yScale.top);
            ctx.lineTo(x, yScale.bottom);
            ctx.stroke();
            ctx.restore();
          } catch {}
        },
      } as const;

      const config: ChartConfiguration = {
        type: 'line',
        data: {
        labels: years.map(y => y.toString()),
        datasets: [
          {
            label: c1.name,
            data: data1,
            borderColor: color1,
            backgroundColor: this.hexToRgba(color1, 0.1),
            tension: 0.3,
            fill: true,
            pointRadius: pointRadius1,
            pointHitRadius: 10,
            pointHoverRadius: years.map(y => c1Standings[y.toString()] === 1 ? 10 : 7),
            pointBackgroundColor: color1,
            pointBorderColor: color1,
            pointBorderWidth: years.map(y => c1Standings[y.toString()] === 1 ? 2 : 1),
          },
          {
            label: c2.name,
            data: data2,
            borderColor: color2,
            backgroundColor: this.hexToRgba(color2, 0.1),
            tension: 0.3,
            fill: true,
            pointRadius: pointRadius2,
            pointHitRadius: 10,
            pointHoverRadius: years.map(y => c2Standings[y.toString()] === 1 ? 10 : 7),
            pointBackgroundColor: color2,
            pointBorderColor: color2,
            pointBorderWidth: years.map(y => c2Standings[y.toString()] === 1 ? 2 : 1),
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false, axis: 'x' },
        hover: { mode: 'index', intersect: false },
        plugins: {
          title: {
            display: true,
            text: 'Points Over Time',
            color: '#e6edf3',
            font: { size: 16, weight: 'bold' }
          },
          legend: {
            labels: { color: '#e6edf3' }
          },
          tooltip: {
            intersect: false,
            mode: 'index',
            position: 'nearest',
            callbacks: {
              title: (items: any[]) => (items?.length ? `Year ${items[0].label}` : ''),
              label: (ctx: any) => {
                const label = ctx.dataset?.label || '';
                const val = ctx.formattedValue ?? ctx.raw;
                return `${label}: ${val} pts`;
              },
              afterLabel: (context: any) => {
                const year = years[context.dataIndex];
                const yearStr = year.toString();
                const datasetIndex = context.datasetIndex;
                const position = datasetIndex === 0
                  ? c1Standings[yearStr]
                  : c2Standings[yearStr];
                if (!position) return '';
                const getOrdinal = (n: number): string => {
                  const s = ['th', 'st', 'nd', 'rd'];
                  const v = n % 100;
                  return n + (s[(v - 20) % 10] || s[v] || s[0]);
                };
                const standing = `Standing: ${getOrdinal(position)}`;
                return position === 1 ? `${standing} 👑` : standing;
              }
            }
          }
        },
        scales: {
          y: {
            beginAtZero: true,
            ticks: { color: '#7d8596' },
            grid: { color: 'rgba(125, 133, 150, 0.1)' }
          },
          x: {
            ticks: { color: '#7d8596' },
            grid: { color: 'rgba(125, 133, 150, 0.1)' }
          }
        }
      },
      plugins: [crosshairPlugin]
    } as any;

    const chart = new Chart(this.pointsChart.nativeElement, config as any);
    this.charts.push(chart);
    console.log('Points chart created successfully');
    } catch (error) {
      console.error('Error creating points chart:', error);
    }
  }

  private createWinsChart(): void {
    if (!this.winsChart?.nativeElement) {
      console.warn('Wins chart canvas not found');
      return;
    }
    console.log('Creating wins chart...');

    try {
      const c1 = this.constructor1Data!;
      const c2 = this.constructor2Data!;

    const allYears = new Set<number>();
    Object.keys(c1.wins_by_year).forEach(y => allYears.add(parseInt(y)));
    Object.keys(c2.wins_by_year).forEach(y => allYears.add(parseInt(y)));
    const years = Array.from(allYears).sort();

    const data1 = years.map(y => c1.wins_by_year[y.toString()] || 0);
    const data2 = years.map(y => c2.wins_by_year[y.toString()] || 0);

    // Use actual team colors
    const color1 = c1.team_color || '#3b82f6';
    const color2 = c2.team_color || '#ef4444';

    const config: ChartConfiguration = {
      type: 'bar',
      data: {
        labels: years.map(y => y.toString()),
        datasets: [
          {
            label: c1.name,
            data: data1,
            backgroundColor: color1,
          },
          {
            label: c2.name,
            data: data2,
            backgroundColor: color2,
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false, axis: 'x' },
        hover: { mode: 'index', intersect: false },
        animation: false,
        plugins: {
          title: {
            display: true,
            text: 'Wins by Year',
            color: '#e2e8f0',
            font: { size: 16 }
          },
          legend: {
            labels: { color: '#e2e8f0' }
          }
        },
        scales: {
          y: {
            beginAtZero: true,
            ticks: { color: '#94a3b8', stepSize: 1 },
            grid: { color: 'rgba(148, 163, 184, 0.1)' }
          },
          x: {
            ticks: { color: '#94a3b8' },
            grid: { color: 'rgba(148, 163, 184, 0.1)' }
          }
        }
      }
    };

    const chart = new Chart(this.winsChart.nativeElement, config);
    this.charts.push(chart);
    console.log('Wins chart created successfully');
    } catch (error) {
      console.error('Error creating wins chart:', error);
    }
  }

  private createPodiumsChart(): void {
    if (!this.podiumsChart?.nativeElement) {
      console.warn('Podiums chart canvas not found');
      return;
    }
    console.log('Creating podiums chart...');

    try {
      const c1 = this.constructor1Data!;
      const c2 = this.constructor2Data!;

    const allYears = new Set<number>();
    Object.keys(c1.podiums_by_year).forEach(y => allYears.add(parseInt(y)));
    Object.keys(c2.podiums_by_year).forEach(y => allYears.add(parseInt(y)));
    const years = Array.from(allYears).sort();

    const data1 = years.map(y => c1.podiums_by_year[y.toString()] || 0);
    const data2 = years.map(y => c2.podiums_by_year[y.toString()] || 0);

    // Use actual team colors
    const color1 = c1.team_color || '#3b82f6';
    const color2 = c2.team_color || '#ef4444';

    const config: ChartConfiguration = {
      type: 'bar',
      data: {
        labels: years.map(y => y.toString()),
        datasets: [
          {
            label: c1.name,
            data: data1,
            backgroundColor: color1,
          },
          {
            label: c2.name,
            data: data2,
            backgroundColor: color2,
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false, axis: 'x' },
        hover: { mode: 'index', intersect: false },
        animation: false,
        plugins: {
          title: {
            display: true,
            text: 'Podiums by Year',
            color: '#e2e8f0',
            font: { size: 16 }
          },
          legend: {
            labels: { color: '#e2e8f0' }
          }
        },
        scales: {
          y: {
            beginAtZero: true,
            ticks: { color: '#94a3b8', stepSize: 1 },
            grid: { color: 'rgba(148, 163, 184, 0.1)' }
          },
          x: {
            ticks: { color: '#94a3b8' },
            grid: { color: 'rgba(148, 163, 184, 0.1)' }
          }
        }
      }
    };

    const chart = new Chart(this.podiumsChart.nativeElement, config);
    this.charts.push(chart);
    console.log('Podiums chart created successfully');
    } catch (error) {
      console.error('Error creating podiums chart:', error);
    }
  }

  getBestResultDisplay(bestResult: ConstructorSummary['best_result']): string {
    if (!bestResult || !bestResult.drivers || bestResult.drivers.length === 0) return 'N/A';
    
    // Format as multi-line for better readability
    const eventLine = `<strong>${bestResult.year} - ${bestResult.event}</strong>`;
    const pointsLine = `<span style="font-size: 0.9em;">${bestResult.points} pts total</span>`;
    const driversLines = bestResult.drivers
      .map(d => `<span style="font-size: 0.85em;">P${d.position} ${d.name} (${d.points}pts)</span>`)
      .join('<br/>');
    
    return `${eventLine}<br/>${pointsLine}<br/>${driversLines}`;
  }

  toggleDriversList(constructor: number): void {
    if (constructor === 1) {
      this.showDriversList1 = !this.showDriversList1;
      this.showDriversList2 = false;
    } else {
      this.showDriversList2 = !this.showDriversList2;
      this.showDriversList1 = false;
    }
    this.cdr.markForCheck();
  }

  getDriverChanges(constructor: ConstructorSummary): Array<{year: number, joined: string[], left: string[]}> {
    if (!constructor || !constructor.drivers_by_year) return [];
    
    const changes: Array<{year: number, joined: string[], left: string[]}> = [];
    const sortedYears = constructor.seasons.sort((a, b) => a - b);
    
    for (let i = 0; i < sortedYears.length; i++) {
      const year = sortedYears[i];
      const currentDrivers = constructor.drivers_by_year[year.toString()] || [];
      const previousDrivers = i > 0 ? (constructor.drivers_by_year[sortedYears[i - 1].toString()] || []) : [];
      
      const joined = currentDrivers.filter(d => !previousDrivers.includes(d));
      const left = previousDrivers.filter(d => !currentDrivers.includes(d));
      
      // Only show years where there were changes
      if (joined.length > 0 || left.length > 0) {
        changes.push({
          year,
          joined: joined.sort(),
          left: left.sort()
        });
      }
    }
    
    return changes;
  }

  private hexToRgba(hex: string, alpha: number): string {
    // Remove # if present
    hex = hex.replace('#', '');
    
    // Parse hex to RGB
    const r = parseInt(hex.substring(0, 2), 16);
    const g = parseInt(hex.substring(2, 4), 16);
    const b = parseInt(hex.substring(4, 6), 16);
    
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }
}
