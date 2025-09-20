from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="GridStats API", version="0.1.0")

# CORS: Angular Dev-Server zulassen
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200", "http://127.0.0.1:4200"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Basic endpoints ---

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/drivers")
def list_drivers():
    # Platzhalter: später aus FastF1/DB
    return [
        {"id": "1", "name": "Max Verstappen"},
        {"id": "44", "name": "Lewis Hamilton"},
        {"id": "16", "name": "Charles Leclerc"},
        {"id": "55", "name": "Carlos Sainz"},
    ]

@app.get("/f1/race/{year}/{round_number}")
def race_results(year: int, round_number: int):
    # Platzhalter – später echte Daten (FastF1)
    if year < 1950:
        raise HTTPException(status_code=400, detail="invalid season")
    return {
        "year": year,
        "round": round_number,
        "results": [
            {"position": 1, "driver": "1", "name": "Max Verstappen", "points": 25},
            {"position": 2, "driver": "16", "name": "Charles Leclerc", "points": 18},
        ],
    }
