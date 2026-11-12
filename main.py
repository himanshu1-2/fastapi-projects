from contextlib import asynccontextmanager

from database import create_tables
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from service.auth import FRONTEND_ORIGINS, router as auth_router
from service.menu import router as menu_router



@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Lifespan started")
    await create_tables()
    print("Database tables created")
    yield
    # shutdown: cleanup here
    print("Shutting down the app")

app = FastAPI(
     title="Rangmanch Reviews API",
    description="Theatre reviews API for Pune Rangmanch",
    lifespan=lifespan
)    

app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(FRONTEND_ORIGINS),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)

app.include_router(menu_router)
app.include_router(auth_router)
@app.get("/")
def root():
    return {"message": "Welcome to rangmanch review API"}