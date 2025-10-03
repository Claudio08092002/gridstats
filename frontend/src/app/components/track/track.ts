// Modified TrackComponent with localStorage caching

import { Component, OnDestroy, OnInit, inject, PLATFORM_ID } from '@angular/core';
import { CommonModule, isPlatformBrowser } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { HttpClientModule } from '@angular/common/http';
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
  imports: [CommonModule, FormsModule, HttpClientModule],
  templateUrl: './track.html',
  styleUrls: ['./track.css'],
})
export class TrackComponent implements OnInit, OnDestroy {
  private api = inject(ApiService);
  private platformId = inject(PLATFORM_ID);
  private readonly isBrowser = isPlatformBrowser(this.platformId);

  // Inject the HttpClient to allow loading cached files from the assets
  private http = inject(HttpClient);

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

  // Cache version - increment to invalidate all old cached data
  private readonly CACHE_VERSION = 3; // Bumped to 3 to clear after asset cache removal
  private readonly CACHE_VERSION_KEY = 'tracks_cache_version';

  /**
   * Generates a cache key for storing track map data in localStorage.  The
   * key includes the season year and round number to ensure unique
   * entries per event.  Keys are prefixed to avoid clashing with other
   * application data in storage.
   */
  private getCacheKey(year: number, round: number): string {
    // Prefix cache entries with the tracks_cache namespace so that
    // multiple components or libraries can safely coexist in
    // localStorage without key collisions.  Include the selected track
    // key when available.  Without the track key, caches for different
    // circuits might collide when they share the same year/round numbers
    // (e.g. two events both being round 1 in 2024).  Using both the
    // track key and the year/round ensures uniqueness.
    const trackKey = this.selectedKey ?? '';
    return `tracks_cache_v${this.CACHE_VERSION}_${trackKey}_${year}_${round}`;
  }

  /**
   * Check cache version and clear old cache if version has changed.
   * This ensures users get fresh data when the cache structure changes.
   */
  private checkAndClearOldCache(): void {
    if (!this.isBrowser) {
      return;
    }
    try {
      const storedVersion = window?.localStorage?.getItem(this.CACHE_VERSION_KEY);
      const currentVersion = this.CACHE_VERSION.toString();
      
      if (storedVersion !== currentVersion) {
        // Clear all old cache entries
        const keysToRemove: string[] = [];
        for (let i = 0; i < (window?.localStorage?.length ?? 0); i++) {
          const key = window?.localStorage?.key(i);
          if (key && key.startsWith('tracks_cache_')) {
            keysToRemove.push(key);
          }
        }
        keysToRemove.forEach(key => window?.localStorage?.removeItem(key));
        
        // Update version
        window?.localStorage?.setItem(this.CACHE_VERSION_KEY, currentVersion);
        console.log(`[Track Cache] Cleared old cache (v${storedVersion} → v${currentVersion})`);
      }
    } catch {
      // Ignore errors
    }
  }

  /**
   * Attempt to load cached track map data from localStorage.  This method
   * returns `null` when no cached entry exists or when executed in a
   * non‑browser environment (e.g. during SSR).
   */
  private loadFromCache(year: number, round: number): TrackMapResponse | null {
    if (!this.isBrowser) {
      return null;
    }
    try {
      const key = this.getCacheKey(year, round);
      const raw = window?.localStorage?.getItem(key);
      if (!raw) {
        return null;
      }
      return JSON.parse(raw) as TrackMapResponse;
    } catch {
      return null;
    }
  }

  /**
   * Persist the given track map response into localStorage.  Any errors
   * encountered during serialization or storage are silently ignored.  The
   * cached payload includes layout variants, winners and other metadata so
   * that subsequent requests can be served entirely from the client cache.
   */
  private saveToCache(year: number, round: number, data: TrackMapResponse): void {
    if (!this.isBrowser) {
      return;
    }
    try {
      const key = this.getCacheKey(year, round);
      const payload = JSON.stringify(data);
      window?.localStorage?.setItem(key, payload);
    } catch {
      // Ignore storage errors (e.g. quota exceeded)
    }
  }

