import { Component, OnInit, inject, PLATFORM_ID } from '@angular/core';
import { CommonModule, isPlatformBrowser } from '@angular/common';
import { ActivatedRoute } from '@angular/router';
import * as d3 from 'd3';
import { ApiService, DriverRaceDetails } from '../../services/api';

@Component({
  selector: 'app-driver-race',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './driver-race.html',
  styleUrls: ['./driver-race.css'],
})
export class DriverRaceComponent implements OnInit {
  private route = inject(ActivatedRoute);
  private api = inject(ApiService);
  private platformId = inject(PLATFORM_ID);
  private readonly isBrowser = isPlatformBrowser(this.platformId);

  year = Number(this.route.snapshot.paramMap.get('year')) || 0;
  round = Number(this.route.snapshot.paramMap.get('round')) || 0;
  driverCode = String(this.route.snapshot.paramMap.get('code') || '');

  data: DriverRaceDetails | null = null;
  loading = false;
  error: string | null = null;

  ngOnInit(): void {
    this.loading = true;
    this.api.getDriverRace(this.year, this.round, this.driverCode).subscribe({
      next: (res) => {
        this.data = res;
        this.loading = false;
        if (this.isBrowser) {
          setTimeout(() => {
            this.renderPace();
            this.renderStints();
            this.renderPositionMini();
          }, 0);
        }
      },
      error: (err) => {
        this.loading = false;
        this.error = err?.error?.detail || err?.message || 'Failed to load driver details';
      },
    });
  }

  fmtDur(ms: number | null | undefined): string { if (!ms || ms <= 0) return '—'; const s = (ms/1000); return `${s.toFixed(3)}s`; }
  fmtTime(ms: number | null | undefined): string { if (!ms || ms <= 0) return '—'; const t = ms/1000; const m = Math.floor(t/60); const s = t % 60; return `${m}:${s.toFixed(3).padStart(6,'0')}`; }

  private renderPace(): void {
    const el = document.getElementById('pace-chart');
    if (!el || !this.data) return; el.innerHTML = '';
    const margin = { top: 20, right: 10, bottom: 30, left: 50 };
    const width = el.clientWidth || 800; const height = el.clientHeight || 420;
    const w = width - margin.left - margin.right; const h = height - margin.top - margin.bottom;
    const svg = d3.select(el).append('svg').attr('width', width).attr('height', height);
    const g = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`);

    const laps = (this.data.laps || []).filter(d => d.lap_time_ms != null && d.is_accurate !== false);
    if (!laps.length) {
      g.append('text')
        .attr('x', w/2)
        .attr('y', h/2)
        .attr('text-anchor','middle')
        .attr('fill','#7d8596')
        .text('No lap data available');
      return;
    }
    const maxLap = d3.max(laps, (d: any) => d.lap) || 1;
    const x = d3.scaleLinear().domain([0.5, maxLap + 0.5]).range([0, w]);
    const extent = d3.extent(laps, (d: any) => d.lap_time_ms as number) as [number, number];
    const pad = (extent[1] - extent[0]) * 0.03; const y = d3.scaleLinear().domain([extent[0]-pad, extent[1]+pad]).range([h, 0]).nice();
    g.append('g').attr('transform', `translate(0,${h})`).call(d3.axisBottom(x).ticks(10).tickFormat(d3.format('d')));
    g.append('g').call(d3.axisLeft(y).ticks(8).tickFormat((v: any) => this.fmtTime(Number(v))));

    const colorByCompound: Record<string, string> = {
      HARD: '#f3f4f6', H: '#f3f4f6', C1: '#f3f4f6', C2: '#f3f4f6', C3: '#f3f4f6',
      MEDIUM: '#ffd500', M: '#ffd500',
      SOFT: '#ff2d2d', S: '#ff2d2d', C4: '#ff2d2d', C5: '#ff2d2d',
      INTERMEDIATE: '#39d353', I: '#39d353',
      WET: '#58a6ff', W: '#58a6ff'
    };
    const tooltip = d3.select('#pace-tooltip');

    // Draw dots (visual density), but interaction will be via an overlay for easy hover
    g.selectAll('circle').data(laps).enter().append('circle')
      .attr('cx', (d: any) => x(d.lap))
      .attr('cy', (d: any) => y(d.lap_time_ms || 0))
      .attr('r', 3)
      .attr('fill', (d: any) => colorByCompound[d.compound || ''] || '#9ca3af')
      .attr('opacity', 0.85);

    const line = d3.line().x((d: any) => x(d.lap)).y((d: any) => y(d.lap_time_ms));
    g.append('path').datum(laps).attr('fill', 'none').attr('stroke', this.data.team_color || '#888').attr('stroke-width', 1.5).attr('opacity', 0.6).attr('d', line as any);

    // Hover overlay with nearest-lap focus
    const focusLine = g.append('line')
      .attr('x1', 0).attr('y1', 0).attr('x2', 0).attr('y2', h)
      .attr('stroke', '#9ca3af').attr('stroke-dasharray', '3,3').style('display', 'none');
    const focusDot = g.append('circle')
      .attr('r', 4).attr('fill', this.data.team_color || '#e6edf3').attr('stroke', '#0b0f16').style('display', 'none');

    const bisect = d3.bisector((d: any) => d.lap).left;
    const onMove = (event: MouseEvent) => {
      const [mx] = d3.pointer(event, g.node() as any);
      const lapX = x.invert(mx);
      let i = bisect(laps, lapX);
      if (i <= 0) i = 0; if (i >= laps.length) i = laps.length - 1;
      const d0 = laps[Math.max(0, i - 1)];
      const d1 = laps[i];
      const d = (!d0 || Math.abs(d1.lap - lapX) < Math.abs(lapX - d0.lap)) ? d1 : d0;
      const cx = x(d.lap);
      const cy = y(d.lap_time_ms || 0);
      focusLine.attr('x1', cx).attr('x2', cx).style('display', 'block');
      focusDot.attr('cx', cx).attr('cy', cy).style('display', 'block');
      const html = `Lap ${d.lap} — ${this.fmtTime(d.lap_time_ms)}${d.compound ? `\n(${(d.compound || '').toUpperCase()})` : ''}`.replace('\n','<br/>');
      tooltip.style('display', 'block').style('left', `${event.pageX + 12}px`).style('top', `${event.pageY - 24}px`).html(html);
    };
    g.append('rect')
      .attr('width', w).attr('height', h)
      .attr('fill', 'none').attr('pointer-events', 'all')
      .on('mousemove', onMove)
      .on('mouseleave', () => { tooltip.style('display','none'); focusLine.style('display', 'none'); focusDot.style('display', 'none'); });
  }

  private renderStints(): void {
    const el = document.getElementById('stint-chart');
    if (!el || !this.data) return; el.innerHTML = '';
    const margin = { top: 10, right: 10, bottom: 20, left: 40 };
    const width = el.clientWidth || 800; const height = el.clientHeight || 160;
    const w = width - margin.left - margin.right; const h = height - margin.top - margin.bottom;
    const svg = d3.select(el).append('svg').attr('width', width).attr('height', height);
    const g = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`);

