# Track Map Cache Files

This directory contains pre-computed track map data for offline deployment.

## Purpose
These JSON files are copied from the backend cache (`backend/app/tracks_cache/`) to allow the Angular frontend to work **completely offline** in production. When a user selects a track, the frontend first checks these bundled files before making any HTTP requests.

## Structure
- `trackmap_{track_key}.json` - Track map data for each circuit
- `tracks_list.json` - Index of all available tracks

Each trackmap file contains entries keyed by `"{year}-{round}"` with track coordinates, corners, and layout metadata.

## Updating Cache Files
When new race data becomes available, run the warmup endpoint to populate the backend cache, then copy files to frontend:

```powershell
# From project root
.\copy-cache-to-frontend.ps1
```

This ensures production deployments have the latest track data bundled with the Angular build.

## Docker Deployment
These files are automatically included in the frontend Docker image because they're in the `public/` directory, which is copied during the build process. No volume mounts are needed - the cache files are **bundled into the image**.
