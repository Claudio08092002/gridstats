import { Component, OnDestroy, OnInit, inject, PLATFORM_ID } from '@angular/core';
import { CommonModule, isPlatformBrowser } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService, TrackInfo, TrackMapResponse, TrackPoint, TrackCorner } from '../../services/api';
import * as d3 from 'd3';

@Component({
  selector: 'app-track',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './track.html',
  styleUrls: ['./track.css']
})
export class TrackComponent implements OnInit, OnDestroy {
  private api = inject(ApiService);
  private platformId = inject(PLATFORM_ID);

  currentYear = new Date().getFullYear();
  tracks: TrackInfo[] = [];
  selectedKey: string | null = null;
  selected?: TrackInfo;

  trackMap?: TrackMapResponse;

  // Minimal country-to-flag mapping; extend as needed
  private countryFlags: Record<string, string> = {
    'Australia': '🇦🇺',
    'Austria': '🇦🇹',
    'Azerbaijan': '🇦🇿',
    'Bahrain': '🇧🇭',
    'Belgium': '🇧🇪',
    'Brazil': '🇧🇷',
    'Canada': '🇨🇦',
    'China': '🇨🇳',
    'France': '🇫🇷',
    'Germany': '🇩🇪',
    'Hungary': '🇭🇺',
    'Italy': '🇮🇹',
    'Japan': '🇯🇵',
    'Mexico': '🇲🇽',
    'Monaco': '🇲🇨',
    'Netherlands': '🇳🇱',
    'Portugal': '🇵🇹',
    'Qatar': '🇶🇦',
    'Russia': '🇷🇺',
    'Saudi Arabia': '🇸🇦',
    'Singapore': '🇸🇬',
    'South Africa': '🇿🇦',
    'Spain': '🇪🇸',
    'United Arab Emirates': '🇦🇪',
    'United Kingdom': '🇬🇧',
    'Great Britain': '🇬🇧',
    'USA': '🇺🇸',
    'United States': '🇺🇸',
    'United States of America': '🇺🇸',
    'United States Grand Prix': '🇺🇸',
    'América': '🇺🇸',
    'Argentina': '🇦🇷',
    'Emilia-Romagna': '🇮🇹',
    'San Marino': '🇸🇲',
    'Turkey': '🇹🇷',
    'Abu Dhabi': '🇦🇪'
  };

  flagFor(country?: string | null): string {
    if (!country) return '';
    const flag = this.countryFlags[country];
    return flag ?? '';
  }

  ngOnInit(): void {
    if (isPlatformBrowser(this.platformId)) {
      this.api.getTracks().subscribe({
        next: (items) => this.tracks = items,
      });
    }
  }

  ngOnDestroy(): void {
    // cleanup if needed
  }

  onSelectKey(): void {
    if (!this.selectedKey) return;
    this.selected = this.tracks.find(t => t.key === this.selectedKey) ?? undefined;
    if (!this.selected) return;
    this.api.getTrackMap(this.selected.year, this.selected.round).subscribe({
      next: (map) => {
        this.trackMap = map;
        this.drawTrackMap(map);
      }
    });
  }

