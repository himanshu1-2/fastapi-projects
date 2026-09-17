from database import get_session
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from models.menu import Menu
from schema.menu import MenuCreate, MenuRead
from sqlmodel import Session, func, select

router = APIRouter(prefix="/menu", tags=["menu"])

@router.post("/", response_model=MenuRead)
def create_menu(menu: MenuCreate, session: Session = Depends(get_session)):
    db_menu = Menu(**menu.model_dump())
    session.add(db_menu)
    session.commit()
    session.refresh(db_menu)
    return db_menu

@router.get("/", response_model=list[MenuRead])
def list_menu(
    name: str | None = Query(None, description="Filter by menu name"),
    skip: int = Query(0, ge=0, description="Number of menu items to skip"),
    limit: int = Query(10, ge=1, le=50, description="Max menu items to return"),
    session: Session = Depends(get_session)
):
    query = select(Menu)

    if name:
        query = query.where(Menu.name == name)

    query = query.offset(skip).limit(limit)
    menus = session.exec(query).all()
    return menus

@router.patch("/{menu_id}", response_model=MenuRead)
def update_menu(menu_id: int, menu: MenuCreate, session: Session = Depends(get_session)):
    db_menu = session.get(Menu, menu_id)
    if not db_menu:
        raise HTTPException(status_code=404, detail="Menu item not found")
    
    for key, value in menu.model_dump().items():
        setattr(db_menu, key, value)
    
    session.add(db_menu)
    session.commit()
    session.refresh(db_menu)
    return db_menu

@router.get("/{menu_id}", response_model=MenuRead)
def get_menu(menu_id: int, session: Session = Depends(get_session)):
    db_menu = session.get(Menu, menu_id)
    if not db_menu:
        raise HTTPException(status_code=404, detail="Menu item not found")
    return db_menu

@router.delete("/{menu_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_menu(menu_id: int, session: Session = Depends(get_session)):
    db_menu = session.get(Menu, menu_id)
    if not db_menu:
        raise HTTPException(status_code=404, detail="Menu item not found")

    session.delete(db_menu)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)