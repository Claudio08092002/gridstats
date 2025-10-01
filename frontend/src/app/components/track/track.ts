import { Component, OnDestroy, OnInit, inject, PLATFORM_ID } from '@angular/core';
import { CommonModule, isPlatformBrowser } from '@angular/common';
import { FormsModule } from '@angular/forms';
import {
  ApiService,
  TrackInfo,
  TrackMapResponse,
  TrackPoint,
  TrackCorner,
  TrackLayoutVariant,
  RaceWinnerInfo,
  TrackRoundRef,
} from '../../services/api';
import * as d3 from 'd3';

@Component({
  selector: 'app-track',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './track.html',
  styleUrls: ['./track.css'],
})
export class TrackComponent implements OnInit, OnDestroy {
  private api = inject(ApiService);
  private platformId = inject(PLATFORM_ID);
  private readonly isBrowser = isPlatformBrowser(this.platformId);

  currentYear = new Date().getFullYear();

  tracks: TrackInfo[] = [];
  selectedKey: string | null = null;
  selectedTrack?: TrackInfo;

  selectedVariantSignature: string | null = null;
  selectedRoundKey: string | null = null;
  selectedRound?: TrackRoundRef;

  trackMap?: TrackMapResponse;
  layoutVariants: TrackLayoutVariant[] = [];
  layoutYears: number[] = [];
  winners: RaceWinnerInfo[] = [];

  loading = false;
  error: string | null = null;

  ngOnInit(): void {
    if (!this.isBrowser) {
      return;
    }
    this.api.getTracks().subscribe({
      next: (items) => {
        this.tracks = (items ?? []).sort((a, b) => a.display_name.localeCompare(b.display_name));
      },
      error: (err) => {
        this.error = err?.error?.detail ?? err?.message ?? 'Failed to load tracks';
      },
    });
  }

  ngOnDestroy(): void {
    // No subscriptions to clean up; kept for future extensibility.
  }

  get layoutYearsLabel(): string {
    return this.layoutYears?.length ? this.layoutYears.join(', ') : '';
  }

  get selectedVariantRounds(): TrackRoundRef[] {
    const variant = this.layoutVariants.find((item) => item.layout_signature === this.selectedVariantSignature);
    if (!variant) {
      return [];
    }
    return [...variant.rounds].sort((a, b) => {
      if (a.year === b.year) {
        return a.round - b.round;
      }
      return a.year - b.year;
    });
  }

  get displayWinners(): RaceWinnerInfo[] {
    if (!this.winners?.length) {
      return [];
    }
    return [...this.winners].sort((a, b) => {
      if (a.year === b.year) {
        return b.round - a.round;
      }
      return b.year - a.year;
    });
  }

  flagClass(track?: TrackInfo | null): string[] | null {
    const code = track?.country_code;
    if (!code) {
      return null;
    }
    const normalized = code.toLowerCase();
    return ['fi', `fi-${normalized}`];
  }

  onSelectTrack(): void {
    this.trackMap = undefined;
    this.layoutVariants = [];
    this.layoutYears = [];
    this.winners = [];
    this.selectedVariantSignature = null;
    this.selectedRoundKey = null;
    this.selectedRound = undefined;
    this.error = null;

    if (!this.selectedKey) {
      this.selectedTrack = undefined;
      return;
    }

    this.selectedTrack = this.tracks.find((item) => item.key === this.selectedKey);
    if (!this.selectedTrack) {
      return;
    }

    const defaultRound = this.pickLatestRound(this.selectedTrack.rounds);
    if (defaultRound) {
      this.loadTrackMap(defaultRound, true);
    }
  }

  onVariantSelect(signature: string | null): void {
    if (!signature) {
      return;
    }
    // Don't return early if same signature - allow redraw
    const needsReload = this.selectedVariantSignature !== signature;
    this.selectedVariantSignature = signature;
    const variant = this.layoutVariants.find((item) => item.layout_signature === signature);
    if (!variant) {
      return;
    }
    const targetRound = this.pickLatestRound(variant.rounds);
    if (targetRound) {
      if (needsReload) {
        this.loadTrackMap(targetRound, true);
      } else {
        // Redraw current map even if same signature
        if (this.trackMap) {
          this.drawTrackMap(this.trackMap);
        }
      }
    }
  }

  onRoundSelect(roundKey: string | null): void {
    if (!roundKey) {
      return;
    }
    if (this.selectedRoundKey === roundKey) {
      return;
    }
    this.selectedRoundKey = roundKey;
    const [yearStr, roundStr] = roundKey.split('-');
    const year = Number(yearStr);
    const round = Number(roundStr);
    if (!Number.isFinite(year) || !Number.isFinite(round)) {
      return;
    }
    let roundRef: TrackRoundRef | undefined;
    const variant = this.layoutVariants.find((item) => item.layout_signature === this.selectedVariantSignature);
    if (variant) {
      roundRef = variant.rounds.find((r) => r.year === year && r.round === round);
    }
    if (!roundRef && this.selectedTrack) {
      roundRef = this.selectedTrack.rounds.find((r) => r.year === year && r.round === round);
    }
    if (roundRef) {
      this.loadTrackMap(roundRef, true);
    }
  }

  private pickLatestRound(rounds: TrackRoundRef[] | undefined): TrackRoundRef | null {
    if (!rounds || !rounds.length) {
      return null;
    }
    const sorted = [...rounds].sort((a, b) => {
      if (a.year === b.year) {
        return a.round - b.round;
      }
      return a.year - b.year;
    });
    return sorted[sorted.length - 1];
  }