  private drawTrackMap(trackMapData: TrackMapResponse) {
    if (!isPlatformBrowser(this.platformId)) {
      return;
    }

    this.trackMap = trackMapData;

    const svg = d3.select('#trackMap');
    const svgNode = svg.node();

    if (!svgNode) {
      // SVG may not exist yet because of *ngIf; try again on next tick.
      setTimeout(() => this.drawTrackMap(trackMapData), 0);
      return;
    }

    svg.selectAll('*').remove();

    const trackData: TrackPoint[] = trackMapData.track ?? [];
    const cornerData: TrackCorner[] = trackMapData.corners ?? [];

    if (!trackData.length) {
      console.warn('Track data is empty; nothing to draw.');
      return;
    }

  const widthAttr = Number(svgNode.getAttribute('width'));
  const heightAttr = Number(svgNode.getAttribute('height'));
  const width = Number.isFinite(widthAttr) && widthAttr > 0 ? widthAttr : 800;
  const height = Number.isFinite(heightAttr) && heightAttr > 0 ? heightAttr : 600;
  const padding = 40;

    const xExtent = d3.extent(trackData, (d: TrackPoint) => d.x);
    const yExtent = d3.extent(trackData, (d: TrackPoint) => d.y);

    const minX = xExtent[0];
    const maxX = xExtent[1];
    const minY = yExtent[0];
    const maxY = yExtent[1];

    if (minX === undefined || maxX === undefined || minY === undefined || maxY === undefined) {
      console.error('Track extents undefined, cannot render track.');
      return;
    }

    const rangeWidth = Math.max(maxX - minX, 1e-6);
    const rangeHeight = Math.max(maxY - minY, 1e-6);

    const scale = Math.max(
      Math.min(
        (width - 2 * padding) / rangeWidth,
        (height - 2 * padding) / rangeHeight
      ),
      1e-3
    );

    const xOffset = (width - scale * rangeWidth) / 2;
    const yOffset = (height - scale * rangeHeight) / 2;

    const projectX = (value: number) => (value - minX) * scale + xOffset;
    const projectY = (value: number) => height - ((value - minY) * scale + yOffset);

    svg
      .attr('width', width)
      .attr('height', height)
      .attr('viewBox', `0 0 ${width} ${height}`)
      .attr('preserveAspectRatio', 'xMidYMid meet');

    const lineGenerator = d3.line()
      .x((d: TrackPoint) => projectX(d.x))
      .y((d: TrackPoint) => projectY(d.y))
      .curve(d3.curveLinearClosed);

    const path = svg.append('path')
      .datum(trackData)
      .attr('fill', 'none')
      .attr('stroke', '#FFFFFF')
      .attr('stroke-width', 14)
      .attr('d', lineGenerator);

    const pathNode = path.node();
    if (!pathNode || !pathNode.getTotalLength) {
      console.error('Unable to compute path length.');
      return;
    }

    const totalLength = pathNode.getTotalLength();
    const animationDuration = 2000;

    path.attr('stroke-dasharray', `${totalLength} ${totalLength}`)
      .attr('stroke-dashoffset', totalLength)
      .transition()
      .duration(animationDuration)
      .ease(d3.easeCubicInOut)
      .attr('stroke-dashoffset', 0);

    if (!cornerData.length) {
      return;
    }

    const distance = (x1: number, y1: number, x2: number, y2: number) => Math.hypot(x2 - x1, y2 - y1);
    let runningDistance = 0;
    const startingPoint = pathNode.getPointAtLength(0);

    cornerData.forEach((corner: TrackCorner, index: number) => {
      const currentX = projectX(corner.track_position[0]);
      const currentY = projectY(corner.track_position[1]);

      if (index === 0) {
        runningDistance += distance(startingPoint.x, startingPoint.y, currentX, currentY);
      } else {
        const prev: TrackCorner = cornerData[index - 1];
        runningDistance += distance(
          projectX(prev.track_position[0]),
          projectY(prev.track_position[1]),
          currentX,
          currentY
        );
      }

      corner.distanceFromStart = runningDistance;
    });

    cornerData.forEach((corner: TrackCorner) => {
      const delayTime = this.findTimeToReachDistance(corner.distanceFromStart ?? 0, totalLength, animationDuration);
      const labelX = projectX(corner.text_position[0]);
      const labelY = projectY(corner.text_position[1]);

      svg.append('circle')
        .attr('cx', labelX)
        .attr('cy', labelY)
        .attr('r', 13)
        .attr('fill', '#FFFFFF')
        .attr('opacity', 0)
        .transition()
        .delay(delayTime)
        .attr('opacity', 1);

      svg.append('text')
        .attr('x', labelX)
        .attr('y', labelY)
        .attr('dy', '0.35em')
        .attr('text-anchor', 'middle')
        .attr('fill', '#000b18')
        .attr('font-size', 12)
        .attr('font-weight', '600')
        .attr('opacity', 0)
        .text(corner.corner_number)
        .transition()
        .delay(delayTime)
        .attr('opacity', 1);

      if (corner.corner_name) {
        svg.append('text')
          .attr('x', labelX)
          .attr('y', labelY + 24)
          .attr('text-anchor', 'middle')
          .attr('fill', '#e6edf3')
          .attr('font-size', 11)
          .attr('font-weight', '500')
          .attr('opacity', 0)
          .text(corner.corner_name)
          .transition()
          .delay(delayTime + 150)
          .attr('opacity', 1);
      }
    });
  }

  private findTimeToReachDistance(distance: number, totalLength: number, animationDuration: number): number {
    if (totalLength <= 0) {
      return 0;
    }

    const normalizedDistance = distance / totalLength;
    let tGuess = Math.min(Math.max(normalizedDistance, 0), 1);
    const epsilon = 1e-5;

    for (let i = 0; i < 100; i++) {
      const functionValue = (3 * tGuess ** 2 - 2 * tGuess ** 3) - normalizedDistance;
      const derivativeValue = 6 * tGuess - 6 * tGuess ** 2;

      if (Math.abs(derivativeValue) < epsilon) {
        break;
      }

      const tNext = tGuess - functionValue / derivativeValue;
      if (Math.abs(tNext - tGuess) < epsilon) {
        tGuess = tNext;
        break;
      }
      tGuess = tNext;
    }

    return Math.min(Math.max(tGuess, 0), 1) * animationDuration;
  }
}
 
