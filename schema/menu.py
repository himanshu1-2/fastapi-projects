from datetime import datetime
from time import strftime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr
from pydantic.alias_generators import to_camel


class MenuCreate(BaseModel):
    name: str
    description: Optional[str] = None
    price: float
    is_active: Optional[bool] = True

class MenuRead(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    price: float
    created_at: datetime
    is_active: bool

    model_config = ConfigDict(
        alias_generator=to_camel,  # automatically convert python snake_case to camelCase e.g profile_picture -> profilePicture
        populate_by_name=True,  # allow you create an object either using the alias(e.g profilePicture) or original name( e,g profile_picture)
        from_attributes=True  # allow you read data directly from database. i.e allows you to pass a raw database object directly into your model
    ) 

class MenuUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None


class MenuDelete(BaseModel):
    id: int
    is_active: bool = False       