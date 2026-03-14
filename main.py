from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List
import databases
import sqlalchemy
from sqlalchemy import select, func
import os
from datetime import datetime
import re

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./rabota.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "changeme")

database = databases.Database(DATABASE_URL)
metadata = sqlalchemy.MetaData()

categories_table = sqlalchemy.Table(
    "categories", metadata,
    sqlalchemy.Column("id", sqlalchemy.String(50), primary_key=True),
    sqlalchemy.Column("name", sqlalchemy.String(200), nullable=False),
    sqlalchemy.Column("image_data", sqlalchemy.Text),
    sqlalchemy.Column("order_index", sqlalchemy.Integer, default=0),
    sqlalchemy.Column("active", sqlalchemy.Boolean, default=True),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=datetime.utcnow),
)

listings_table = sqlalchemy.Table(
    "listings", metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True, autoincrement=True),
    sqlalchemy.Column("category_id", sqlalchemy.String(50), nullable=False),
    sqlalchemy.Column("text", sqlalchemy.Text, nullable=False),
    sqlalchemy.Column("phone", sqlalchemy.String(50)),
    sqlalchemy.Column("telegram", sqlalchemy.String(100)),
    sqlalchemy.Column("author_name", sqlalchemy.String(100)),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=datetime.utcnow),
    sqlalchemy.Column("approved", sqlalchemy.Boolean, default=False),
    sqlalchemy.Column("rejected", sqlalchemy.Boolean, default=False),
    sqlalchemy.Column("pinned", sqlalchemy.Boolean, default=False),
    sqlalchemy.Column("vip", sqlalchemy.Boolean, default=False),
    sqlalchemy.Column("is_admin_post", sqlalchemy.Boolean, default=False),
    sqlalchemy.Column("expires_at", sqlalchemy.DateTime, nullable=True),
)

blacklist_table = sqlalchemy.Table(
    "blacklist", metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True, autoincrement=True),
    sqlalchemy.Column("value", sqlalchemy.String(200), nullable=False),
    sqlalchemy.Column("reason", sqlalchemy.String(500)),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=datetime.utcnow),
)

complaints_table = sqlalchemy.Table(
    "complaints", metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True, autoincrement=True),
    sqlalchemy.Column("listing_id", sqlalchemy.Integer, nullable=False),
    sqlalchemy.Column("reason", sqlalchemy.String(500)),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, default=datetime.utcnow),
)

