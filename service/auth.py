import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta, timezone

from database import get_session
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.menu import AuthSession, MenuItem, User, Vendor

router = APIRouter(prefix="/auth", tags=["authentication"])

SESSION_COOKIE = "qr_menu_session"
SESSION_DURATION = timedelta(days=7)
SESSION_MAX_AGE = int(SESSION_DURATION.total_seconds())
PASSWORD_ITERATIONS = 310_000
SESSION_SECURE = os.getenv("AUTH_COOKIE_SECURE", "false").strip().lower() == "true"
FRONTEND_ORIGINS = {
    origin.strip()
    for origin in os.getenv(
        "FRONTEND_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")
    if origin.strip()
}


class VendorRegistration(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=128)
    restaurant_name: str = Field(min_length=2, max_length=200)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
            raise ValueError("Enter a valid email address")
        return normalized

    @field_validator("restaurant_name")
    @classmethod
    def normalize_restaurant_name(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 2:
            raise ValueError("Restaurant name must contain at least 2 characters")
        return normalized


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
            raise ValueError("Enter a valid email address")
        return normalized


def hash_password(password: str, salt: bytes | None = None) -> str:
    actual_salt = salt or secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), actual_salt, PASSWORD_ITERATIONS
    )
    return f"{actual_salt.hex()}:{derived.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        salt_hex, expected_hex = password_hash.split(":", maxsplit=1)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(expected_hex)
    except (ValueError, TypeError):
        return False

    actual = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS
    )
    return hmac.compare_digest(actual, expected)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _slug_base(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return (slug or "restaurant")[:90].rstrip("-")


async def _new_vendor_slug(name: str, session: AsyncSession) -> str:
    base = _slug_base(name)
    candidate = base
    suffix = 2
    while True:
        existing_vendor = await session.execute(select(Vendor.id).where(Vendor.slug == candidate))
        existing_menu = await session.execute(select(MenuItem.id).where(MenuItem.vendor_id == candidate).limit(1))
        if existing_vendor.scalar_one_or_none() is None and existing_menu.scalar_one_or_none() is None:
            return candidate
        candidate = f"{base[:88]}-{suffix}"
        suffix += 1


async def _issue_session(user: User, response: Response, session: AsyncSession) -> None:
    token = secrets.token_urlsafe(48)
    session.add(
        AuthSession(
            token_hash=_token_hash(token),
            user_id=user.id,
            expires_at=datetime.now(timezone.utc) + SESSION_DURATION,
        )
    )
    await session.commit()
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=SESSION_SECURE,
        samesite="lax",
        path="/",
    )


async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Login required")

    auth_session = await session.get(AuthSession, _token_hash(token))
    now = datetime.now(timezone.utc)
    if auth_session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session is invalid")

    expires_at = auth_session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= now:
        await session.delete(auth_session)
        await session.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session has expired")

    user = await session.get(User, auth_session.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account no longer exists")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator access required")
    return user


def require_trusted_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin and origin not in FRONTEND_ORIGINS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Untrusted request origin")


async def _user_payload(user: User, session: AsyncSession) -> dict[str, object]:
    vendor_result = await session.execute(select(Vendor).where(Vendor.owner_user_id == user.id))
    vendor = vendor_result.scalar_one_or_none()
    return {
        "id": user.id,
        "email": user.email,
        "role": user.role,
        "vendor_id": vendor.slug if vendor else None,
        "vendor_name": vendor.name if vendor else None,
    }


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register_vendor(
    payload: VendorRegistration,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    require_trusted_origin(request)
    existing = await session.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists")

    try:
        user = User(email=payload.email, password_hash=hash_password(payload.password), role="vendor")
        session.add(user)
        await session.flush()
        slug = await _new_vendor_slug(payload.restaurant_name, session)
        session.add(Vendor(slug=slug, name=payload.restaurant_name, owner_user_id=user.id))
        await _issue_session(user, response, session)
    except IntegrityError as error:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Account could not be created; retry with different details") from error

    return await _user_payload(user, session)


@router.post("/login")
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    require_trusted_origin(request)
    result = await session.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    await _issue_session(user, response, session)
    return await _user_payload(user, session)


@router.get("/me")
async def current_user(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await _user_payload(user, session)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    require_trusted_origin(request)
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        auth_session = await session.get(AuthSession, _token_hash(token))
        if auth_session is not None:
            await session.delete(auth_session)
            await session.commit()
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, secure=SESSION_SECURE, samesite="lax")