    const stints = this.data.stints || [];
    const maxLapS = d3.max(stints, (d: any) => d.end_lap) || (this.data.laps[this.data.laps.length-1]?.lap || 1);
    const x = d3.scaleLinear().domain([0.5, maxLapS + 0.5]).range([0, w]);
    g.append('g').attr('transform', `translate(0,${h})`).call(d3.axisBottom(x).ticks(10).tickFormat(d3.format('d')));

    // Pirelli palette similar to FastF1 examples
    const colorByCompound: Record<string, string> = {
      HARD: '#f3f4f6', H: '#f3f4f6', C1: '#f3f4f6', C2: '#f3f4f6', C3: '#f3f4f6',
      MEDIUM: '#ffd500', M: '#ffd500',
      SOFT: '#ff2d2d', S: '#ff2d2d', C4: '#ff2d2d', C5: '#ff2d2d',
      INTERMEDIATE: '#39d353', I: '#39d353',
      WET: '#58a6ff', W: '#58a6ff'
    };
    const yTop = 32; const barHeight = 26;

    const tooltip = d3.select('#stint-tooltip');

    const rects = g.selectAll('rect').data(stints).enter().append('rect')
      .attr('x', (d: any) => x(d.start_lap - 0.5))
      .attr('y', yTop)
      // widen from start_lap -0.5 to end_lap +0.5 to center and remove gaps
      .attr('width', (d: any) => Math.max(1, x(d.end_lap + 0.5) - x(d.start_lap - 0.5)))
      .attr('height', barHeight)
      .attr('fill', (d: any) => colorByCompound[(d.compound || '').toUpperCase()] || '#9ca3af')
      .attr('opacity', 0.9)
      .attr('stroke', '#1f2937')
      .on('mousemove', (event: MouseEvent, d: any) => {
        const pt = this.findPitAtLap(d.end_lap);
        const tyreMs = (pt && (pt as any).stationary_ms != null) ? (pt as any).stationary_ms : (pt ? pt.duration_ms : null);
        const html = `Lap ${d.start_lap} → ${d.end_lap}<br/>Tyre: ${d.compound || '—'}${d.fresh ? ' (new)' : ''}${tyreMs!=null ? `<br/>Pit: ${this.fmtDur(tyreMs)}` : ''}`;
        tooltip.style('display','block').style('left', `${event.pageX + 12}px`).style('top', `${event.pageY - 24}px`).html(html);
      })
      .on('mouseleave', () => { tooltip.style('display','none'); });

