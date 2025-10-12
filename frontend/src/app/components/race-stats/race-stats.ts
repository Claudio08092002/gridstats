import { Component, OnInit, AfterViewInit, inject, PLATFORM_ID } from '@angular/core';
import { CommonModule, isPlatformBrowser } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import * as d3 from 'd3';
import { ApiService, RaceOverviewResponse, PositionSeries, TeamPaceItem, TeamBoxItem } from '../../services/api';

@Component({
  selector: 'app-race-stats',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './race-stats.html',
  styleUrls: ['./race-stats.css'],
})
export class RaceStatsComponent implements OnInit, AfterViewInit {
  private route = inject(ActivatedRoute);
  private api = inject(ApiService);
  private platformId = inject(PLATFORM_ID);
  private readonly isBrowser = isPlatformBrowser(this.platformId);
  private router = inject(Router);

  year = Number(this.route.snapshot.paramMap.get('year')) || 0;
  round = Number(this.route.snapshot.paramMap.get('round')) || 0;

  data: RaceOverviewResponse | null = null;
  loading = false;
  error: string | null = null;

  ngOnInit(): void {
    this.fetch();
  }

  ngAfterViewInit(): void {
    // charts render after data load when in browser
  }

  goDriver(r: any): void {
    const code = r?.driver; if (!code) return;
    this.router.navigate(['/race', this.year, this.round, 'driver', code]);
  }

  private fetch(): void {
    this.loading = true;
    this.error = null;
    this.api.getRaceOverview(this.year, this.round).subscribe({
      next: (res) => {
        this.data = res;
        this.loading = false;
        if (this.isBrowser) {
          setTimeout(() => {
            this.renderPositionChart(res);
            this.renderTeamBoxplot(res.team_box || []);
          }, 0);
        }
      },
      error: (err) => {
        this.loading = false;
        this.error = err?.error?.detail || err?.message || 'Failed to load race overview';
      },
    });
  }

  formatDuration(ms: number | null | undefined): string {
    if (!ms || ms <= 0) { return '—'; }
    const sec = Math.floor(ms / 1000);
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = sec % 60;
    if (h > 0) return `${h}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
    return `${m}:${String(s).padStart(2,'0')}`;
  }

  formatLap(ms: number | null | undefined): string {
    if (!ms || ms <= 0) { return ''; }
    const sec = ms / 1000;
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${m}:${s.toFixed(3).padStart(6,'0')}`;
  }

  simplifyStatus(r: any): string {
    const raw: string = (r?.status || '').toString().toLowerCase();
    if (!raw) return r?.dnf ? 'Retired' : 'Finished';
    if (raw.includes('disqual') || raw.includes('excluded')) return 'DSQ';
    if (raw.includes('did not start') || raw === 'dns') return 'DNS';
    if (raw.includes('not classified') || raw === 'nc') return 'NC';
    if (r?.dnf) return 'Retired';
    if (raw.includes('finished') || raw.includes('lapped') || raw.includes('+')) return 'Finished';
    return r?.dnf ? 'Retired' : 'Finished';
  }

