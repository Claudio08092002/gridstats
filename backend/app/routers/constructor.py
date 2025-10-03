# backend/app/routers/constructor.py

from fastapi import APIRouter, Query, HTTPException
from typing import Dict, List, Any, Optional
import fastf1
from fastf1.ergast import Ergast
import pandas as pd
from pathlib import Path
import json
from collections import defaultdict
import time
import logging

from app.services.f1_utils import load_results_strict

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/f1/constructors")

CACHE_VERSION = "v5"  # Bumped to v5 for dynamic championship calculation
CONSTRUCTOR_CACHE_DIR = Path(__file__).resolve().parent.parent / "constructor_cache"
CONSTRUCTOR_CACHE_DIR.mkdir(exist_ok=True)


def _normalize_team_name(team_name: str) -> str:
    """
    Normalize team names to merge teams that are the same but had name changes.
    This ensures historical continuity for teams that briefly changed names.
    """
    # Red Bull and Red Bull Racing are the same team
    if team_name == 'Red Bull':
        return 'Red Bull Racing'
    
    return team_name


def _calculate_standings_by_year(constructors: dict) -> dict:
    """Calculate championship standings position for each constructor by year"""
    standings_by_year = {}
    
    # Collect all years
    all_years = set()
    for data in constructors.values():
        all_years.update(data['points_by_year'].keys())
    
    # For each year, calculate standings
    for year in all_years:
        # Get all constructors and their points for this year
        year_standings = []
        for team_name, data in constructors.items():
            points = data['points_by_year'].get(year, 0)
            year_standings.append((team_name, points))
        
        # Sort by points descending (highest points = position 1)
        year_standings.sort(key=lambda x: x[1], reverse=True)
        
        # Assign positions
        for position, (team_name, points) in enumerate(year_standings, 1):
            if team_name not in standings_by_year:
                standings_by_year[team_name] = {}
            # Only add positions for teams that actually competed (had points or participated)
            if points > 0 or team_name in constructors and year in constructors[team_name]['seasons']:
                standings_by_year[team_name][year] = position
    
    return standings_by_year


def _get_cache_path() -> Path:
    return CONSTRUCTOR_CACHE_DIR / "constructors_all_seasons.json"


def _read_cache() -> Optional[Dict[str, Any]]:
    cache_path = _get_cache_path()
    if not cache_path.exists():
        return None
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if data.get("version") == CACHE_VERSION:
                return data
    except Exception:
        pass
    return None


def _write_cache(data: Dict[str, Any]) -> None:
    cache_path = _get_cache_path()
    data["version"] = CACHE_VERSION
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        logger.info(f"Cache written successfully to {cache_path}")
    except Exception as e:
        logger.error(f"Failed to write constructor cache: {e}")