  ngOnInit(): void {
    if (!this.isBrowser) {
      return;
    }
    // Check and clear old cache on init
    this.checkAndClearOldCache();
    
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

  /**
   * Convert hex color to rgba with opacity for winner backgrounds
   */
  getWinnerBackgroundColor(teamColor: string | undefined): string {
    if (!teamColor) {
      return 'rgba(255, 255, 255, 0.03)';
    }
    // Convert hex to rgba with 15% opacity
    const hex = teamColor.replace('#', '');
    const r = parseInt(hex.substring(0, 2), 16);
    const g = parseInt(hex.substring(2, 4), 16);
    const b = parseInt(hex.substring(4, 6), 16);
    return `rgba(${r}, ${g}, ${b}, 0.15)`;
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
    // Always update the variant and reload the map.  Even when the
    // signature matches the current selection the user might be toggling
    // between different rounds of the same layout.  For example, Abu
    // Dhabi has multiple versions of its layout with subtle corner
    // differences that share a signature once quantized in the backend.
    this.selectedVariantSignature = signature;
    const variant = this.layoutVariants.find((item) => item.layout_signature === signature);
    if (!variant) {
      return;
    }
    const targetRound = this.pickLatestRound(variant.rounds);
    if (targetRound) {
      // Always include layout information when reloading to refresh
      // variants and years even if the cached payload exists.
      this.loadTrackMap(targetRound, true);
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
    // Attempt to serve from client cache first.  If a cached entry is found
    // the map is drawn immediately and network requests are skipped.
    const cached = this.loadFromCache(roundRef.year, roundRef.round);
    if (cached) {
      this.loading = false;
      this.error = null;
      this.selectedRound = roundRef;
      this.selectedRoundKey = `${roundRef.year}-${roundRef.round}`;
      this.trackMap = cached;
      this.layoutVariants = cached.layout_variants ?? [];
      this.layoutYears = cached.layout_years ?? [];
      this.winners = cached.winners ?? [];
      // Update selected layout signature
      if (cached.layout_signature) {
        this.selectedVariantSignature = cached.layout_signature;
      } else if (this.layoutVariants.length) {
        this.selectedVariantSignature = this.layoutVariants[0].layout_signature;
      } else {
        this.selectedVariantSignature = null;
      }
      this.drawTrackMap(cached);
      return;
    }

    // Next, attempt to load from the precomputed cache stored in assets/tracks_cache.
    // This allows offline viewing on production deployments where external API
    // calls are not possible.  If the file exists and contains the requested
    // round entry, use it and avoid any HTTP calls to the backend.  The file
    // structure corresponds to the backend track cache bundle: a JSON object
    // with a `entries` dictionary keyed by "<year>-<round>".
    const sanitizedKey = this.sanitizeCacheKey(this.selectedKey ?? '');
    if (sanitizedKey) {
      const bundleUrl = `assets/tracks_cache/trackmap_${sanitizedKey}.json`;
      console.log(`[TRACK LOAD] Attempting to load from bundle: ${bundleUrl}`);
      this.http.get<any>(bundleUrl).subscribe({
        next: (bundle) => {
          console.log(`[TRACK LOAD] Bundle loaded successfully`, bundle);
          if (bundle && typeof bundle === 'object' && bundle.entries) {
            const key = `${roundRef.year}-${roundRef.round}`;
            let entry = bundle.entries[key];
            console.log(`[TRACK LOAD] Looking for entry ${key}, found:`, !!entry);
            
            // Fallback: if requested year-round doesn't exist, use the most recent cached entry
            if (!entry || !entry.track) {
              console.log(`[TRACK LOAD] Entry not found or invalid, trying fallback`);
              const entryKeys = Object.keys(bundle.entries || {});
              if (entryKeys.length > 0) {
                // Sort entries by year-round (descending) and pick the most recent
                const sortedKeys = entryKeys.sort((a, b) => {
                  const [yearA, roundA] = a.split('-').map(Number);
                  const [yearB, roundB] = b.split('-').map(Number);
                  if (yearA !== yearB) return yearB - yearA;
                  return roundB - roundA;
                });
                const fallbackKey = sortedKeys[0];
                entry = bundle.entries[fallbackKey];
                
                // Update roundRef to match the fallback entry
                if (entry && entry.track) {
                  const [fallbackYear, fallbackRound] = fallbackKey.split('-').map(Number);
                  const originalRound = `${roundRef.year}-${roundRef.round}`;
                  roundRef = { 
                    year: fallbackYear, 
                    round: fallbackRound,
                    event_name: entry.circuit_name || entry.layout_label || this.selectedTrack?.display_name || ''
                  };
                  console.log(`[TRACK FALLBACK] ${originalRound} not in cache, using ${fallbackYear}-${fallbackRound}`);
                }
              }
            }
            
            if (entry && entry.track) {
              console.log(`[TRACK LOAD] Using bundle entry, has all required fields:`, {
                track: !!entry.track,
                winners: !!entry.winners,
                layout_variants: !!entry.layout_variants,
                layout_years: !!entry.layout_years
              });
              // Merge the cached entry into a TrackMapResponse-like object.
              // Enhanced cache files now include winners, layout_variants, and layout_years!
              const fromBundle: TrackMapResponse = {
                track: entry.track,
                corners: entry.corners || [],
                layout_length: entry.layout_length,
                layout_label: entry.layout_label,
                layout_signature: entry.layout_signature,
                circuit_name: entry.circuit_name,
                // Use cached metadata if available (from enhanced warmup)
                winners: entry.winners || [],
                winner: entry.winner || null,
                layout_variants: entry.layout_variants || [],
                layout_years: entry.layout_years || (entry.year ? [entry.year] : []),
              };
              // Persist to localStorage for faster future access
              this.saveToCache(roundRef.year, roundRef.round, fromBundle);
              this.loading = false;
              this.error = null;
              this.selectedRound = roundRef;
              this.selectedRoundKey = `${roundRef.year}-${roundRef.round}`;
              this.trackMap = fromBundle;
              this.layoutVariants = fromBundle.layout_variants || [];
              this.layoutYears = fromBundle.layout_years || [];
              this.winners = fromBundle.winners || [];
              // Update selected layout signature
              if (fromBundle.layout_signature) {
                this.selectedVariantSignature = fromBundle.layout_signature;
              } else if (this.layoutVariants.length) {
                this.selectedVariantSignature = this.layoutVariants[0].layout_signature;
              } else {
                this.selectedVariantSignature = null;
              }
              this.drawTrackMap(fromBundle);
              return;
            }
          }
          // Not found in bundle; fall back to API call below
          this._loadTrackMapViaApi(roundRef, includeLayouts);
        },
        error: () => {
          // Bundle file not found or invalid; fall back to API call
          this._loadTrackMapViaApi(roundRef, includeLayouts);
        },
      });
      return;
    }

    // If we cannot determine a sanitized key, fall back to API call.
    this._loadTrackMapViaApi(roundRef, includeLayouts);
  }

  /**
   * Fallback logic to load a track map from the backend API when no local or
   * asset cache entry could be used.  This function contains the original
   * implementation for network requests and persists results to the client
   * cache.  It is extracted into a helper to avoid deeply nested
   * subscribe/callbacks in loadTrackMap.
   */
  private _loadTrackMapViaApi(roundRef: TrackRoundRef, includeLayouts: boolean): void {
    console.log(`[TRACK LOAD] Falling back to API for ${roundRef.year}-${roundRef.round}`);
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
        // Persist the payload in client cache.  Save under both the requested
        // year/round and the actual year/round reported by the backend as
        // described in the loadTrackMap comments.
        this.saveToCache(roundRef.year, roundRef.round, map);
        const saveYear = (map as any).year ?? roundRef.year;
        const saveRound = (map as any).round ?? roundRef.round;
        if (saveYear !== roundRef.year || saveRound !== roundRef.round) {
          this.saveToCache(saveYear, saveRound, map);
        }
      },
      error: (err) => {
        this.loading = false;
        this.error = err?.error?.detail ?? err?.message ?? 'Failed to load track map';
      },
    });
  }

  /**
   * Sanitize a track key to mirror the backend's cache file naming convention.
   * This ensures we construct the correct filename when attempting to load
   * trackmap bundles from the assets folder.  Non‑alphanumeric characters
   * become underscores and multiple underscores collapse.
   */
  private sanitizeCacheKey(raw: string): string {
    if (!raw) {
      return '';
    }
    // Match backend's _normalize_token logic exactly:
    // 1. Normalize to NFKD
    // 2. Remove accents (convert to ASCII-safe)
    // 3. Replace non-alphanumeric with underscores
    // 4. Strip leading/trailing underscores
    // 5. Convert to lowercase
    const normalized = raw
      .normalize('NFKD')
      .replace(/[\u0300-\u036f]/g, '') // Remove diacritics/accents
      .replace(/[^a-zA-Z0-9]+/g, '_')
      .replace(/^_+|_+$/g, '')
      .toLowerCase();
    return normalized || '';
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

    // Remove verbose logging in production.  Previously we logged details
    // about the number of track points, corners and layout metadata
    // whenever a map was drawn. These logs cluttered the console and
    // provided little value once the component was working reliably.

    if (!trackData.length) {
      // Nothing to draw when no coordinate data is present. Simply return
      // without logging a warning, since this scenario occurs naturally
      // when switching layouts or loading incomplete data.
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

    // The path animation completes here. In earlier revisions we emitted
    // diagnostic logs about the number of corners, but this is no
    // longer necessary.

    if (!cornerData.length) {
      // If the layout contains no corner metadata just return early. The
      // animation of the track outline has already completed.
      return;
    }

    // Start rendering the corner markers and labels. Removed verbose logging.

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

    // Corner rendering complete. No log emission.
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