  private renderPositionChart(res: RaceOverviewResponse): void {
    const series: PositionSeries[] = res.position_by_lap?.drivers || [];
    const totalLaps = res.meta?.total_laps || 0;
    const el = document.getElementById('pos-chart');
    if (!el) return;
    el.innerHTML = '';
    const margin = { top: 20, right: 90, bottom: 30, left: 30 };
    const width = el.clientWidth || 800;
    const height = el.clientHeight || 420;
    const w = width - margin.left - margin.right;
    const h = height - margin.top - margin.bottom;

    const svg = d3.select(el).append('svg').attr('width', width).attr('height', height);
    const g = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`);

    const x = d3.scaleLinear().domain([0, Math.max(1, totalLaps)]).range([0, w]);
    // y: 1 at top
    const maxPos = d3.max(series.map(s => d3.max(s.laps, (d: any) => d.position) || 0)) || 20;
    const y = d3.scaleLinear().domain([1, Math.max(1, maxPos)]).range([0, h]);

    const xAxis = d3.axisBottom(x).ticks(10).tickFormat((v: any) => (Number(v) === 0 ? '' : d3.format('d')(Number(v))));
    const yAxis = d3.axisLeft(y).ticks(Math.min(maxPos, 20)).tickFormat(d3.format('d'));

    g.append('g').attr('transform', `translate(0,${h})`).call(xAxis);
    g.append('g').call(yAxis);

    const line = d3.line()
      .defined((d: any) => Number.isFinite(d.lap) && Number.isFinite(d.position))
      .x((d: any) => x(d.lap))
      .y((d: any) => y(d.position));

    // draw lines
    // Sort series by final position if available to improve label stacking
    const sorted = [...series].sort((a: any, b: any) => {
      const ap = (a as any).final_position ?? (a.laps?.[a.laps.length - 1]?.position ?? 999);
      const bp = (b as any).final_position ?? (b.laps?.[b.laps.length - 1]?.position ?? 999);
      return ap - bp;
    });

    for (const s of sorted) {
      const col = s.team_color || '#888';
      g.append('path')
        .datum(s.laps)
        .attr('fill', 'none')
        .attr('stroke', col)
        .attr('stroke-width', 1.5)
        .attr('d', line as any)
        .attr('opacity', 0.85);
    }

    // Label placement with de-overlap
    const targets = sorted.map((s: any) => {
      const last = s.laps[s.laps.length - 1];
      const finalPos = s.final_position ?? last?.position ?? 999;
      return { driver: s.driver, color: s.team_color || '#888', y: y(finalPos), pos: finalPos };
    }).sort((a: any, b: any) => a.pos - b.pos);

    const minGap = 12; // px
    let lastY = -1e9;
    for (const t of targets) {
      let yy = t.y;
      if (yy < lastY + minGap) yy = lastY + minGap;
      if (yy > h) yy = h;
      // connector line from right edge to label
      g.append('line')
        .attr('x1', w - 4)
        .attr('x2', w + 2)
        .attr('y1', t.y)
        .attr('y2', yy)
        .attr('stroke', t.color)
        .attr('opacity', 0.6);
      g.append('text')
        .attr('x', w + 6)
        .attr('y', yy)
        .attr('dominant-baseline', 'middle')
        .attr('fill', t.color)
        .attr('font-size', 11)
        .text(t.driver);
      lastY = yy;
    }

    // right guide line for labels
    g.append('line').attr('x1', w).attr('x2', w).attr('y1', 0).attr('y2', h).attr('stroke', '#2a3548').attr('stroke-dasharray', '3,3');
  }

  private renderTeamBoxplot(items: TeamBoxItem[]): void {
    const el = document.getElementById('pace-boxplot');
    if (!el) return;
    el.innerHTML = '';
    const data = [...items].filter(d => d.team && d.median_ms != null && d.q1_ms != null && d.q3_ms != null);

    // Sort by median ascending (faster first)
    data.sort((a, b) => (a.median_ms ?? 0) - (b.median_ms ?? 0));

    const margin = { top: 20, right: 20, bottom: 70, left: 40 };
    const width = el.clientWidth || 900;
    const height = 420;
    const w = width - margin.left - margin.right;
    const h = height - margin.top - margin.bottom;

    const svg = d3.select(el).append('svg').attr('width', width).attr('height', height);
    const g = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`);

    const x = d3.scaleBand().domain(data.map(d => d.team)).range([0, w]).padding(0.2);
    // Ensure all values are numeric milliseconds
    // Convert milliseconds to seconds for axis and plotting, matching typical fastf1 visuals
    const allValsSec = data.flatMap(d => [d.min_ms, d.q1_ms, d.median_ms, d.q3_ms, d.max_ms])
      .map(v => (v == null ? null : Number(v) / 1000))
      .filter((v: any) => Number.isFinite(v)) as number[];
    const extentSec = d3.extent(allValsSec) as [number, number];
    const padSec = (extentSec && isFinite(extentSec[0]) && isFinite(extentSec[1])) ? (extentSec[1] - extentSec[0]) * 0.03 : 0;
    const minSec = (extentSec && extentSec[0] != null) ? extentSec[0] - padSec : 0;
    const maxSec = (extentSec && extentSec[1] != null) ? extentSec[1] + padSec : 1;
    const y = d3.scaleLinear().domain([minSec, maxSec]).nice().range([h, 0]);

    g.append('g').attr('transform', `translate(0,${h})`).call(d3.axisBottom(x)).selectAll('text').attr('transform', 'rotate(-30)').style('text-anchor', 'end');
    g.append('g').call(d3.axisLeft(y).ticks(8).tickFormat((v: any) => d3.format('.1f')(Number(v))));

    const boxes = g.selectAll('.box').data(data).enter().append('g').attr('class', 'box').attr('transform', (d: any) => `translate(${x(d.team) || 0},0)`);

    // Whiskers
    boxes.append('line')
      .attr('x1', x.bandwidth() / 2)
      .attr('x2', x.bandwidth() / 2)
      .attr('y1', (d: any) => y((d.min_ms || 0) / 1000))
      .attr('y2', (d: any) => y((d.max_ms || 0) / 1000))
      .attr('stroke', (d: any) => d.team_color || '#777');

    // Box
    boxes.append('rect')
      .attr('x', 0)
      .attr('width', x.bandwidth())
      .attr('y', (d: any) => y(Number(d.q3_ms || 0) / 1000))
      .attr('height', (d: any) => Math.max(1, y(Number(d.q1_ms || 0) / 1000) - y(Number(d.q3_ms || 0) / 1000)))
      .attr('fill', (d: any) => (d.team_color || '#777'))
      .attr('opacity', 0.35)
      .attr('stroke', (d: any) => d.team_color || '#777');

    // Median line
    boxes.append('line')
      .attr('x1', 0)
      .attr('x2', x.bandwidth())
      .attr('y1', (d: any) => y(Number(d.median_ms || 0) / 1000))
      .attr('y2', (d: any) => y(Number(d.median_ms || 0) / 1000))
      .attr('stroke', (d: any) => d.team_color || '#fff')
      .attr('stroke-width', 2);
  }
}
