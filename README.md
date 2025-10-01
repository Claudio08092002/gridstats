# GridStats

A modern Formula 1 statistics and visualization web application built with Angular and FastAPI.

## Features

- **Driver Comparison**: Compare two drivers' performance across an entire season
  - Head-to-head statistics
  - Race-by-race position analysis
  - Points progression charts
  - Qualifying vs race performance

- **Track Maps**: Interactive F1 circuit visualizations
  - Animated track drawings with corner numbers
  - Multiple layout variants per circuit
  - Historical track data (2018-2025)
  - Complete offline support

- **Season Data**: Browse historical F1 seasons
  - Driver standings
  - Constructor standings
  - Race results and winners

## Tech Stack

**Frontend:**
- Angular 19
- TypeScript
- D3.js for visualizations
- Server-side rendering (SSR)

**Backend:**
- FastAPI (Python)
- FastF1 library for F1 data
- JSON file caching for offline operation

## Getting Started

### Prerequisites

- Node.js 18+ and npm
- Python 3.11+
- Git

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Claudio08092002/gridstats.git
   cd gridstats
   ```

2. **Install backend dependencies:**
   ```bash
   cd backend
   pip install -r requirements.txt
   ```

3. **Install frontend dependencies:**
   ```bash
   cd ../frontend
   npm install
   ```

### Running Locally

**Backend:**
```bash
cd backend
uvicorn app.main:app --reload
```
Backend runs at: http://localhost:8000

**Frontend:**
```bash
cd frontend
npm start
```
Frontend runs at: http://localhost:4200

### Pre-populate Cache for Offline Deployment

For production deployments without internet access, you need to bundle track cache files with the frontend:

1. **Start the backend and populate cache:**
   ```bash
   cd backend
   uvicorn app.main:app --reload
   ```
   Then open: http://localhost:8000/f1/tracks/warmup
   
   Wait 5-15 minutes for all tracks to cache.

2. **Copy cache files to frontend assets:**
   ```powershell
   .\copy-cache-to-frontend.ps1
   ```
   
   This copies cache files from `backend/app/tracks_cache/` to `frontend/public/assets/tracks_cache/` so they're bundled in the Angular build.

3. **Rebuild frontend and Docker images:**
   ```bash
   cd frontend
   npm run build
   
   # Rebuild Docker images with updated cache
   docker-compose build
   ```

The app will now work **completely offline** - tracks load from bundled JSON files without any HTTP requests.

## Project Structure

```
gridstats/
├── frontend/               # Angular application
│   ├── src/
│   │   ├── app/
│   │   │   ├── components/    # UI components
│   │   │   ├── services/      # API services
│   │   │   └── models/        # TypeScript interfaces
│   │   └── styles.css
│   ├── angular.json
│   └── package.json
│
├── backend/                # FastAPI application
│   ├── app/
│   │   ├── routers/          # API endpoints
│   │   │   ├── compare.py    # Driver comparison
│   │   │   └── track.py      # Track maps
│   │   ├── services/         # Business logic
│   │   ├── season_cache/     # Cached season data
│   │   └── tracks_cache/     # Cached track data
│   ├── main.py
│   └── requirements.txt
│
└── docker-compose.yml      # Docker setup
```

## API Endpoints

**Tracks:**
- `GET /f1/tracks` - List all F1 tracks
- `GET /f1/trackmap/{year}/{round}` - Get track map for specific race
- `GET /f1/tracks/warmup` - Pre-populate all track cache

**Driver Comparison:**
- `GET /f1/compare` - Compare two drivers for a season

## Caching System

The app uses JSON file caching for optimal performance:

- **Season Cache**: Pre-built season data (2018-2025) in `backend/app/season_cache/`
- **Track Cache**: Track maps saved per circuit in `backend/app/tracks_cache/`
- **Offline Ready**: Works without internet once cache is populated

## Docker Deployment

```bash
docker-compose up -d
```

Access the app at: http://localhost:80

## Development

**Backend development:**
```bash
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Frontend development:**
```bash
cd frontend
npm start
```

**Build for production:**
```bash
cd frontend
npm run build
```

## Documentation

- **API Docs**: http://localhost:8000/docs (when backend is running)
- **Track Cache Guide**: See `HOW_TO_WARMUP.md` for offline setup

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature-name`
3. Commit changes: `git commit -am 'Add feature'`
4. Push to branch: `git push origin feature-name`
5. Open a Pull Request

## License

This project is licensed under the MIT License.

## Acknowledgments

- [FastF1](https://github.com/theOehrly/Fast-F1) - F1 data access library
- [Ergast API](http://ergast.com/mrd/) - Historical F1 data
- [D3.js](https://d3js.org/) - Data visualization

## Author

**Claudio**  
GitHub: [@Claudio08092002](https://github.com/Claudio08092002)

---