    // Labels inside bars (optional)
    g.selectAll('text').data(stints).enter().append('text')
      .attr('x', (d: any) => x((d.start_lap + d.end_lap) / 2))
      .attr('y', yTop + barHeight / 2)
      .attr('dominant-baseline', 'middle')
      .attr('text-anchor', 'middle')
      .attr('fill', '#0b0f16')
      .attr('font-size', 11)
      .text((d: any) => `${(d.compound || '').toUpperCase()}`);
  }

  private findPitAtLap(lap: number) {
    if (!this.data) return null;
    const p = (this.data.pits || []).find(pp => pp.lap === lap || pp.lap === lap + 1);
    return p || null;
  }

  private renderPositionMini(): void {
    const el = document.getElementById('pos-mini-chart');
    if (!el || !this.data) return; el.innerHTML = '';
    const margin = { top: 10, right: 10, bottom: 20, left: 40 };
    const width = el.clientWidth || 800; const height = el.clientHeight || 160;
    const w = width - margin.left - margin.right; const h = height - margin.top - margin.bottom;
    const svg = d3.select(el).append('svg').attr('width', width).attr('height', height);
    const g = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`);

    const laps = (this.data.laps || []).filter(d => d.position != null && d.lap != null);
    if (!laps.length) {
      g.append('text')
        .attr('x', w/2)
        .attr('y', h/2)
        .attr('text-anchor','middle')
        .attr('fill','#7d8596')
        .text('No lap position data');
      return;
    }
    const maxLap = d3.max(laps, (d: any) => d.lap) || 1;
    const maxPos = d3.max(laps, (d: any) => d.position) || 20;
    const x = d3.scaleLinear().domain([0.5, maxLap + 0.5]).range([0, w]);
    const y = d3.scaleLinear().domain([1, Math.max(1, maxPos)]).range([0, h]);
    g.append('g').attr('transform', `translate(0,${h})`).call(d3.axisBottom(x).ticks(10).tickFormat(d3.format('d')));
    g.append('g').call(d3.axisLeft(y).ticks(Math.min(maxPos, 10)).tickFormat(d3.format('d')));

    const line = d3.line().x((d: any) => x(d.lap)).y((d: any) => y(d.position));
    g.append('path').datum(laps).attr('fill', 'none').attr('stroke', this.data.team_color || '#7d8596').attr('stroke-width', 1.5).attr('opacity', 0.8).attr('d', line as any);

    const tooltip = d3.select('#pos-tooltip');
    const focusLine = g.append('line')
      .attr('x1', 0).attr('y1', 0).attr('x2', 0).attr('y2', h)
      .attr('stroke', '#9ca3af').attr('stroke-dasharray', '3,3').style('display', 'none');
    const focusDot = g.append('circle')
      .attr('r', 4).attr('fill', this.data.team_color || '#e6edf3').attr('stroke', '#0b0f16').style('display', 'none');
    const bisect = d3.bisector((d: any) => d.lap).left;
    const onMove = (event: MouseEvent) => {
      const [mx] = d3.pointer(event, g.node() as any);
      const lapX = x.invert(mx);
      let i = bisect(laps, lapX);
      if (i <= 0) i = 0; if (i >= laps.length) i = laps.length - 1;
      const d0 = laps[Math.max(0, i - 1)];
      const d1 = laps[i];
      const d = (!d0 || Math.abs(d1.lap - lapX) < Math.abs(lapX - d0.lap)) ? d1 : d0;
      const cx = x(d.lap);
      const cy = y(d.position);
      focusLine.attr('x1', cx).attr('x2', cx).style('display', 'block');
      focusDot.attr('cx', cx).attr('cy', cy).style('display', 'block');
      const html = `Lap ${d.lap} — Pos ${d.position}`;
      tooltip.style('display', 'block').style('left', `${event.pageX + 12}px`).style('top', `${event.pageY - 24}px`).html(html);
    };
    g.append('rect')
      .attr('width', w).attr('height', h)
      .attr('fill', 'none').attr('pointer-events', 'all')
      .on('mousemove', onMove)
      .on('mouseleave', () => { tooltip.style('display','none'); focusLine.style('display', 'none'); focusDot.style('display', 'none'); });
  }
}