def _build_constructor_data() -> Dict[str, Any]:
    """Aggregate constructor statistics from 2018-2025 using the same reliable loading as compare.py"""
    
    logger.info("Building constructor data from 2018-2025...")
    constructors: Dict[str, Dict[str, Any]] = {}
    
    # Years to process - only completed seasons to avoid issues
    current_year = pd.Timestamp.now().year
    end_year = min(2025, current_year)  # Only up to current year
    years = list(range(2018, end_year + 1))
    
    for year in years:
        logger.info(f"Processing year {year}...")
        try:
            # Load the season schedule - same as compare.py
            schedule = fastf1.get_event_schedule(year, include_testing=False)
        except Exception as exc:
            logger.error(f"Failed to load schedule for {year}: {exc}")
            continue
        
        if schedule is None or schedule.empty:
            logger.warning(f"No schedule data for {year}")
            continue
        
        schedule = schedule.copy()
        if "RoundNumber" not in schedule.columns:
            logger.error(f"Schedule for {year} missing round information")
            continue
        
        schedule["RoundNumber"] = pd.to_numeric(schedule["RoundNumber"], errors="coerce")
        schedule = schedule.dropna(subset=["RoundNumber"])
        schedule = schedule.sort_values("RoundNumber")
        
        for _, event in schedule.iterrows():
            rnd_raw = event.get("RoundNumber")
            if pd.isna(rnd_raw):
                continue
            rnd = int(rnd_raw)
            event_name = str(event.get("EventName", f"Round {rnd}"))
            country = str(event.get("Country", ""))
            
            logger.info(f"  Processing {year} Round {rnd}: {event_name}")
            
            # Use load_results_strict - the same reliable method as compare.py
            try:
                _, df = load_results_strict(year, rnd)
            except Exception as e:
                logger.warning(f"    Failed to load results for {year} Round {rnd}: {e}")
                continue
            
            if df is None or df.empty:
                logger.info(f"    No results data for {year} Round {rnd}, skipping...")
                continue
            
            # Ensure numeric columns
            df["Points"] = pd.to_numeric(df.get("Points"), errors="coerce").fillna(0.0)
            df["Position"] = pd.to_numeric(df.get("Position"), errors="coerce")
            df["GridPosition"] = pd.to_numeric(df.get("GridPosition"), errors="coerce")
            
            # Process each result
            for _, row in df.iterrows():
                team_name = str(row.get('TeamName') or row.get('ConstructorName') or '')
                if not team_name or team_name == 'nan' or team_name.lower() == 'nan':
                    continue
                
                # Normalize team name (e.g., merge "Red Bull" with "Red Bull Racing")
                team_name = _normalize_team_name(team_name)
                
                # Initialize constructor entry if needed
                if team_name not in constructors:
                    constructors[team_name] = {
                        'name': team_name,
                        'total_points': 0,
                        'wins': 0,
                        'podiums': 0,
                        'poles': 0,
                        'seasons': set(),
                        'drivers': set(),
                        'drivers_by_year': {},  # Track which drivers drove in which year
                        'driver_race_counts': {},  # Track race count per driver per year
                        'points_by_year': {},
                        'points_by_race': {},  # Track points per race for best result
                        'wins_by_year': {},
                        'podiums_by_year': {},
                        'countries': set(),
                        'team_color': None,  # Store team color
                        'best_result': None,
                        'best_result_points': 0,
                    }
                
                constructor = constructors[team_name]
                
                # Store team color (first non-empty color we find)
                if not constructor['team_color']:
                    team_color = row.get('TeamColor')
                    if team_color and pd.notna(team_color):
                        color_str = str(team_color).strip()
                        if color_str and color_str.lower() != 'nan':
                            # Ensure it has # prefix
                            if not color_str.startswith('#'):
                                color_str = f'#{color_str}'
                            constructor['team_color'] = color_str
                
                # Add season and driver
                constructor['seasons'].add(year)
                driver_name = str(row.get('FullName') or row.get('BroadcastName') or row.get('Driver') or '')
                if driver_name and driver_name != 'nan' and driver_name.lower() != 'nan':
                    constructor['drivers'].add(driver_name)
                    # Track drivers by year
                    if year not in constructor['drivers_by_year']:
                        constructor['drivers_by_year'][year] = set()
                    constructor['drivers_by_year'][year].add(driver_name)
                    
                    # Track race counts per driver per year (for filtering fill-ins)
                    year_key = str(year)
                    if year_key not in constructor['driver_race_counts']:
                        constructor['driver_race_counts'][year_key] = {}
                    if driver_name not in constructor['driver_race_counts'][year_key]:
                        constructor['driver_race_counts'][year_key][driver_name] = 0
                    constructor['driver_race_counts'][year_key][driver_name] += 1
                
                # Add country
                if country and country != 'nan' and country.lower() != 'nan':
                    constructor['countries'].add(country)
                
                # Points
                points = float(row.get('Points', 0))
                constructor['total_points'] += points
                
                if year not in constructor['points_by_year']:
                    constructor['points_by_year'][year] = 0
                constructor['points_by_year'][year] += points
                
                # Track points by race for best result calculation (team total)
                race_key = f"{year}_{rnd}"
                if race_key not in constructor['points_by_race']:
                    constructor['points_by_race'][race_key] = {
                        'year': year,
                        'round': int(rnd),
                        'event': event_name,
                        'points': 0,
                        'drivers': []
                    }
                constructor['points_by_race'][race_key]['points'] += points
                if points > 0:
                    constructor['points_by_race'][race_key]['drivers'].append({
                        'name': driver_name,
                        'points': points,
                        'position': row.get('Position')
                    })
                
                # Position-based stats
                position = row.get('Position')
                if pd.notna(position):
                    try:
                        pos = int(float(position))
                        
                        # Wins
                        if pos == 1:
                            constructor['wins'] += 1
                            if year not in constructor['wins_by_year']:
                                constructor['wins_by_year'][year] = 0
                            constructor['wins_by_year'][year] += 1
                        
                        # Podiums
                        if pos <= 3:
                            constructor['podiums'] += 1
                            if year not in constructor['podiums_by_year']:
                                constructor['podiums_by_year'][year] = 0
                            constructor['podiums_by_year'][year] += 1
                    except (ValueError, TypeError):
                        pass
                
                # Grid position for poles
                grid_pos = row.get('GridPosition')
                if pd.notna(grid_pos):
                    try:
                        grid = int(float(grid_pos))
                        if grid == 1:
                            constructor['poles'] += 1
                    except (ValueError, TypeError):
                        pass
            
            # Try to add sprint points if available (like compare.py does)
            try:
                sprint_session = fastf1.get_session(year, rnd, 'S', backend='fastf1')
                sprint_session.load(laps=False, telemetry=False, weather=False, messages=False)
                sprint_results = sprint_session.results
                
                if sprint_results is not None and not sprint_results.empty:
                    sprint_results["Points"] = pd.to_numeric(sprint_results.get("Points"), errors="coerce").fillna(0.0)
                    
                    for _, sprint_row in sprint_results.iterrows():
                        sprint_points = float(sprint_row.get('Points', 0))
                        if sprint_points <= 0:
                            continue
                        
                        team_name = str(sprint_row.get('TeamName') or sprint_row.get('ConstructorName') or '')
                        if not team_name or team_name == 'nan' or team_name.lower() == 'nan':
                            continue
                        
                        if team_name in constructors:
                            constructors[team_name]['total_points'] += sprint_points
                            if year in constructors[team_name]['points_by_year']:
                                constructors[team_name]['points_by_year'][year] += sprint_points
            except Exception:
                # Sprint not available - that's fine, continue
                pass
    
    logger.info(f"Finished processing. Found {len(constructors)} constructors.")
    
    # Calculate championship standings for each year
    standings_by_year = _calculate_standings_by_year(constructors)
    
    # Convert sets to lists/counts and format data
    formatted_constructors = {}
    for team_name, data in constructors.items():
        # Find best result (highest team points in a single race)
        best_result = None
        best_points = 0
        for race_key, race_data in data['points_by_race'].items():
            if race_data['points'] > best_points:
                best_points = race_data['points']
                # Sort drivers by points in that race
                sorted_drivers = sorted(race_data['drivers'], key=lambda d: d['points'], reverse=True)
                best_result = {
                    'year': race_data['year'],
                    'round': race_data['round'],
                    'event': race_data['event'],
                    'points': round(race_data['points'], 2),
                    'drivers': [{'name': d['name'], 'points': d['points'], 'position': d['position']} for d in sorted_drivers]
                }
        
        # Format drivers by year for timeline (exclude fill-in drivers with <= 2 races)
        drivers_by_year_formatted = {}
        for year, drivers_set in data['drivers_by_year'].items():
            year_key = str(year)
            # Filter out drivers who only did 1-2 races (fill-ins)
            permanent_drivers = []
            if year_key in data['driver_race_counts']:
                for driver in drivers_set:
                    race_count = data['driver_race_counts'][year_key].get(driver, 0)
                    # Only include drivers who raced 3+ times (permanent drivers)
                    if race_count >= 3:
                        permanent_drivers.append(driver)
            drivers_by_year_formatted[year_key] = sorted(permanent_drivers)
        
        # Determine origin country - use known team origins first, fallback to None
        origin = None
        team_origins = {
            'Ferrari': 'Italy',
            'Red Bull Racing': 'Austria',
            'Mercedes': 'Germany',
            'McLaren': 'United Kingdom',
            'Alpine': 'France',
            'Aston Martin': 'United Kingdom',
            'Williams': 'United Kingdom',
            'AlphaTauri': 'Italy',
            'Alfa Romeo': 'Switzerland',
            'Haas F1 Team': 'United States',
            'Racing Point': 'United Kingdom',
            'Renault': 'France',
            'Toro Rosso': 'Italy',
            'Force India': 'India',
            'Sauber': 'Switzerland',
            'Kick Sauber': 'Switzerland',
            'RB': 'Italy',
        }
        
        # Check if team name matches known origins
        origin = team_origins.get(team_name, None)
        
        # Get standings positions for each year this constructor competed
        constructor_standings = standings_by_year.get(team_name, {})
        
        formatted_constructors[team_name] = {
            'name': data['name'],
            'team_color': data['team_color'] or '#888888',  # Default gray if no color
            'total_points': round(data['total_points'], 2),
            'wins': data['wins'],
            'podiums': data['podiums'],
            'poles': data['poles'],
            'season_count': len(data['seasons']),
            'seasons': sorted(list(data['seasons'])),
            'total_drivers': len(data['drivers']),
            'drivers': sorted(list(data['drivers'])),
            'drivers_by_year': drivers_by_year_formatted,
            'origin': origin,
            'points_by_year': {str(k): round(v, 2) for k, v in sorted(data['points_by_year'].items())},
            'wins_by_year': {str(k): v for k, v in sorted(data['wins_by_year'].items())},
            'podiums_by_year': {str(k): v for k, v in sorted(data['podiums_by_year'].items())},
            'best_result': best_result,
            'standings_by_year': {str(k): v for k, v in sorted(constructor_standings.items())},
        }
    
    return {
        'constructors': formatted_constructors,
        'years': years,
    }


@router.get("")
def list_constructors(refresh: bool = Query(False)):
    """Get list of all constructors from 2018-2025"""
    
    if not refresh:
        cached = _read_cache()
        if cached:
            logger.info("Returning cached constructor data")
            return cached
    
    # Build fresh data
    logger.info("Building fresh constructor data (this may take several minutes)...")
    data = _build_constructor_data()
    _write_cache(data)
    
    return data


@router.get("/compare")
def compare_constructors(
    constructor1: str = Query(..., description="First constructor name"),
    constructor2: str = Query(..., description="Second constructor name"),
    refresh: bool = Query(False)
):
    """Compare two constructors side by side"""
    
    # Get all constructor data
    all_data = list_constructors(refresh=refresh)
    constructors = all_data.get('constructors', {})
    
    c1_data = constructors.get(constructor1)
    c2_data = constructors.get(constructor2)
    
    if not c1_data:
        return {"error": f"Constructor '{constructor1}' not found"}
    if not c2_data:
        return {"error": f"Constructor '{constructor2}' not found"}
    
    return {
        'constructor1': c1_data,
        'constructor2': c2_data,
        'years': all_data.get('years', []),
    }
