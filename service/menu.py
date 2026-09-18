from database import get_session
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from models.menu import Menu
from schema.menu import MenuCreate, MenuRead
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

router = APIRouter(prefix="/menu", tags=["menu"])


@router.post("/", response_model=MenuRead)
async def create_menu(menu: MenuCreate, session: AsyncSession = Depends(get_session)):
    db_menu = Menu(**menu.model_dump())
    session.add(db_menu)
    await session.commit()
    await session.refresh(db_menu)
    return db_menu


@router.get("/", response_model=list[MenuRead])
async def list_menu(
    name: str | None = Query(None, description="Filter by menu name"),
    skip: int = Query(0, ge=0, description="Number of menu items to skip"),
    limit: int = Query(10, ge=1, le=50, description="Max menu items to return"),
    session: AsyncSession = Depends(get_session),
):
    query = select(Menu)

    if name:
        query = query.where(Menu.name == name)

    query = query.offset(skip).limit(limit)
    result = await session.execute(query)
    return result.scalars().all()


@router.patch("/{menu_id}", response_model=MenuRead)
async def update_menu(
    menu_id: int,
    menu: MenuCreate,
    session: AsyncSession = Depends(get_session),
):
    db_menu = await session.get(Menu, menu_id)
    if not db_menu:
        raise HTTPException(status_code=404, detail="Menu item not found")

    for key, value in menu.model_dump().items():
        setattr(db_menu, key, value)

    session.add(db_menu)
    await session.commit()
    await session.refresh(db_menu)
    return db_menu


@router.get("/{menu_id}", response_model=MenuRead)
async def get_menu(menu_id: int, session: AsyncSession = Depends(get_session)):
    db_menu = await session.get(Menu, menu_id)
    if not db_menu:
        raise HTTPException(status_code=404, detail="Menu item not found")
    return db_menu


@router.delete("/{menu_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_menu(menu_id: int, session: AsyncSession = Depends(get_session)):
    db_menu = await session.get(Menu, menu_id)
    if not db_menu:
        raise HTTPException(status_code=404, detail="Menu item not found")

    await session.delete(db_menu)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)