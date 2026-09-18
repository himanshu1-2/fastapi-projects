from contextlib import asynccontextmanager

from database import create_tables
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(menu_router)
@app.get("/")
def root():
    return {"message": "Welcome to rangmanch review API"}