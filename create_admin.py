import asyncio
import getpass
import re

from sqlalchemy import select

from database import async_session_maker, create_tables
from models.menu import User
from service.auth import hash_password


async def create_admin(email: str, password: str) -> None:
    await create_tables()
    normalized_email = email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized_email):
        raise ValueError("Enter a valid email address")
    if len(password) < 12:
        raise ValueError("Admin password must contain at least 12 characters")

    async with async_session_maker() as session:
        existing_admin = await session.execute(select(User).where(User.role == "admin"))
        if existing_admin.scalar_one_or_none() is not None:
            raise RuntimeError("An administrator already exists")
        existing_user = await session.execute(select(User).where(User.email == normalized_email))
        if existing_user.scalar_one_or_none() is not None:
            raise RuntimeError("An account already uses this email")

        session.add(User(email=normalized_email, password_hash=hash_password(password), role="admin"))
        await session.commit()


def main() -> None:
    email = input("Admin email: ").strip()
    password = getpass.getpass("Admin password (minimum 12 characters): ")
    confirmation = getpass.getpass("Confirm admin password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match")
    asyncio.run(create_admin(email, password))
    print("Administrator account created.")


if __name__ == "__main__":
    main()
