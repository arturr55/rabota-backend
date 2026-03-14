from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import databases
import sqlalchemy
import os
from datetime import datetime

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./rabota.db")
# Railway даёт postgres://, SQLAlchemy нужен postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

database = databases.Database(DATABASE_URL)
metadata = sqlalchemy.MetaData()

listings_table = sqlalchemy.Table(
    "listings",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("category_id", sqlalchemy.String(50), nullable=False),
    sqlalchemy.Column("text", sqlalchemy.Text, nullable=False),
    sqlalchemy.Column("phone", sqlalchemy.String(50)),
    sqlalchemy.Column("telegram", sqlalchemy.String(100)),
    sqlalchemy.Column("author_name", sqlalchemy.String(100)),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=datetime.utcnow),
    sqlalchemy.Column("approved", sqlalchemy.Boolean, default=False),
)

engine = sqlalchemy.create_engine(
    DATABASE_URL if "sqlite" in DATABASE_URL else DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
)
metadata.create_all(engine)

app = FastAPI(title="Поговорим о работе API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ListingCreate(BaseModel):
    category_id: str
    text: str
    phone: Optional[str] = None
    telegram: Optional[str] = None
    author_name: Optional[str] = None


@app.on_event("startup")
async def startup():
    await database.connect()


@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()


@app.get("/")
async def root():
    return {"status": "ok", "app": "Поговорим о работе"}


@app.get("/listings/{category_id}")
async def get_listings(category_id: str):
    query = (
        listings_table.select()
        .where(listings_table.c.category_id == category_id)
        .where(listings_table.c.approved == True)
        .order_by(listings_table.c.created_at.desc())
    )
    rows = await database.fetch_all(query)
    return [dict(row) for row in rows]


@app.post("/listings", status_code=201)
async def create_listing(data: ListingCreate):
    if len(data.text.strip()) < 10:
        raise HTTPException(status_code=400, detail="Текст слишком короткий")
    query = listings_table.insert().values(
        category_id=data.category_id,
        text=data.text.strip(),
        phone=data.phone,
        telegram=data.telegram,
        author_name=data.author_name,
        created_at=datetime.utcnow(),
        approved=False,
    )
    listing_id = await database.execute(query)
    return {"id": listing_id, "message": "Объявление отправлено на модерацию"}


# Эндпоинт для одобрения (только ты используешь)
@app.patch("/admin/listings/{listing_id}/approve")
async def approve_listing(listing_id: int, token: str):
    admin_token = os.getenv("ADMIN_TOKEN", "changeme")
    if token != admin_token:
        raise HTTPException(status_code=403, detail="Нет доступа")
    query = (
        listings_table.update()
        .where(listings_table.c.id == listing_id)
        .values(approved=True)
    )
    await database.execute(query)
    return {"message": "Одобрено"}


# Список всех неодобренных (для модерации)
@app.get("/admin/pending")
async def pending_listings(token: str):
    admin_token = os.getenv("ADMIN_TOKEN", "changeme")
    if token != admin_token:
        raise HTTPException(status_code=403, detail="Нет доступа")
    query = (
        listings_table.select()
        .where(listings_table.c.approved == False)
        .order_by(listings_table.c.created_at.asc())
    )
    rows = await database.fetch_all(query)
    return [dict(row) for row in rows]
