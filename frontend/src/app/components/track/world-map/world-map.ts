import { Component, ElementRef, EventEmitter, Input, OnChanges, OnDestroy, OnInit, Output, PLATFORM_ID, SimpleChanges, ViewChild, ViewEncapsulation, inject } from '@angular/core';
import { CommonModule, isPlatformBrowser } from '@angular/common';
import * as d3 from 'd3';

export interface CountrySelectEvent {
  code: string; // ISO alpha-2
  name?: string;
}

@Component({
  selector: 'app-track-world-map',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './world-map.html',
  styleUrls: ['./world-map.css'],
  encapsulation: ViewEncapsulation.None,
})
export class TrackWorldMapComponent implements OnInit, OnChanges, OnDestroy {
  @Input() tracks: Array<{ country_code?: string | null } & Record<string, any>> = [];
  @Input() selectedCode: string | null = null;
  @Output() countrySelect = new EventEmitter<CountrySelectEvent>();

  @ViewChild('svg', { static: true }) svgRef!: ElementRef<SVGSVGElement>;
  @ViewChild('canvas', { static: true }) canvasRef!: ElementRef<HTMLDivElement>;
  @ViewChild('tooltip', { static: true }) tooltipRef!: ElementRef<HTMLDivElement>;

  private platformId = inject(PLATFORM_ID);
  private readonly isBrowser = isPlatformBrowser(this.platformId);

  private destroy = false;
  private features: any[] = [];
  private countsByCode: Record<string, number> = {};
  private zoomBehavior: any = null;

  ngOnInit(): void {
    if (!this.isBrowser) return;
    this.updateCounts();
    this.loadGeo().then(() => this.draw());
    window.addEventListener('resize', this.handleResize, { passive: true });
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (!this.isBrowser) return;
    if (changes['tracks']) {
      this.updateCounts();
      this.draw();
    }
    if (changes['selectedCode']) {
      this.highlightSelected();
    }
  }

  ngOnDestroy(): void {
    this.destroy = true;
    if (this.isBrowser) {
      window.removeEventListener('resize', this.handleResize);
    }
  }

  private handleResize = () => {
    if (!this.isBrowser) return;
    this.draw();
  };

  private updateCounts(): void {
    const counts: Record<string, number> = {};
    for (const t of this.tracks || []) {
      const code = (t.country_code || '').toString().toUpperCase();
      if (!code) continue;
      counts[code] = (counts[code] || 0) + 1;
    }
    this.countsByCode = counts;
  }

