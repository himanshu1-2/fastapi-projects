from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime


class Menu(SQLModel, table=True):
    __tablename__ = "menu"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    description: Optional[str] = None
    price: float = Field()
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)