  private loadTrackMap(roundRef: TrackRoundRef, includeLayouts: boolean): void {
    if (!this.isBrowser) {
      return;
    }
    this.loading = true;
    this.error = null;
    this.selectedRound = roundRef;
    this.selectedRoundKey = `${roundRef.year}-${roundRef.round}`;

    this.api.getTrackMap(roundRef.year, roundRef.round, { includeLayouts }).subscribe({
      next: (map) => {
        this.loading = false;
        this.trackMap = map;
        this.layoutVariants = map.layout_variants ?? [];
        this.layoutYears = map.layout_years ?? [];
        this.winners = map.winners ?? [];
        const stillValid = this.selectedVariantSignature
          ? this.layoutVariants.some((variant) => variant.layout_signature === this.selectedVariantSignature)
          : false;

        if (map.layout_signature) {
          this.selectedVariantSignature = map.layout_signature;
        } else if (!stillValid && this.layoutVariants.length) {
          this.selectedVariantSignature = this.layoutVariants[0].layout_signature;
        } else if (!stillValid) {
          this.selectedVariantSignature = null;
        }
        this.drawTrackMap(map);
      },
      error: (err) => {
        this.loading = false;
        this.error = err?.error?.detail ?? err?.message ?? 'Failed to load track map';
      },
    });
  }

  private drawTrackMap(trackMapData: TrackMapResponse): void {
    if (!this.isBrowser) {
      return;
    }

    this.trackMap = trackMapData;

    const svg = d3.select('#trackMap');
    const svgNode = svg.node();

    if (!svgNode) {
      setTimeout(() => this.drawTrackMap(trackMapData), 0);
      return;
    }

    svg.selectAll('*').remove();

    const trackData: TrackPoint[] = trackMapData.track ?? [];
    const cornerData: TrackCorner[] = trackMapData.corners ?? [];

    console.log('[TrackMap] Drawing track map:', {
      trackPoints: trackData.length,
      corners: cornerData.length,
      layoutSignature: trackMapData.layout_signature,
      layoutLabel: trackMapData.layout_label,
    });

    if (!trackData.length) {
      console.warn('[TrackMap] No track data available');
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
      return;
    }

    const rangeWidth = Math.max(maxX - minX, 1e-6);
    const rangeHeight = Math.max(maxY - minY, 1e-6);

    const scale = Math.max(
      Math.min(
        (width - 2 * padding) / rangeWidth,
        (height - 2 * padding) / rangeHeight,
      ),
      1e-3,
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

    const lineGenerator = d3
      .line()
      .x((d: unknown) => projectX((d as TrackPoint).x))
      .y((d: unknown) => projectY((d as TrackPoint).y))
      .curve(d3.curveLinearClosed);

    const path = svg
      .append('path')
      .datum(trackData)
      .attr('fill', 'none')
      .attr('stroke', '#FFFFFF')
      .attr('stroke-width', 14)
      .attr('d', lineGenerator);

    const pathNode = path.node();
    if (!pathNode || !pathNode.getTotalLength) {
      return;
    }

    const totalLength = pathNode.getTotalLength();
    const animationDuration = 2000;

    path
      .attr('stroke-dasharray', `${totalLength} ${totalLength}`)
      .attr('stroke-dashoffset', totalLength)
      .transition()
      .duration(animationDuration)
      .ease(d3.easeCubicInOut)
      .attr('stroke-dashoffset', 0);

    console.log('[TrackMap] Path animated, checking corners:', {
      cornerCount: cornerData.length,
      hasCorners: cornerData.length > 0,
    });

    if (!cornerData.length) {
      console.warn('[TrackMap] No corner data available - skipping corner rendering');
      return;
    }

    console.log('[TrackMap] Starting corner rendering for', cornerData.length, 'corners');

    const distance = (x1: number, y1: number, x2: number, y2: number) => Math.hypot(x2 - x1, y2 - y1);
    let runningDistance = 0;
    const startingPoint = pathNode.getPointAtLength(0);

    // First pass: calculate distances from start for animation delays
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
          currentY,
        );
      }

      corner.distanceFromStart = runningDistance;
    });

    // Second pass: render corners with calculated delays
    cornerData.forEach((corner: TrackCorner) => {
      const delayTime = this.findTimeToReachDistance(corner.distanceFromStart || 0, totalLength, animationDuration);
      const labelX = projectX(corner.text_position[0]);
      const labelY = projectY(corner.text_position[1]);

      svg
        .append('circle')
        .attr('cx', labelX)
        .attr('cy', labelY)
        .attr('r', 13)
        .attr('fill', '#FFFFFF')
        .attr('opacity', 0)
        .transition()
        .delay(delayTime)
        .attr('opacity', 1);

      svg
        .append('text')
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
        svg
          .append('text')
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

    console.log('[TrackMap] Finished rendering', cornerData.length, 'corners');
  }

  private findTimeToReachDistance(distance: number, totalLength: number, animationDuration: number): number {
    if (totalLength <= 0) {
      return 0;
    }

    const normalizedDistance = distance / totalLength;
    let tGuess = Math.min(Math.max(normalizedDistance, 0), 1);
    const epsilon = 1e-5;

    for (let i = 0; i < 100; i++) {
      const functionValue = 3 * tGuess ** 2 - 2 * tGuess ** 3 - normalizedDistance;
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

