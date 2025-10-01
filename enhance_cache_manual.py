"""
Quick script to add metadata to existing cache files
"""
import json
from pathlib import Path
from typing import Dict, Any, List

# Load tracks list to get events
tracks_list_path = Path("backend/app/tracks_cache/tracks_list.json")
with open(tracks_list_path, 'r', encoding='utf-8') as f:
    tracks_data = json.load(f)
    tracks = tracks_data.get("tracks", [])

# Load season cache for winners
season_cache_root = Path("backend/app/season_cache")

def get_winner(year: int, round_num: int) -> Dict[str, Any]:
    """Get winner from season cache"""
    season_path = season_cache_root / f"season_{year}.json"
    if not season_path.exists():
        return None
    
    with open(season_path, 'r', encoding='utf-8') as f:
        season_data = json.load(f)
    
    races = season_data.get("races", [])
    for race in races:
        if race.get("round") == round_num:
            winner = race.get("winner", {})
            if winner:
                return {
                    "year": year,
                    "round": round_num,
                    "driver": winner.get("driver"),
                    "team": winner.get("team"),
                    "code": winner.get("code")
                }
    return None

# Process each track
enhanced_count = 0
for track in tracks:
    track_key = track.get("key")
    track_name = track.get("display_name", track_key)
    events = track.get("events", [])
    
    # Load cache file
    cache_path = Path(f"backend/app/tracks_cache/trackmap_{track_key}.json")
    if not cache_path.exists():
        print(f"[SKIP] {track_name}: No cache file")
        continue
    
    with open(cache_path, 'r', encoding='utf-8') as f:
        cache_bundle = json.load(f)
    
    entries = cache_bundle.get("entries", {})
    if not entries:
        print(f"[SKIP] {track_name}: No entries")
        continue
    
    # Collect all winners for this track
    all_winners = []
    for event in events:
        year = event.get("year")
        round_num = event.get("round")
        winner = get_winner(year, round_num)
        if winner:
            all_winners.append(winner)
    
    # Collect layout variants from cached entries
    layout_map = {}
    for entry_key, entry_data in entries.items():
        signature = entry_data.get("layout_signature", entry_key)
        if signature not in layout_map:
            layout_map[signature] = {
                "layout_signature": signature,
                "layout_label": entry_data.get("layout_label"),
                "layout_length": entry_data.get("layout_length"),
                "circuit_name": entry_data.get("circuit_name"),
                "years": set(),
                "rounds": []
            }
        
        year, round_num = entry_key.split('-')
        year = int(year)
        round_num = int(round_num)
        layout_map[signature]["years"].add(year)
        layout_map[signature]["rounds"].append({"year": year, "round": round_num})
    
    # Convert layout_map to list
    layout_variants = []
    for signature, info in layout_map.items():
        layout_variants.append({
            "layout_signature": signature,
            "layout_label": info["layout_label"],
            "layout_length": info["layout_length"],
            "circuit_name": info["circuit_name"],
            "years": sorted(list(info["years"])),
            "rounds": info["rounds"]
        })
    
    # Update each entry with metadata
    modified = False
    for entry_key, entry_data in entries.items():
        if entry_data.get("winners"):
            continue  # Already has metadata
        
        year_str, round_str = entry_key.split('-')
        year = int(year_str)
        round_num = int(round_str)
        
        # Find winner for this event
        winner = next((w for w in all_winners if w["year"] == year and w["round"] == round_num), None)
        
        # Add metadata
        entry_data["winners"] = all_winners
        entry_data["winner"] = winner
        entry_data["layout_variants"] = layout_variants
        
        # Layout years for this specific signature
        current_signature = entry_data.get("layout_signature")
        if current_signature and current_signature in layout_map:
            entry_data["layout_years"] = sorted(list(layout_map[current_signature]["years"]))
        else:
            entry_data["layout_years"] = [year]
        
        modified = True
    
    if modified:
        # Save updated cache
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(cache_bundle, f, indent=2)
        
        enhanced_count += 1
        print(f"[ENHANCED] {track_name}: {len(entries)} entries updated")

print(f"\n✅ Enhanced {enhanced_count} track cache files!")
