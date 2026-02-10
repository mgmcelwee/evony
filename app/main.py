# app/main.py
from __future__ import annotations

from fastapi import FastAPI
from sqlalchemy import text

from app.database import engine
from app.routes.auth import router as auth_router
from app.routes.game import router as game_router
from app.routes.buildings import router as buildings_router
from app.routes.cities import router as cities_router
from app.routes import raids
from app.routes import mail
from fastapi.security import HTTPBearer

app = FastAPI(title="Evony-like Server", version="0.2.0")

app.include_router(auth_router)
app.include_router(game_router)
app.include_router(buildings_router)
app.include_router(cities_router)
app.include_router(raids.router)
app.include_router(mail.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/db-ping")
def db_ping() -> dict:
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1")).scalar_one()
    return {"db": "ok", "select_1": result}
