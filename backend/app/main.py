# backend/app/main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import compare, track


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
