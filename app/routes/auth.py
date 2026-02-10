
# app/routes/auth.py
from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status, Header
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.database import get_db
from app.models.building import Building
from app.models.user import User
from app.models.city import City
from app.models.session import SessionToken

bearer_scheme = HTTPBearer()
router = APIRouter(prefix="/auth", tags=["auth"])

# Pi-friendly hashing (no native deps)
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

SESSION_HOURS = 24


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8, max_length=128)
    city_name: str = Field(default="Capital", min_length=1, max_length=40)


class RegisterResponse(BaseModel):
    user_id: int
    username: str
    city_id: int
    city_name: str


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    token_type: str = "bearer"
    expires_at: datetime


class MeResponse(BaseModel):
    user_id: int
    username: str
    cities: list[dict]


def _now_utc_naive() -> datetime:
    # Naive UTC datetime (no tzinfo). Works cleanly with SQLite.
    return datetime.utcnow()


def _extract_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2:
        return None
    scheme, value = parts[0].lower(), parts[1].strip()
    if scheme != "bearer" or not value:
        return None
    return value


def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    token = creds.credentials  # this replaces your header parsing

    sess = db.query(SessionToken).filter(SessionToken.token == token).first()
    if not sess:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    if sess.expires_at <= _now_utc_naive():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")

    user = db.query(User).filter(User.id == sess.user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session user")

    return user

@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> RegisterResponse:
    existing = db.query(User).filter(User.username == payload.username).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")

    user = User(
        username=payload.username,
        password_hash=pwd_context.hash(payload.password),
    )
    db.add(user)
    db.flush()

    city = City(
        owner_id=user.id,
        name=payload.city_name,
        townhall_level=1,
        food=500,
        wood=500,
        stone=500,
        iron=500,
    )
    db.add(city)
    db.flush()  # ensures city.id is available

    starter_types = [
        "townhall",
        "farm",
        "sawmill",
        "quarry",
        "ironmine",
        "warehouse",
        "academy",
        "barracks",
    ]

    for t in starter_types:
        db.add(Building(city_id=city.id, type=t, level=1))

    db.commit()
    db.refresh(user)
    db.refresh(city)

    return RegisterResponse(
        user_id=user.id,
        username=user.username,
        city_id=city.id,
        city_name=city.name,
    )


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    user = db.query(User).filter(User.username == payload.username).first()
    if not user or not pwd_context.verify(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    token = secrets.token_hex(32)
    expires_at = _now_utc_naive() + timedelta(hours=SESSION_HOURS)

    sess = SessionToken(
        user_id=user.id,
        token=token,
        created_at=_now_utc_naive(),
        expires_at=expires_at,

    )
    db.add(sess)
    db.commit()

    return LoginResponse(token=token, expires_at=expires_at)


@router.get("/me", response_model=MeResponse)
def me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> MeResponse:
    cities = db.query(City).filter(City.owner_id == current_user.id).all()
    return MeResponse(
        user_id=current_user.id,
        username=current_user.username,
        cities=[
            {
                "city_id": c.id,
                "name": c.name,
                "townhall_level": c.townhall_level,
                "food": c.food,
                "wood": c.wood,
                "stone": c.stone,
                "iron": c.iron,
            }
            for c in cities
        ],
    )
