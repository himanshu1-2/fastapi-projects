import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))


def normalize_database_url(raw_url: str) -> str:
    """Convert a PostgreSQL URL to asyncpg-compatible form."""
    if not raw_url or not raw_url.strip():
        raise ValueError("DATABASE_URL is empty. Check your .env file or Vercel Environment Variables.")

    url = raw_url.strip()

    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql+psycopg://"):
        url = url.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)

    if not url.startswith("postgresql+asyncpg://"):
        raise ValueError(
            "DATABASE_URL must use a PostgreSQL async driver format like "
            "postgresql+asyncpg://..."
        )

    parsed = urlsplit(url)
    query_params = parse_qsl(parsed.query, keep_blank_values=True)
    filtered = []
    seen = set()

    for key, value in query_params:
        if key in {"sslmode", "channel_binding"}:
            continue
        if key in seen:
            continue
        seen.add(key)
        filtered.append((key, value))

    if "ssl" not in seen and ("neon.tech" in parsed.netloc or "sslmode=" in parsed.query):
        filtered.append(("ssl", "true"))

    rebuilt_query = urlencode(filtered)
    return urlunsplit(parsed._replace(query=rebuilt_query))


raw_database_url = os.getenv("DATABASE_URL")
if not raw_database_url:
    raise RuntimeError(
        "DATABASE_URL is missing. Add it in your .env file or Vercel Environment Variables. "
        "Example: postgresql+asyncpg://user:password@host:5432/dbname"
    )

DATABASE_URL = normalize_database_url(raw_database_url)

engine_kwargs = {"echo": True}
if "neon.tech" in DATABASE_URL or "ssl=true" in DATABASE_URL.lower():
    engine_kwargs["connect_args"] = {"ssl": True}

engine = create_async_engine(DATABASE_URL, **engine_kwargs)
async_session_maker = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def create_tables():
    """Create all tables defined by SQLModel classes."""
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


async def get_session():
    """Dependency that provides an async database session per request."""
    async with async_session_maker() as session:
        yield session