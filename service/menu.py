from datetime import datetime

from database import get_session
from models.menu import DailyMenuItem, MenuItem
from schema.menu import (
    DailyMenuItemCreate,
    DailyMenuItemRead,
    DailyMenuItemUpdate,
    MenuDelete,
    MenuItemCreate,
    MenuItemRead,
    MenuItemUpdate,
    PublicVendorMenuItemRead,
    VendorSummary,
)
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi import Request
from service.auth import get_current_user, require_trusted_origin
from models.menu import User, Vendor

router = APIRouter(prefix="/menu", tags=["menu"])


@router.post("/items", response_model=MenuItemRead)
async def create_menu_item(
    menu: MenuItemCreate,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    require_trusted_origin(request)
    await ensure_vendor_access(menu.vendor_id, user, session)
    db_menu = MenuItem(**menu.model_dump())
    session.add(db_menu)
    await session.commit()
    await session.refresh(db_menu)
    return db_menu


@router.get("/vendors", response_model=list[VendorSummary])
async def list_vendors(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Vendor).where(Vendor.is_active.is_(True)).order_by(Vendor.name))
    vendors = result.scalars().all()
    vendors_by_slug = {vendor.slug: vendor.name for vendor in vendors}

    legacy_result = await session.execute(
        select(MenuItem.vendor_id)
        .where(MenuItem.is_active.is_(True))
        .distinct()
        .order_by(MenuItem.vendor_id)
    )
    for vendor_id in legacy_result.scalars().all():
        vendors_by_slug.setdefault(vendor_id, vendor_id)
    return [
        VendorSummary(slug=vendor_id, name=name)
        for vendor_id, name in sorted(vendors_by_slug.items(), key=lambda item: item[1].casefold())
    ]