  private async loadGeo(): Promise<void> {
    if (this.features.length) return;
    const primary = 'https://raw.githubusercontent.com/datasets/geo-countries/master/data/countries.geojson';
    const fallback = 'assets/world/countries.geo.json';
    const tryLoad = async (url: string) => {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`Failed to fetch ${url}`);
      const geo = await res.json();
      return geo && geo.features ? geo.features : [];
    };
    try {
      this.features = await tryLoad(primary);
    } catch {
      try {
        this.features = await tryLoad(fallback);
      } catch {
        this.features = [];
      }
    }
  }

  private iso2Of(d: any): string {
    const p: any = d?.properties || {};
    const raw = (p.ISO_A2 || p.iso_a2 || p['ISO3166-1-Alpha-2'] || '').toString().toUpperCase();
    if (raw && raw.length === 2 && raw !== '-9' && raw !== '-99') {
      return raw;
    }
    const name = (p.ADMIN || p.NAME || p.name || '').toString().toLowerCase();
    const alias: Record<string, string> = {
      'france': 'FR',
      'united kingdom': 'GB',
      'great britain': 'GB',
      'united states': 'US',
      'united states of america': 'US',
      'spain': 'ES',
      'italy': 'IT',
      'germany': 'DE',
      'austria': 'AT',
      'hungary': 'HU',
      'belgium': 'BE',
      'netherlands': 'NL',
      'monaco': 'MC',
      'portugal': 'PT',
      'qatar': 'QA',
      'saudi arabia': 'SA',
      'united arab emirates': 'AE',
      'bahrain': 'BH',
      'singapore': 'SG',
      'japan': 'JP',
      'china': 'CN',
      'azerbaijan': 'AZ',
      'mexico': 'MX',
      'brazil': 'BR',
      'canada': 'CA',
      'australia': 'AU',
      'san marino': 'SM',
      'turkey': 'TR',
    };
    return alias[name] || '';
  }

  private nameOf(d: any): string {
    const p: any = d?.properties || {};
    return (p.ADMIN || p.NAME || p.name || 'Unknown') as string;
  }

  private draw(): void {
    if (!this.isBrowser) return;
    const svgEl = this.svgRef?.nativeElement;
    const canvasEl = this.canvasRef?.nativeElement;
    if (!svgEl || !canvasEl || !this.features?.length) return;

    const tooltip = this.tooltipRef.nativeElement;
    tooltip.style.opacity = '0';

    const bounds = canvasEl.getBoundingClientRect();
    if (!bounds.width) {
      setTimeout(() => { if (!this.destroy) { this.draw(); } }, 16);
      return;
    }
    const width = Math.max(680, Math.floor(bounds.width));
    const height = Math.floor(width * 0.52);

    const svg = d3.select(svgEl);
    svg.attr('viewBox', `0 0 ${width} ${height}`);
    svg.selectAll('*').remove();

    const projection = d3.geoNaturalEarth1().fitSize([width, height], { type: 'FeatureCollection', features: this.features as any });
    const path = d3.geoPath(projection);

    const g = svg.append('g');
    const self = this;

    g.selectAll('path.country')
      .data(this.features)
      .join('path')
      .attr('class', (d: any) => {
        const code = self.iso2Of(d);
        const base = 'country';
        const has = self.countsByCode[code] > 0;
        return has ? base + ' has-tracks' : base;
      })
      .attr('d', path as any)
      .on('mousemove', function (event: MouseEvent, d: any) {
        const code = self.iso2Of(d);
        const name = self.nameOf(d);
        const count = self.countsByCode[code] || 0;
        const x = event.offsetX;
        const y = event.offsetY;
        tooltip.style.left = `${x}px`;
        tooltip.style.top = `${y}px`;
        tooltip.style.opacity = '1';
        tooltip.innerHTML = count > 0 ? `${name} - ${count} track${count > 1 ? 's' : ''}` : `${name}`;
      })
      .on('mouseenter', function (this: SVGPathElement) {
        d3.select(this).classed('hover', true);
      })
      .on('mouseleave', function (this: SVGPathElement) {
        d3.select(this).classed('hover', false);
        tooltip.style.opacity = '0';
      })
      .on('click', (_event: MouseEvent, d: any) => {
        const code = this.iso2Of(d);
        const name = this.nameOf(d) || undefined;
        if (this.countsByCode[code] > 0) {
          this.selectedCode = code;
          this.highlightSelected();
          this.countrySelect.emit({ code, name });
        }
      })
      .append('title')
      .text((d: any) => this.nameOf(d));

    this.highlightSelected();

    const zoomed = (event: any) => {
      g.attr('transform', event.transform.toString());
    };
    const zoom: any = (d3 as any)
      .zoom()
      .scaleExtent([1, 18])
      .translateExtent([[-width, -height], [width * 2, height * 2]])
      .on('zoom', zoomed);
    (svg as any).call(zoom);
    this.zoomBehavior = zoom;
  }

  private highlightSelected(): void {
    const svgEl = this.svgRef?.nativeElement;
    if (!svgEl) return;
    const svg = d3.select(svgEl);
    svg.selectAll('path.country').classed('selected', (d: any) => {
      const code = this.iso2Of(d);
      return !!this.selectedCode && code === this.selectedCode.toUpperCase();
    });
  }

  // Public API: reset zoom/pan and clear selection highlight
  resetMap(): void {
    if (!this.isBrowser) return;
    try {
      // Clear selection highlight
      this.selectedCode = null;
      this.highlightSelected();
      // Hide tooltip
      const tooltip = this.tooltipRef?.nativeElement;
      if (tooltip) tooltip.style.opacity = '0';
      // Reset zoom transform
      const svg = d3.select(this.svgRef?.nativeElement as SVGSVGElement);
      if (this.zoomBehavior) {
        (svg as any)
          .transition()
          .duration(350)
          .call(this.zoomBehavior.transform, (d3 as any).zoomIdentity);
      }
    } catch {}
  }
}