connect_args = {"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
engine = sqlalchemy.create_engine(DATABASE_URL, connect_args=connect_args)
metadata.create_all(engine)

DEFAULT_CATEGORIES = [
    {"id": "vacancies",     "name": "Вакансии и резюме",             "order_index": 0},
    {"id": "construction",  "name": "Строительство",                 "order_index": 1},
    {"id": "cleaning",      "name": "Уборка | Мойка | Грузчики",     "order_index": 2},
    {"id": "restaurant",    "name": "Общепит | Бары | Рестораны",    "order_index": 3},
    {"id": "logistics",     "name": "Логистика | Водители | Курьеры","order_index": 4},
    {"id": "office",        "name": "Бухгалтерия | Офис | Аудит",   "order_index": 5},
    {"id": "remote",        "name": "Удалённая работа | IT",         "order_index": 6},
    {"id": "security",      "name": "Вахта | Охрана | ЧОП",         "order_index": 7},
    {"id": "medicine",      "name": "Медицина",                      "order_index": 8},
]

app = FastAPI(title="Поговорим о работе API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")


# ── Pydantic models ────────────────────────────────────────────────────────────

class ListingCreate(BaseModel):
    category_id: str
    text: str
    phone: Optional[str] = None
    telegram: Optional[str] = None
    author_name: Optional[str] = None

class ListingEdit(BaseModel):
    text: Optional[str] = None
    phone: Optional[str] = None
    telegram: Optional[str] = None
    author_name: Optional[str] = None
    expires_at: Optional[datetime] = None

class AdminPost(BaseModel):
    category_ids: List[str]
    text: str
    phone: Optional[str] = None
    telegram: Optional[str] = None
    author_name: Optional[str] = None
    pinned: bool = False
    vip: bool = False
    expires_at: Optional[datetime] = None

class CategoryCreate(BaseModel):
    name: str
    image_data: Optional[str] = None

class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    image_data: Optional[str] = None
    order_index: Optional[int] = None
    active: Optional[bool] = None

class BlacklistAdd(BaseModel):
    value: str
    reason: Optional[str] = ""

class ComplaintCreate(BaseModel):
    listing_id: int
    reason: Optional[str] = ""


# ── Helpers ────────────────────────────────────────────────────────────────────

def check_admin(token: str):
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Нет доступа")

def row_to_dict(row):
    d = dict(row)
    for k, v in d.items():
        if isinstance(v, datetime):
            d[k] = v.isoformat()
    return d


# ── Startup ────────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    await database.connect()
    count = await database.fetch_val(select(func.count()).select_from(categories_table))
    if count == 0:
        for cat in DEFAULT_CATEGORIES:
            await database.execute(categories_table.insert().values(
                id=cat["id"], name=cat["name"], image_data=None,
                order_index=cat["order_index"], active=True, created_at=datetime.utcnow(),
            ))

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()


# ── Public endpoints ───────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {"status": "ok", "app": "Поговорим о работе"}

@app.get("/categories")
async def get_categories():
    rows = await database.fetch_all(
        categories_table.select()
        .where(categories_table.c.active == True)
        .order_by(categories_table.c.order_index)
    )
    return [row_to_dict(r) for r in rows]

@app.get("/listings/{category_id}")
async def get_listings(category_id: str):
    now = datetime.utcnow()
    rows = await database.fetch_all(
        listings_table.select()
        .where(listings_table.c.category_id == category_id)
        .where(listings_table.c.approved == True)
        .where(listings_table.c.rejected == False)
        .order_by(listings_table.c.pinned.desc(), listings_table.c.created_at.desc())
    )
    result = []
    for r in rows:
        d = row_to_dict(r)
        if d.get("expires_at") and datetime.fromisoformat(d["expires_at"]) < now:
            continue
        result.append(d)
    return result

@app.post("/listings", status_code=201)
async def create_listing(data: ListingCreate):
    if len(data.text.strip()) < 10:
        raise HTTPException(status_code=400, detail="Текст слишком короткий")
    for val in [data.phone, data.telegram]:
        if val:
            bl = await database.fetch_one(blacklist_table.select().where(blacklist_table.c.value == val))
            if bl:
                raise HTTPException(status_code=403, detail="Заблокировано")
    listing_id = await database.execute(listings_table.insert().values(
        category_id=data.category_id, text=data.text.strip(),
        phone=data.phone, telegram=data.telegram, author_name=data.author_name,
        created_at=datetime.utcnow(), approved=False, rejected=False,
        pinned=False, vip=False, is_admin_post=False,
    ))
    return {"id": listing_id, "message": "Объявление отправлено на модерацию"}

@app.post("/complaints", status_code=201)
async def create_complaint(data: ComplaintCreate):
    await database.execute(complaints_table.insert().values(
        listing_id=data.listing_id, reason=data.reason, created_at=datetime.utcnow()
    ))
    return {"message": "Жалоба отправлена"}


# ── Admin: stats ───────────────────────────────────────────────────────────────

@app.get("/admin/stats")
async def admin_stats(token: str):
    check_admin(token)
    pending  = await database.fetch_val(select(func.count()).select_from(listings_table).where(listings_table.c.approved == False).where(listings_table.c.rejected == False))
    approved = await database.fetch_val(select(func.count()).select_from(listings_table).where(listings_table.c.approved == True))
    rejected = await database.fetch_val(select(func.count()).select_from(listings_table).where(listings_table.c.rejected == True))
    total    = await database.fetch_val(select(func.count()).select_from(listings_table))
    cats     = await database.fetch_val(select(func.count()).select_from(categories_table).where(categories_table.c.active == True))
    compl    = await database.fetch_val(select(func.count()).select_from(complaints_table))
    return {"pending": pending, "approved": approved, "rejected": rejected, "total": total, "categories": cats, "complaints": compl}


# ── Admin: listings ────────────────────────────────────────────────────────────

@app.get("/admin/pending")
async def pending_listings(token: str):
    check_admin(token)
    rows = await database.fetch_all(
        listings_table.select()
        .where(listings_table.c.approved == False)
        .where(listings_table.c.rejected == False)
        .order_by(listings_table.c.created_at.asc())
    )
    return [row_to_dict(r) for r in rows]

@app.get("/admin/listings")
async def all_listings(token: str, status: str = "all", category_id: str = "", search: str = ""):
    check_admin(token)
    q = listings_table.select()
    if status == "pending":
        q = q.where(listings_table.c.approved == False).where(listings_table.c.rejected == False)
    elif status == "approved":
        q = q.where(listings_table.c.approved == True)
    elif status == "rejected":
        q = q.where(listings_table.c.rejected == True)
    if category_id:
        q = q.where(listings_table.c.category_id == category_id)
    rows = await database.fetch_all(q.order_by(listings_table.c.created_at.desc()))
    results = [row_to_dict(r) for r in rows]
    if search:
        s = search.lower()
        results = [r for r in results if
                   s in (r.get("text") or "").lower() or
                   s in (r.get("phone") or "").lower() or
                   s in (r.get("telegram") or "").lower() or
                   s in (r.get("author_name") or "").lower()]
    return results

@app.patch("/admin/listings/{lid}/approve")
async def approve_listing(lid: int, token: str):
    check_admin(token)
    await database.execute(listings_table.update().where(listings_table.c.id == lid).values(approved=True, rejected=False))
    return {"message": "Одобрено"}

@app.patch("/admin/listings/{lid}/reject")
async def reject_listing(lid: int, token: str):
    check_admin(token)
    await database.execute(listings_table.update().where(listings_table.c.id == lid).values(rejected=True, approved=False))
    return {"message": "Отклонено"}

@app.patch("/admin/listings/{lid}/pin")
async def pin_listing(lid: int, token: str, pinned: bool = True):
    check_admin(token)
    await database.execute(listings_table.update().where(listings_table.c.id == lid).values(pinned=pinned))
    return {"message": "Обновлено"}

@app.patch("/admin/listings/{lid}/vip")
async def vip_listing(lid: int, token: str, vip: bool = True):
    check_admin(token)
    await database.execute(listings_table.update().where(listings_table.c.id == lid).values(vip=vip))
    return {"message": "Обновлено"}

@app.patch("/admin/listings/{lid}")
async def edit_listing(lid: int, token: str, data: ListingEdit):
    check_admin(token)
    values = {k: v for k, v in data.dict().items() if v is not None}
    if values:
        await database.execute(listings_table.update().where(listings_table.c.id == lid).values(**values))
    return {"message": "Обновлено"}

@app.delete("/admin/listings/{lid}")
async def delete_listing(lid: int, token: str):
    check_admin(token)
    await database.execute(listings_table.delete().where(listings_table.c.id == lid))
    return {"message": "Удалено"}

@app.post("/admin/post", status_code=201)
async def admin_post(token: str, data: AdminPost):
    check_admin(token)
    ids = data.category_ids
    if "all" in ids:
        rows = await database.fetch_all(categories_table.select().where(categories_table.c.active == True))
        ids = [r["id"] for r in rows]
    for cat_id in ids:
        await database.execute(listings_table.insert().values(
            category_id=cat_id, text=data.text,
            phone=data.phone, telegram=data.telegram,
            author_name=data.author_name or "Администрация",
            created_at=datetime.utcnow(), approved=True, rejected=False,
            pinned=data.pinned, vip=data.vip, is_admin_post=True,
            expires_at=data.expires_at,
        ))
    return {"message": f"Опубликовано в {len(ids)} категориях"}


# ── Admin: categories ──────────────────────────────────────────────────────────

@app.get("/admin/categories")
async def admin_get_categories(token: str):
    check_admin(token)
    rows = await database.fetch_all(categories_table.select().order_by(categories_table.c.order_index))
    return [row_to_dict(r) for r in rows]

@app.post("/admin/categories", status_code=201)
async def admin_create_category(token: str, data: CategoryCreate):
    check_admin(token)
    cat_id = re.sub(r'[^a-z0-9]', '_', data.name.lower())[:30].strip('_')
    max_order = await database.fetch_val(select(func.max(categories_table.c.order_index)).select_from(categories_table)) or 0
    await database.execute(categories_table.insert().values(
        id=cat_id, name=data.name, image_data=data.image_data,
        order_index=max_order + 1, active=True, created_at=datetime.utcnow(),
    ))
    return {"id": cat_id, "message": "Категория создана"}

@app.patch("/admin/categories/{cat_id}")
async def admin_update_category(cat_id: str, token: str, data: CategoryUpdate):
    check_admin(token)
    values = {k: v for k, v in data.dict().items() if v is not None}
    if values:
        await database.execute(categories_table.update().where(categories_table.c.id == cat_id).values(**values))
    return {"message": "Обновлено"}

@app.delete("/admin/categories/{cat_id}")
async def admin_delete_category(cat_id: str, token: str):
    check_admin(token)
    await database.execute(categories_table.delete().where(categories_table.c.id == cat_id))
    return {"message": "Удалено"}


# ── Admin: blacklist ───────────────────────────────────────────────────────────

@app.get("/admin/blacklist")
async def get_blacklist(token: str):
    check_admin(token)
    rows = await database.fetch_all(blacklist_table.select().order_by(blacklist_table.c.created_at.desc()))
    return [row_to_dict(r) for r in rows]

@app.post("/admin/blacklist", status_code=201)
async def add_blacklist(token: str, data: BlacklistAdd):
    check_admin(token)
    try:
        await database.execute(blacklist_table.insert().values(value=data.value, reason=data.reason, created_at=datetime.utcnow()))
    except Exception:
        pass
    return {"message": "Добавлено"}

@app.delete("/admin/blacklist/{bl_id}")
async def remove_blacklist(bl_id: int, token: str):
    check_admin(token)
    await database.execute(blacklist_table.delete().where(blacklist_table.c.id == bl_id))
    return {"message": "Удалено"}


# ── Admin: complaints ──────────────────────────────────────────────────────────

@app.get("/admin/complaints")
async def get_complaints(token: str):
    check_admin(token)
    rows = await database.fetch_all(complaints_table.select().order_by(complaints_table.c.created_at.desc()))
    return [row_to_dict(r) for r in rows]

@app.delete("/admin/complaints/{cid}")
async def delete_complaint(cid: int, token: str):
    check_admin(token)
    await database.execute(complaints_table.delete().where(complaints_table.c.id == cid))
    return {"message": "Удалено"}


# ── Admin panel HTML ───────────────────────────────────────────────────────────

@app.get("/admin", response_class=HTMLResponse)
async def admin_page():
    with open("static/admin.html", encoding="utf-8") as f:
        return f.read()