async def ensure_vendor_access(vendor_id: str, user: User, session: AsyncSession) -> None:
    if user.role == "admin":
        return
    result = await session.execute(
        select(Vendor.id).where(
            Vendor.slug == vendor_id,
            Vendor.owner_user_id == user.id,
            Vendor.is_active.is_(True),
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You cannot access this vendor")


@router.get("/items/{vendor_id}", response_model=list[MenuItemRead])
async def list_menu_items(
    vendor_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await ensure_vendor_access(vendor_id, user, session)
    query = select(MenuItem).where(MenuItem.vendor_id == vendor_id, MenuItem.is_active.is_(True))
    result = await session.execute(query)
    return result.scalars().all()


@router.get("/items/{vendor_id}/previously-used", response_model=list[MenuItemRead])
async def list_previously_used_menu_items(
    vendor_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await ensure_vendor_access(vendor_id, user, session)
    query = (
        select(MenuItem)
        .join(DailyMenuItem, DailyMenuItem.menu_item_id == MenuItem.id)
        .where(
            MenuItem.vendor_id == vendor_id,
            MenuItem.is_active.is_(True),
            DailyMenuItem.vendor_id == vendor_id,
        )
        .distinct()
        .order_by(MenuItem.name)
    )
    result = await session.execute(query)
    return result.scalars().all()


@router.patch("/items/{menu_item_id}", response_model=MenuItemRead)
async def update_menu_item(
    menu_item_id: int,
    menu: MenuItemUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    require_trusted_origin(request)
    db_menu = await session.get(MenuItem, menu_item_id)
    if not db_menu:
        raise HTTPException(status_code=404, detail="Menu item not found")
    await ensure_vendor_access(db_menu.vendor_id, user, session)

    for key, value in menu.model_dump(exclude_unset=True).items():
        setattr(db_menu, key, value)

    await session.commit()
    await session.refresh(db_menu)
    return db_menu


@router.get("/daily/{vendor_id}/{date}", response_model=list[DailyMenuItemRead])
async def list_daily_menu(
    vendor_id: str,
    date: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    await ensure_vendor_access(vendor_id, user, session)
    query = select(DailyMenuItem).where(DailyMenuItem.vendor_id == vendor_id, DailyMenuItem.date == date)
    result = await session.execute(query)
    return result.scalars().all()


@router.post("/daily/{vendor_id}", response_model=list[DailyMenuItemRead])
async def upsert_daily_menu(
    vendor_id: str,
    payload: list[DailyMenuItemCreate],
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    require_trusted_origin(request)
    await ensure_vendor_access(vendor_id, user, session)
    if not payload:
        return []

    item_ids: set[int] = set()
    for item in payload:
        if item.vendor_id != vendor_id:
            raise HTTPException(400, detail="Vendor mismatch")
        if item.menu_item_id in item_ids:
            raise HTTPException(status_code=400, detail="A menu item may only appear once per daily menu")
        item_ids.add(item.menu_item_id)
        catalog_result = await session.execute(
            select(MenuItem.id).where(
                MenuItem.id == item.menu_item_id,
                MenuItem.vendor_id == vendor_id,
                MenuItem.is_active.is_(True),
            )
        )
        if catalog_result.scalar_one_or_none() is None:
            raise HTTPException(status_code=400, detail="Daily menu item must be an active item for this vendor")

        existing = await session.execute(
            select(DailyMenuItem).where(
                DailyMenuItem.vendor_id == vendor_id,
                DailyMenuItem.date == item.date,
                DailyMenuItem.menu_item_id == item.menu_item_id,
            )
        )
        db_item = existing.scalar_one_or_none()

        if db_item:
            db_item.price = item.price
            db_item.stock_count = item.stock_count
            db_item.available = item.available
            db_item.updated_at = datetime.utcnow()
            session.add(db_item)
        else:
            session.add(
                DailyMenuItem(
                    vendor_id=item.vendor_id,
                    date=item.date,
                    menu_item_id=item.menu_item_id,
                    price=item.price,
                    stock_count=item.stock_count,
                    available=item.available,
                )
            )

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Duplicate daily menu entry for the same vendor/date/item")

    result = await session.execute(
        select(DailyMenuItem).where(
            DailyMenuItem.vendor_id == vendor_id,
            DailyMenuItem.date.in_([entry.date for entry in payload]),
        )
    )
    return result.scalars().all()


@router.put("/daily/{vendor_id}/{date}", response_model=list[DailyMenuItemRead])
async def replace_daily_menu(
    vendor_id: str,
    date: str,
    payload: list[DailyMenuItemCreate],
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    require_trusted_origin(request)
    await ensure_vendor_access(vendor_id, user, session)
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Date must use YYYY-MM-DD format") from error

    if len({item.menu_item_id for item in payload}) != len(payload):
        raise HTTPException(status_code=400, detail="A menu item may only appear once per daily menu")

    for item in payload:
        if item.vendor_id != vendor_id or item.date != date:
            raise HTTPException(status_code=400, detail="Vendor or date mismatch")
        catalog_result = await session.execute(
            select(MenuItem.id).where(
                MenuItem.id == item.menu_item_id,
                MenuItem.vendor_id == vendor_id,
                MenuItem.is_active.is_(True),
            )
        )
        if catalog_result.scalar_one_or_none() is None:
            raise HTTPException(status_code=400, detail="Daily menu item must be an active item for this vendor")

    existing_result = await session.execute(
        select(DailyMenuItem).where(DailyMenuItem.vendor_id == vendor_id, DailyMenuItem.date == date)
    )
    existing_items = existing_result.scalars().all()
    payload_by_item_id = {item.menu_item_id: item for item in payload}

    for existing in existing_items:
        item = payload_by_item_id.pop(existing.menu_item_id, None)
        if item is None:
            await session.delete(existing)
        else:
            existing.price = item.price
            existing.stock_count = item.stock_count
            existing.available = item.available
            existing.updated_at = datetime.utcnow()

    for item in payload_by_item_id.values():
        session.add(
            DailyMenuItem(
                vendor_id=vendor_id,
                date=date,
                menu_item_id=item.menu_item_id,
                price=item.price,
                stock_count=item.stock_count,
                available=item.available,
            )
        )

    await session.commit()
    result = await session.execute(
        select(DailyMenuItem)
        .where(DailyMenuItem.vendor_id == vendor_id, DailyMenuItem.date == date)
        .order_by(DailyMenuItem.id)
    )
    return result.scalars().all()


@router.get("/{vendor_id}/today", response_model=list[PublicVendorMenuItemRead])
async def public_vendor_menu_today(
    vendor_id: str,
    session: AsyncSession = Depends(get_session),
):
    today = datetime.utcnow().strftime("%Y-%m-%d")

    statement = (
        select(
            MenuItem.id,
            MenuItem.vendor_id,
            MenuItem.name,
            MenuItem.description,
            MenuItem.category,
            DailyMenuItem.price,
            DailyMenuItem.available,
        )
        .join(DailyMenuItem, DailyMenuItem.menu_item_id == MenuItem.id)
        .where(
            MenuItem.vendor_id == vendor_id,
            MenuItem.is_active.is_(True),
            DailyMenuItem.vendor_id == vendor_id,
            DailyMenuItem.date == today,
            DailyMenuItem.available.is_(True),
        )
    )
    result = await session.execute(statement)
    rows = result.all()

    return [
        PublicVendorMenuItemRead(
            id=row[0],
            vendor_id=row[1],
            name=row[2],
            description=row[3],
            category=row[4],
            price=row[5],
            available=row[6],
        )
        for row in rows
    ]


@router.get("/{menu_id}", response_model=MenuItemRead)
async def get_menu_item(
    menu_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    menu_item = await session.get(MenuItem, menu_id)
    if not menu_item:
        raise HTTPException(status_code=404, detail="Menu item not found")
    await ensure_vendor_access(menu_item.vendor_id, user, session)
    return menu_item


@router.delete("/daily/{menu_item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_daily_menu_item(
    menu_item_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    require_trusted_origin(request)
    db_menu = await session.get(DailyMenuItem, menu_item_id)
    if not db_menu:
        raise HTTPException(status_code=404, detail="Daily menu item not found")
    await ensure_vendor_access(db_menu.vendor_id, user, session)

    await session.delete(db_menu)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{menu_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_menu_item(
    menu_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    require_trusted_origin(request)
    db_menu = await session.get(MenuItem, menu_id)
    if not db_menu:
        raise HTTPException(status_code=404, detail="Menu item not found")
    await ensure_vendor_access(db_menu.vendor_id, user, session)

    await session.delete(db_menu)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)