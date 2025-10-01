# DEPLOYMENT FIX - Tracks Not Loading

## Problem
The tracks weren't loading in production because the frontend was trying to load from `assets/tracks_cache/trackmap_*.json` files that didn't exist in the deployed Angular build.

## Solution
Copy the backend cache files to the frontend assets folder so they're bundled with the Angular build.

## What Changed

### 1. Created Copy Script
**File:** `copy-cache-to-frontend.ps1`
- Copies all JSON files from `backend/app/tracks_cache/` to `frontend/public/assets/tracks_cache/`
- Run this script after populating the backend cache with the warmup endpoint

### 2. Cache Files Now in Frontend
**Location:** `frontend/public/assets/tracks_cache/`
- Contains 37 JSON files (36 track maps + tracks_list.json)
- These files are automatically included in the Angular build
- Bundled into the Docker image - no volume mounts needed

### 3. Updated Documentation
- `README.md` - Added section on offline cache deployment
- `frontend/public/assets/tracks_cache/README.md` - Documents the cache system

## How to Deploy

### Step 1: Ensure Cache is Populated
```powershell
# Start backend locally
cd backend
uvicorn app.main:app --reload

# In browser, go to: http://localhost:8000/api/f1/tracks/warmup
# Wait 5-15 minutes for all tracks to cache
```

### Step 2: Copy Cache to Frontend
```powershell
# From project root
.\copy-cache-to-frontend.ps1
```

You should see:
```
Copying track cache files from backend to frontend...
  Copied: trackmap_70th_anniversary_grand_prix.json
  Copied: trackmap_abu_dhabi_grand_prix.json
  ...
Total files copied: 37
Frontend assets are now ready for offline deployment!
```

### Step 3: Commit and Push
```bash
git add copy-cache-to-frontend.ps1
git add frontend/public/assets/
git add README.md
git add backend/app/routers/track.py
git add docker-compose.portainer.yml
git commit -m "Add offline track cache to frontend assets"
git push origin main
```

### Step 4: Rebuild Docker Images
```bash
# Build and push new images
docker-compose build

# If you're using Docker Hub:
docker tag gridstats-backend:latest claudio08092002/gridstats-backend:latest
docker tag gridstats-frontend:latest claudio08092002/gridstats-frontend:latest
docker push claudio08092002/gridstats-backend:latest
docker push claudio08092002/gridstats-frontend:latest
```

### Step 5: Redeploy in Portainer
1. Stop your current stack
2. Update the stack (it will pull the new images)
3. Start the stack again

## How It Works

### Frontend Loading Strategy (track.component.ts)
The frontend tries to load track data in this order:

1. **localStorage cache** (from previous visits)
2. **Bundled assets** (`assets/tracks_cache/trackmap_{track_key}.json`)
3. **Backend API** (only as fallback)

For offline deployment, the bundled assets are used, so no HTTP requests are needed.

### What Gets Bundled
All files in `frontend/public/` are copied to the Angular dist folder during build:
- `public/assets/tracks_cache/*.json` → `dist/browser/assets/tracks_cache/*.json`

The Docker image contains these files, making the app **completely offline**.

## Verification

After deploying, verify the cache files are accessible:
```bash
# Check if files exist in the container
docker exec <container-name> ls -la /usr/share/nginx/html/assets/tracks_cache/
```

You should see 37 JSON files.

## Important Notes

1. **Don't mount volumes** for `tracks_cache` or `season_cache` in docker-compose - they should be bundled in the image
2. **Run the copy script** every time you update the backend cache with new race data
3. **Rebuild the frontend Docker image** after copying new cache files
4. The cache files are ~5MB total, which is acceptable for bundling

## Testing Locally

To test the offline behavior locally:
1. Copy cache files: `.\copy-cache-to-frontend.ps1`
2. Build frontend: `cd frontend; npm run build`
3. Serve the build: `npx http-server dist/browser`
4. Open browser and check Network tab - no `/trackmap` requests should be made
