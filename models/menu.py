from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, UniqueConstraint
from sqlmodel import Field, SQLModel


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True, max_length=254)
    password_hash: str = Field(max_length=256)
    role: str = Field(default="vendor", max_length=16, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Vendor(SQLModel, table=True):
    __tablename__ = "vendors"

    id: Optional[int] = Field(default=None, primary_key=True)
    slug: str = Field(index=True, unique=True, max_length=100)
    name: str = Field(max_length=200)
    owner_user_id: int = Field(foreign_key="users.id", index=True, unique=True)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AuthSession(SQLModel, table=True):
    __tablename__ = "auth_sessions"

    token_hash: str = Field(primary_key=True, max_length=64)
    user_id: int = Field(foreign_key="users.id", index=True)
    expires_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False, index=True))
    created_at: datetime = Field(default_factory=datetime.utcnow)


class MenuItem(SQLModel, table=True):
    __tablename__ = "menu_items"

    id: Optional[int] = Field(default=None, primary_key=True)
    vendor_id: str = Field(index=True)
    name: str = Field(index=True)
    description: Optional[str] = None
    category: str = Field(index=True)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class DailyMenuItem(SQLModel, table=True):
    __tablename__ = "daily_menu_items"
    __table_args__ = (
        UniqueConstraint("vendor_id", "date", "menu_item_id", name="uq_vendor_daily_menu_item"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    vendor_id: str = Field(index=True)
    date: str = Field(index=True)
    menu_item_id: int = Field(foreign_key="menu_items.id", index=True)
    price: float = Field()
    stock_count: int = Field(default=0)
    available: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)