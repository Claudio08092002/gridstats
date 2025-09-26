# backend/app/main.py
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import compare, track

# Raise the global log level so module INFO logs and uvicorn access logs are visible.
root_logger = logging.getLogger()
if root_logger.level > logging.INFO:
    root_logger.setLevel(logging.INFO)
logging.getLogger("uvicorn.access").setLevel(logging.INFO)
logging.getLogger("uvicorn.error").setLevel(logging.INFO)

ALLOWED_ORIGINS = [
    "http://localhost:4200",
    "https://claudio.stefanhohl.ch",
]
ALLOWED_ORIGIN_REGEX = r"^https://(?:.+\.)?stefanhohl\.ch$"

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=ALLOWED_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(compare.router, prefix="/api")
app.include_router(track.router, prefix="/api")

@app.get("/healthz")
@app.get("/api/healthz")
def healthz():
    return {"status": "ok"}
