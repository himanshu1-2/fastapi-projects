import asyncio
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlmodel import SQLModel

from database import get_session
from main import app
from models.menu import User
from service.auth import hash_password


class VendorAuthMenuTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "test.sqlite"
        self.engine = create_async_engine(
            f"sqlite+aiosqlite:///{database_path}",
            poolclass=NullPool,
        )
        self.session_maker = async_sessionmaker(self.engine, expire_on_commit=False)

        async def create_schema() -> None:
            async with self.engine.begin() as connection:
                await connection.run_sync(SQLModel.metadata.create_all)

        asyncio.run(create_schema())

        async def override_session():
            async with self.session_maker() as session:
                yield session

        self.original_override = app.dependency_overrides.get(get_session)
        app.dependency_overrides[get_session] = override_session
        self.client = TestClient(app)
        self.origin = {"Origin": "http://localhost:5173"}

    def tearDown(self) -> None:
        self.client.close()
        if self.original_override is None:
            app.dependency_overrides.pop(get_session, None)
        else:
            app.dependency_overrides[get_session] = self.original_override

        async def dispose() -> None:
            await self.engine.dispose()

        asyncio.run(dispose())
        self.temp_dir.cleanup()

    def register_vendor(self, email: str, restaurant_name: str) -> tuple[TestClient, str]:
        client = TestClient(app)
        response = client.post(
            "/auth/register",
            headers=self.origin,
            json={
                "email": email,
                "password": "a sufficiently long password",
                "restaurant_name": restaurant_name,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return client, response.json()["vendor_id"]

    def test_vendor_registration_login_and_menu_access(self) -> None:
        vendor_client, vendor_id = self.register_vendor("vendor@example.com", "Saffron Table")
        self.assertEqual(vendor_id, "saffron-table")
        self.assertEqual(vendor_client.get("/auth/me").json()["role"], "vendor")
        self.assertEqual(vendor_client.get(f"/menu/items/{vendor_id}").status_code, 200)

        created = vendor_client.post(
            "/menu/items",
            headers=self.origin,
            json={
                "vendor_id": vendor_id,
                "name": "Chai",
                "description": "Masala tea",
                "category": "Drinks",
                "is_active": True,
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        item = created.json()
        self.assertEqual(item["vendor_id"], vendor_id)
        self.assertEqual(vendor_client.get(f"/menu/items/{vendor_id}/previously-used").json(), [])

        previous_date = "2000-01-01"
        save_response = vendor_client.put(
            f"/menu/daily/{vendor_id}/{previous_date}",
            headers=self.origin,
            json=[{
                "vendor_id": vendor_id,
                "date": previous_date,
                "menu_item_id": item["id"],
                "price": 25,
                "stock_count": 8,
                "available": True,
            }],
        )
        self.assertEqual(save_response.status_code, 200, save_response.text)

        another_previous_date = "2001-01-01"
        second_save = vendor_client.put(
            f"/menu/daily/{vendor_id}/{another_previous_date}",
            headers=self.origin,
            json=[{
                "vendor_id": vendor_id,
                "date": another_previous_date,
                "menu_item_id": item["id"],
                "price": 27,
                "stock_count": 5,
                "available": True,
            }],
        )
        self.assertEqual(second_save.status_code, 200, second_save.text)
        previously_used = vendor_client.get(f"/menu/items/{vendor_id}/previously-used")
        self.assertEqual(previously_used.status_code, 200, previously_used.text)
        self.assertEqual([used_item["id"] for used_item in previously_used.json()], [item["id"]])

        other_client, other_vendor_id = self.register_vendor("history@example.com", "History Cafe")
        self.assertEqual(other_client.get(f"/menu/items/{vendor_id}/previously-used").status_code, 403)
        self.assertEqual(other_client.get(f"/menu/items/{other_vendor_id}/previously-used").json(), [])

        today = datetime.utcnow().strftime("%Y-%m-%d")
        today_save = vendor_client.put(
            f"/menu/daily/{vendor_id}/{today}",
            headers=self.origin,
            json=[{
                "vendor_id": vendor_id,
                "date": today,
                "menu_item_id": item["id"],
                "price": 25,
                "stock_count": 8,
                "available": True,
            }],
        )
        self.assertEqual(today_save.status_code, 200, today_save.text)
        public_menu = vendor_client.get(f"/menu/{vendor_id}/today")
        self.assertEqual(public_menu.status_code, 200)
        self.assertEqual(public_menu.json()[0]["name"], "Chai")

        removed = vendor_client.put(
            f"/menu/daily/{vendor_id}/{today}",
            headers=self.origin,
            json=[],
        )
        self.assertEqual(removed.status_code, 200, removed.text)
        self.assertEqual(vendor_client.get(f"/menu/{vendor_id}/today").json(), [])
        other_client.close()

    def test_vendors_cannot_manage_another_vendor_and_admin_can_see_all(self) -> None:
        owner_client, owner_slug = self.register_vendor("owner@example.com", "Owner Cafe")
        other_client, other_slug = self.register_vendor("other@example.com", "Other Cafe")

        forbidden = owner_client.get(f"/menu/items/{other_slug}")
        self.assertEqual(forbidden.status_code, 403)

        async def add_admin() -> None:
            async with self.session_maker() as session:
                session.add(User(
                    email="admin@example.com",
                    password_hash=hash_password("another long admin password"),
                    role="admin",
                ))
                await session.commit()

        asyncio.run(add_admin())
        admin_client = TestClient(app)
        login = admin_client.post(
            "/auth/login",
            headers=self.origin,
            json={"email": "admin@example.com", "password": "another long admin password"},
        )
        self.assertEqual(login.status_code, 200, login.text)
        vendors = admin_client.get("/menu/vendors").json()
        slugs = {vendor["slug"] for vendor in vendors}
        self.assertTrue({owner_slug, other_slug}.issubset(slugs))
        self.assertEqual(admin_client.get(f"/menu/items/{other_slug}").status_code, 200)

    def test_menu_writes_require_login(self) -> None:
        response = self.client.post(
            "/menu/items",
            headers=self.origin,
            json={
                "vendor_id": "unowned",
                "name": "Item",
                "category": "Food",
            },
        )
        self.assertEqual(response.status_code, 401)

    def test_registration_rejects_duplicate_email(self) -> None:
        first_client, _ = self.register_vendor("duplicate@example.com", "One Cafe")
        second = self.client.post(
            "/auth/register",
            headers=self.origin,
            json={
                "email": "duplicate@example.com",
                "password": "a sufficiently long password",
                "restaurant_name": "Two Cafe",
            },
        )
        self.assertEqual(second.status_code, 409)
        first_client.close()


if __name__ == "__main__":
    unittest.main()
