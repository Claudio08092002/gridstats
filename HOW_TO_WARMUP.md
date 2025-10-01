# How to Pre-populate Track Cache

## Simple Instructions

1. **Start the backend server:**
   ```bash
   cd backend
   uvicorn app.main:app --reload
   ```

2. **Open this URL in your browser:**
   ```
   http://localhost:8000/f1/tracks/warmup
   ```
   
   Wait for JSON response (5-15 minutes)

3. **Done!** All cache files are now in `backend/app/tracks_cache/`

## What It Does

- Loads ALL tracks from `tracks_list.json`
- For each track, loads ALL years/rounds from FastF1 API
- Saves everything to `trackmap_{track_key}.json` files
- Returns a summary showing what was cached

## Response Example

```json
{
  "status": "completed",
  "summary": {
    "total_tracks": 36,
    "total_events": 250,
    "already_cached": 0,
    "newly_loaded": 250,
    "failed": 0
  },
  "tracks": [
    {
      "track": "Bahrain Grand Prix",
      "track_key": "bahrain_grand_prix",
      "total_events": 8,
      "loaded": 8,
      "cached": 0,
      "failed": 0,
      "errors": []
    }
  ]
}
```

That's it! Your app will now work completely offline in production.
