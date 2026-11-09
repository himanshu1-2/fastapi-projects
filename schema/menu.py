from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class MenuItemCreate(BaseModel):
    vendor_id: str
    name: str
    description: Optional[str] = None
    category: str
    is_active: Optional[bool] = True


class VendorSummary(BaseModel):
    slug: str
    name: str


class MenuItemRead(BaseModel):
    id: int
    vendor_id: str
    name: str
    description: Optional[str] = None
    category: str
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PublicVendorMenuItemRead(BaseModel):
    id: int
    vendor_id: str
    name: str
    description: Optional[str] = None
    category: str
    price: float
    available: bool = True

    model_config = ConfigDict(from_attributes=True)


class MenuItemUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    is_active: Optional[bool] = None


class DailyMenuItemCreate(BaseModel):
    vendor_id: str
    date: str
    menu_item_id: int
    price: float = Field(ge=0)
    stock_count: int = Field(default=0, ge=0)
    available: bool = True


class DailyMenuItemRead(BaseModel):
    id: int
    vendor_id: str
    date: str
    menu_item_id: int
    price: float
    stock_count: int
    available: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DailyMenuItemUpdate(BaseModel):
    price: Optional[float] = None
    stock_count: Optional[int] = None
    available: Optional[bool] = None


class MenuDelete(BaseModel):
    id: int
    is_active: bool = False