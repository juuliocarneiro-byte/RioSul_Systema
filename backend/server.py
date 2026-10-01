from dotenv import load_dotenv
from pathlib import Path
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

import os, jwt, bcrypt, uuid, io, base64, zipfile, re, tempfile
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Any, Dict
from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, Response, UploadFile, File, Query
from fastapi.responses import StreamingResponse, Response as FastResponse
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, EmailStr
import pandas as pd
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm, cm
from reportlab.pdfgen import canvas as rlcanvas
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as RLImage, PageBreak
from PIL import Image as PILImage
import pdfplumber
from pypdf import PdfWriter, PdfReader

JWT_ALGO = "HS256"
JWT_SECRET = os.environ["JWT_SECRET"]
UPLOADS_DIR = ROOT_DIR / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

client = AsyncIOMotorClient(os.environ['MONGO_URL'])
db = client[os.environ['DB_NAME']]

app = FastAPI(title="Rio Sul API")

# CORS middleware must be added early, before routes
FRONTEND_URL = os.environ["FRONTEND_URL"]
app.add_middleware(CORSMiddleware, allow_credentials=True, allow_origins=[FRONTEND_URL],
    allow_methods=["*"], allow_headers=["*"])

api = APIRouter(prefix="/api")

def hash_pw(p: str) -> str:
    return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()

def verify_pw(p: str, h: str) -> bool:
    try: return bcrypt.checkpw(p.encode(), h.encode())
    except Exception: return False

def make_access(uid: str, email: str, role: str) -> str:
    return jwt.encode({"sub": uid, "email": email, "role": role, "type": "access",
                       "exp": datetime.now(timezone.utc) + timedelta(hours=12)}, JWT_SECRET, algorithm=JWT_ALGO)

def make_refresh(uid: str) -> str:
    return jwt.encode({"sub": uid, "type": "refresh",
                       "exp": datetime.now(timezone.utc) + timedelta(days=7)}, JWT_SECRET, algorithm=JWT_ALGO)

def new_id() -> str: return str(uuid.uuid4())
def now_iso() -> str: return datetime.now(timezone.utc).isoformat()

async def get_user(request: Request) -> dict:
    token = request.cookies.get("access_token")
    if not token:
        ah = request.headers.get("Authorization", "")
        if ah.startswith("Bearer "): token = ah[7:]
    if not token: raise HTTPException(401, "Não autenticado")
    try:
        p = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        if p.get("type") != "access": raise HTTPException(401, "Token inválido")
        u = await db.users.find_one({"id": p["sub"]})
        if not u: raise HTTPException(401, "Usuário não encontrado")
        u.pop("_id", None); u.pop("password_hash", None)
        return u
    except jwt.ExpiredSignatureError: raise HTTPException(401, "Token expirado")
    except jwt.InvalidTokenError: raise HTTPException(401, "Token inválido")

async def require_admin(user=Depends(get_user)):
    if user.get("role") != "admin": raise HTTPException(403, "Apenas administradores")
    return user

async def require_staff(user=Depends(get_user)):
    if user.get("role") not in {"admin", "vendedor", "producao"}:
        raise HTTPException(403, "Função sem permissão")
    return user

# ---------- Real catalog seed ----------
REAL_CATEGORIES = [
    ("Impressões", "https://images.unsplash.com/photo-1586952518485-11b180e92764?w=400"),
    ("Impressão Solvente", "https://images.unsplash.com/photo-1568605114967-8130f3a36994?w=400"),
    ("Adesivos", "https://customer-assets-rejwkqb3.emergentagent.net/job_b76bd2f1-9bb5-4397-924a-8f96083362ca/artifacts/o0f32011_ADESIVO%204X4.jpeg"),
    ("Banners", "https://customer-assets-rejwkqb3.emergentagent.net/job_b76bd2f1-9bb5-4397-924a-8f96083362ca/artifacts/rs4a6pfh_BANNER.jpeg"),
    ("Canecas", "https://customer-assets-rejwkqb3.emergentagent.net/job_b76bd2f1-9bb5-4397-924a-8f96083362ca/artifacts/qo4nex83_CANECAS.jpeg"),
    ("Camisas", "https://customer-assets-rejwkqb3.emergentagent.net/job_b76bd2f1-9bb5-4397-924a-8f96083362ca/artifacts/2tnd6g8l_CAMISAS.jpeg"),
    ("Cartões de Visita", "https://images.unsplash.com/photo-1600880292203-757bb62b4baf?w=400"),
    ("Panfletos", "https://images.unsplash.com/photo-1586953208448-b95a79798f07?w=400"),
    ("Fotos", "https://images.unsplash.com/photo-1554080353-a576cf803bda?w=400"),
    ("Molduras", "https://images.unsplash.com/photo-1513519245088-0e12902e5a38?w=400"),
    ("Azulejos", "https://images.unsplash.com/photo-1615873968403-89e068629265?w=400"),
    ("Cardápios", "https://images.unsplash.com/photo-1541542684-4a9c1f0e8a52?w=400"),
    ("Apostilas", "https://images.unsplash.com/photo-1519681393784-d120267933ba?w=400"),
    ("Cavalete", "https://images.unsplash.com/photo-1517245386807-bb43f82c33c4?w=400"),
    ("Combos", "https://images.unsplash.com/photo-1607083206869-4c7672e72a8a?w=400"),
    ("Gravação a Laser", "https://images.unsplash.com/photo-1518138706495-aec1c62be9ee?w=400"),
]

def mkvar(name, price):
    return {"id": new_id(), "name": name, "price": price, "active": True}

REAL_PRODUCTS = [
    # Impressões
    {"cat": "Impressões", "name": "Impressão Preto e Branco", "unit": "Folha", "price": 2.00},
    {"cat": "Impressões", "name": "Impressão Colorida", "unit": "Folha", "price": 2.50},
    {"cat": "Impressões", "name": "Xerox Preto e Branco", "unit": "Folha", "price": 0.50},
    {"cat": "Impressões", "name": "Xerox Colorida", "unit": "Folha", "price": 1.00},
    {"cat": "Impressões", "name": "Plastificação Documento", "unit": "Unidade", "price": 6.00},
    {"cat": "Impressões", "name": "Plastificação A4", "unit": "Unidade", "price": 8.00},
    {"cat": "Impressões", "name": "Encadernação até 100 folhas", "unit": "Unidade", "price": 15.00},
    {"cat": "Impressões", "name": "Encadernação acima de 100 folhas", "unit": "Unidade", "price": 18.00},
    {"cat": "Impressões", "name": "Papel Fotográfico", "unit": "Folha", "price": 6.00},
    {"cat": "Impressões", "name": "Papel Adesivo Fotográfico", "unit": "Folha", "price": 7.00},
    {"cat": "Impressões", "name": "Papel Offset ou Kraft", "unit": "Folha", "price": 6.00},
    {"cat": "Impressões", "name": "Impressão Laser A4 Couchê", "unit": "Folha", "price": 6.00},
    {"cat": "Impressões", "name": "Impressão Laser A3 Couchê", "unit": "Folha", "price": 10.00},
    {"cat": "Impressões", "name": "Impressão Laser A4 Adesiva", "unit": "Folha", "price": 8.00},
    {"cat": "Impressões", "name": "Impressão Laser A3 Adesiva", "unit": "Folha", "price": 15.00},
    {"cat": "Impressões", "name": "Impressão Laser A3 Adesiva com Corte", "unit": "Folha", "price": 20.00},
    # Impressão Solvente (per_m2)
    {"cat": "Impressão Solvente", "name": "Lona com Ilhós", "unit": "M²", "price_type": "per_m2", "m2_price": 40, "m2_min_price": 30},
    {"cat": "Impressão Solvente", "name": "Banner", "unit": "M²", "price_type": "per_m2", "m2_price": 40, "m2_min_price": 30},
    {"cat": "Impressão Solvente", "name": "Adesivo sem Recorte", "unit": "M²", "price_type": "per_m2", "m2_price": 40, "m2_min_price": 30},
    {"cat": "Impressão Solvente", "name": "Adesivo com Recorte", "unit": "M²", "price_type": "per_m2", "m2_price": 45, "m2_min_price": 30},
    # Adesivos
    {"cat": "Adesivos", "name": "Adesivo 4x4 cm (Redondo ou Quadrado)", "unit": "Pacote", "variations": [
        mkvar("130 unidades", 25), mkvar("270 unidades", 40), mkvar("500 unidades", 70), mkvar("1.000 unidades", 110)]},
    {"cat": "Adesivos", "name": "Adesivo 5x5 cm (Redondo ou Quadrado)", "unit": "Pacote", "variations": [
        mkvar("130 unidades", 35), mkvar("280 unidades", 60), mkvar("500 unidades", 95), mkvar("1.000 unidades", 150)]},
    # Banners
    {"cat": "Banners", "name": "Banner Sob Medida", "unit": "M²", "price_type": "per_m2", "m2_price": 40, "m2_min_price": 30},
    {"cat": "Banners", "name": "Banner Pronto", "unit": "Unidade", "variations": [
        mkvar("70x45 cm", 45), mkvar("60x90 cm", 65), mkvar("80x120 cm", 85), mkvar("90x120 cm", 90), mkvar("100x150 cm", 120)]},
    {"cat": "Banners", "name": "Wind Banner", "unit": "Unidade", "price": 275},
    # Canecas
    {"cat": "Canecas", "name": "Caneca Branca de Porcelana", "unit": "Unidade", "price": 35},
    {"cat": "Canecas", "name": "Caneca Mágica", "unit": "Unidade", "price": 55},
    {"cat": "Canecas", "name": "Caneca Glitter", "unit": "Unidade", "price": 55},
    {"cat": "Canecas", "name": "Caneca Alça/Interior Colorido", "unit": "Unidade", "price": 55},
    # Camisas
    {"cat": "Camisas", "name": "Camisa Branca", "unit": "Unidade", "variations": [mkvar("Somente Frente", 35), mkvar("Frente e Verso", 40)]},
    {"cat": "Camisas", "name": "Camisa Poliéster Tons Pastéis/Cinza", "unit": "Unidade", "variations": [mkvar("Somente Frente", 40), mkvar("Frente e Verso", 45)]},
    {"cat": "Camisas", "name": "Camisa Poliéster Colorida", "unit": "Unidade", "variations": [mkvar("Somente Frente", 65), mkvar("Frente e Verso", 70)]},
    {"cat": "Camisas", "name": "Camisa Algodão Colorida", "unit": "Unidade", "variations": [mkvar("Somente Frente", 70), mkvar("Frente e Verso", 75)]},
    {"cat": "Camisas", "name": "Polo Poliéster", "unit": "Unidade", "variations": [mkvar("Somente Frente", 75), mkvar("Frente e Verso", 80)]},
    {"cat": "Camisas", "name": "Polo Algodão", "unit": "Unidade", "variations": [mkvar("Somente Frente", 85), mkvar("Frente e Verso", 90)]},
    # Cartões
    {"cat": "Cartões de Visita", "name": "Cartão Offset 1000 un", "unit": "Milheiro", "variations": [
        mkvar("4/0 Couchê 300g", 100), mkvar("4/4 Couchê 300g", 120), mkvar("4/4 Duodesign 300g + Verniz Localizado", 220)]},
    {"cat": "Cartões de Visita", "name": "Cartão Laser", "unit": "Pacote", "variations": [
        mkvar("100 un 4/0 Couchê 250g", 49.90), mkvar("250 un 4/0 Couchê 250g", 89.90), mkvar("500 un 4/0 Couchê 250g", 109.90)]},
    {"cat": "Cartões de Visita", "name": "Criação de Arte", "unit": "Unidade", "price": 20},
    {"cat": "Cartões de Visita", "name": "Corte Especial / Canteamento / Serrilha", "unit": "Unidade", "price": 20},
    # Panfletos
    {"cat": "Panfletos", "name": "Panfleto 10x14 cm 80g", "unit": "Pacote", "variations": [
        mkvar("1.250 un 4/0", 155), mkvar("1.250 un 4/4", 185),
        mkvar("2.500 un 4/0", 185), mkvar("2.500 un 4/4", 235),
        mkvar("5.000 un 4/0", 235), mkvar("5.000 un 4/4", 295)]},
    # Fotos
    {"cat": "Fotos", "name": "Foto 3x4 (8 unidades)", "unit": "Pacote", "price": 15},
    {"cat": "Fotos", "name": "Polaroid 10x7 cm", "unit": "Unidade", "price": 4},
    {"cat": "Fotos", "name": "Polaroid 10x7 cm com Ímã", "unit": "Unidade", "price": 6},
    {"cat": "Fotos", "name": "Foto 10x15 na Hora", "unit": "Unidade", "price": 4},
    {"cat": "Fotos", "name": "Foto 10x15 (por faixa 24h)", "unit": "Unidade", "variations": [
        mkvar("Acima de 10 fotos", 2.50), mkvar("Acima de 30 fotos", 2.20),
        mkvar("Acima de 50 fotos", 2.00), mkvar("Acima de 100 fotos", 1.75)]},
    {"cat": "Fotos", "name": "Foto 15x21 (24h)", "unit": "Unidade", "price": 8},
    {"cat": "Fotos", "name": "Foto 20x30 (24h)", "unit": "Unidade", "price": 15},
    {"cat": "Fotos", "name": "Foto 30x40 (24h)", "unit": "Unidade", "price": 23},
    # Molduras
    {"cat": "Molduras", "name": "Moldura", "unit": "Unidade", "variations": [
        mkvar("10x15", 12), mkvar("15x21", 15), mkvar("20x30", 18), mkvar("30x40", 28)]},
    # Azulejos
    {"cat": "Azulejos", "name": "Azulejo (base inclusa)", "unit": "Unidade", "variations": [
        mkvar("10x10", 30), mkvar("15x15", 35), mkvar("20x20", 45), mkvar("21x30", 50)]},
    # Cardápios
    {"cat": "Cardápios", "name": "Cardápio A4 Plastificado", "unit": "Unidade", "variations": [mkvar("Somente Frente", 15), mkvar("Frente e Verso", 20)]},
    {"cat": "Cardápios", "name": "Cardápio A3 Plastificado", "unit": "Unidade", "variations": [mkvar("Somente Frente", 25), mkvar("Frente e Verso", 30)]},
    {"cat": "Cardápios", "name": "Cardápio A4 PS 2mm Laminado", "unit": "Unidade", "variations": [mkvar("Somente Frente", 50), mkvar("Frente e Verso", 60)]},
    {"cat": "Cardápios", "name": "Cardápio A3 PS 2mm Laminado", "unit": "Unidade", "variations": [mkvar("Somente Frente", 65), mkvar("Frente e Verso", 80)]},
    # Apostilas (tiered by pages)
    {"cat": "Apostilas", "name": "Apostila (preço por folha)", "unit": "Folha", "price_type": "tiered", "price": 3, "tiers": [
        {"min_qty": 1, "max_qty": 1, "price": 3.00},
        {"min_qty": 2, "max_qty": 10, "price": 1.00},
        {"min_qty": 11, "max_qty": 20, "price": 0.80},
        {"min_qty": 21, "max_qty": 30, "price": 0.70},
        {"min_qty": 31, "max_qty": 50, "price": 0.60},
        {"min_qty": 51, "max_qty": 100, "price": 0.55},
        {"min_qty": 101, "max_qty": 200, "price": 0.50},
        {"min_qty": 201, "max_qty": 300, "price": 0.45},
        {"min_qty": 301, "max_qty": 99999, "price": 0.40},
    ]},
    # Cavalete
    {"cat": "Cavalete", "name": "Cavalete Duplo + Lona 80x120 cm", "unit": "Unidade", "price": 450},
    # Combos
    {"cat": "Combos", "name": "2.500 Folhetos 10x14 80g + 1.000 Cartões", "unit": "Pacote", "price": 250},
    {"cat": "Combos", "name": "2.500 Folhetos 10x14 80g + Banner 80x120", "unit": "Pacote", "price": 250},
    {"cat": "Combos", "name": "1.000 Cartões + Banner 80x120", "unit": "Pacote", "price": 150},
    # Gravação a Laser (starting price)
    {"cat": "Gravação a Laser", "name": "Copo Térmico / Cuia / Tradicional (c/ abridor + tampa)", "unit": "Unidade", "price": 35, "is_starting_price": True},
    {"cat": "Gravação a Laser", "name": "Chaveiro Pé de Galinha com Abridor", "unit": "Unidade", "price": 2.49, "is_starting_price": True},
    {"cat": "Gravação a Laser", "name": "Squeeze Alumínio", "unit": "Unidade", "price": 35, "is_starting_price": True},
    {"cat": "Gravação a Laser", "name": "Chaveiro Acrílico Metalizado", "unit": "Unidade", "price": 4.99, "is_starting_price": True},
]

async def seed_real_catalog():
    # If flag already set, skip
    flag = await db.settings.find_one({"id": "seed_v2"})
    if flag: return
    # Remove test/demo TEST_IMPORT category and its products
    demo_names = ["TEST_IMPORT", "Adesivos","Impressões","Banners","Lonas","Canecas","Camisas","Cartões","Panfletos","Fotos","Outros"]
    for cat_name in demo_names:
        cats_to_remove = await db.categories.find({"name": cat_name}).to_list(100)
        for c in cats_to_remove:
            # remove empty categories (no products) to avoid clashing names
            n = await db.products.count_documents({"category_id": c["id"]})
            if n == 0:
                await db.categories.delete_one({"id": c["id"]})
    # Create real cats
    cat_ids = {}
    for i, (name, img) in enumerate(REAL_CATEGORIES):
        existing = await db.categories.find_one({"name": name})
        if existing:
            cat_ids[name] = existing["id"]
            await db.categories.update_one({"id": existing["id"]}, {"$set": {"image_url": img, "active": True, "order": i}})
        else:
            cid = new_id()
            await db.categories.insert_one({"id": cid, "name": name, "order": i, "active": True, "image_url": img, "created_at": now_iso()})
            cat_ids[name] = cid
    # Create products
    for p in REAL_PRODUCTS:
        cat_id = cat_ids.get(p["cat"])
        if not cat_id: continue
        exists = await db.products.find_one({"name": p["name"], "category_id": cat_id})
        if exists: continue
        doc = {
            "id": new_id(), "name": p["name"], "category_id": cat_id, "description": "",
            "price": p.get("price", 0), "price_type": p.get("price_type", "fixed"),
            "unit": p.get("unit", "Unidade"), "sku": "", "active": True, "order": 0,
            "variations": p.get("variations", []), "tiers": p.get("tiers", []),
            "m2_min_price": p.get("m2_min_price", 0), "m2_price": p.get("m2_price", 0),
            "image_url": p.get("image_url", ""),
            "is_starting_price": p.get("is_starting_price", False),
            "favorite": False, "created_at": now_iso()
        }
        await db.products.insert_one(doc)
    await db.settings.update_one({"id": "seed_v2"}, {"$set": {"id": "seed_v2", "done": True, "at": now_iso()}}, upsert=True)

# ---------- Startup ----------
async def ensure_user_logins():
    users = await db.users.find({}, {"_id": 0, "id": 1, "login": 1, "email": 1}).to_list(1000)
    used = set()
    for u in users:
        login = (u.get("login") or "").strip().lower()
        if not login:
            login = (u.get("email") or "").split("@", 1)[0].strip().lower() or u["id"][:8]
        base = login
        suffix = 2
        while login in used:
            login = f"{base}{suffix}"
            suffix += 1
        used.add(login)
        if u.get("login") != login:
            await db.users.update_one({"id": u["id"]}, {"$set": {"login": login}})

@app.on_event("startup")
async def startup():
    await ensure_user_logins()
    await db.users.update_many({"email": ""}, {"$unset": {"email": ""}})
    try: await db.users.drop_index("email_1")
    except Exception: pass
    await db.users.create_index("email", unique=True, partialFilterExpression={"email": {"$type": "string"}})
    await db.users.create_index("login", unique=True)
    await db.customers.create_index("phone")
    await db.sales.create_index("order_number")
    await db.shopee_orders.create_index("order_number")
    admin_login = os.environ.get("ADMIN_LOGIN", "igor").strip().lower()
    legacy_email = os.environ.get("ADMIN_EMAIL", "").strip().lower()
    pw = os.environ["ADMIN_PASSWORD"]
    name = os.environ.get("ADMIN_NAME", "Admin")
    existing = await db.users.find_one({"login": admin_login})
    if not existing and legacy_email:
        existing = await db.users.find_one({"email": legacy_email})
    if not existing:
        await db.users.insert_one({"id": new_id(), "login": admin_login, "email": legacy_email,
                                   "password_hash": hash_pw(pw), "name": name, "role": "admin",
                                   "active": True, "created_at": now_iso()})
    else:
        update = {"login": admin_login, "role": "admin", "name": name, "active": True}
        if not verify_pw(pw, existing["password_hash"]): update["password_hash"] = hash_pw(pw)
        await db.users.update_one({"id": existing["id"]}, {"$set": update})
    vendor = await db.users.find_one({"login": "vendedor"})
    if not vendor:
        vendor = await db.users.find_one({"email": "vendedor@riosul.com"})
    if not vendor:
        await db.users.insert_one({"id": new_id(), "login": "vendedor", "email": "vendedor@riosul.com",
                                   "password_hash": hash_pw("Vendedor@2026"), "name": "Vendedor Demo",
                                   "role": "vendedor", "active": True, "created_at": now_iso()})
    elif not vendor.get("login"):
        await db.users.update_one({"id": vendor["id"]}, {"$set": {"login": "vendedor"}})
    if await db.channels.count_documents({}) == 0:
        for n in ["Loja","WhatsApp","Instagram","Shopee","Outro"]:
            await db.channels.insert_one({"id": new_id(), "name": n, "active": True})
    if await db.payment_methods.count_documents({}) == 0:
        for n in ["PIX","Dinheiro","Débito","Crédito","Link","Transferência","Outro"]:
            await db.payment_methods.insert_one({"id": new_id(), "name": n, "active": True})
    if await db.units.count_documents({}) == 0:
        for n in ["Unidade","Pacote","Folha","Metro","M²","Cento","Milheiro"]:
            await db.units.insert_one({"id": new_id(), "name": n, "active": True})
    if not await db.settings.find_one({"id": "main"}):
        await db.settings.insert_one({"id": "main", "company_name": "Rio Sul Festas & Gráfica",
                                      "phone": "", "whatsapp": "", "cnpj": "", "email": "",
                                      "address": "", "receipt_footer": "Obrigado pela preferência!",
                                      "logo_url": "/riosul-logo.png"})
    await seed_real_catalog()

# ---------- Auth ----------
class LoginIn(BaseModel):
    login: str
    password: str

def set_cookies(resp: Response, access: str, refresh: str):
    resp.set_cookie("access_token", access, httponly=True, secure=True, samesite="none", max_age=43200, path="/")
    resp.set_cookie("refresh_token", refresh, httponly=True, secure=True, samesite="none", max_age=604800, path="/")

@api.post("/auth/login")
async def login(body: LoginIn, response: Response):
    login_value = body.login.strip().lower()
    u = await db.users.find_one({"login": login_value})
    if not u or not u.get("active", True) or not verify_pw(body.password, u["password_hash"]):
        raise HTTPException(401, "Credenciais inválidas")
    identity = u.get("email") or u["login"]
    access = make_access(u["id"], identity, u["role"])
    refresh = make_refresh(u["id"])
    set_cookies(response, access, refresh)
    return {"id": u["id"], "login": u["login"], "email": u.get("email", ""), "name": u["name"],
            "role": u["role"], "access_token": access}

@api.post("/auth/logout")
async def logout(response: Response, user=Depends(get_user)):
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    return {"ok": True}

@api.get("/auth/me")
async def me(user=Depends(get_user)): return user

@api.post("/auth/refresh")
async def refresh(request: Request, response: Response):
    tok = request.cookies.get("refresh_token")
    if not tok: raise HTTPException(401)
    try:
        p = jwt.decode(tok, JWT_SECRET, algorithms=[JWT_ALGO])
        if p.get("type") != "refresh": raise HTTPException(401)
        u = await db.users.find_one({"id": p["sub"]})
        if not u: raise HTTPException(401)
        access = make_access(u["id"], u.get("email") or u["login"], u["role"])
        response.set_cookie("access_token", access, httponly=True, secure=True, samesite="none", max_age=43200, path="/")
        return {"ok": True}
    except jwt.InvalidTokenError: raise HTTPException(401)

# ---------- Users ----------
class UserIn(BaseModel):
    login: str
    password: str
    name: str
    role: str = "vendedor"
    active: bool = True
    email: Optional[EmailStr] = None

@api.get("/users")
async def list_users(user=Depends(require_admin)):
    return await db.users.find({}, {"password_hash": 0, "_id": 0}).to_list(1000)

@api.post("/users")
async def create_user(body: UserIn, user=Depends(require_admin)):
    login = body.login.strip().lower()
    if not login: raise HTTPException(400, "Login é obrigatório")
    if body.role not in {"admin", "vendedor", "producao"}: raise HTTPException(400, "Função inválida")
    if await db.users.find_one({"login": login}): raise HTTPException(400, "Login já cadastrado")
    d = {"id": new_id(), "login": login, "password_hash": hash_pw(body.password), "name": body.name,
         "role": body.role, "active": body.active, "created_at": now_iso()}
    if body.email: d["email"] = str(body.email).lower()
    await db.users.insert_one(d); d.pop("password_hash"); d.pop("_id", None); return d

class UserUpd(BaseModel):
    login: Optional[str] = None
    name: Optional[str] = None
    role: Optional[str] = None
    active: Optional[bool] = None
    password: Optional[str] = None

@api.put("/users/{uid}")
async def update_user(uid: str, body: UserUpd, user=Depends(require_admin)):
    upd = {k: v for k, v in body.model_dump().items() if v is not None and k not in {"password", "login"}}
    if body.login is not None:
        login = body.login.strip().lower()
        if not login: raise HTTPException(400, "Login é obrigatório")
        duplicate = await db.users.find_one({"login": login, "id": {"$ne": uid}})
        if duplicate: raise HTTPException(400, "Login já cadastrado")
        upd["login"] = login
    if body.role is not None and body.role not in {"admin", "vendedor", "producao"}:
        raise HTTPException(400, "Função inválida")
    if body.password: upd["password_hash"] = hash_pw(body.password)
    await db.users.update_one({"id": uid}, {"$set": upd})
    return await db.users.find_one({"id": uid}, {"password_hash": 0, "_id": 0})

@api.delete("/users/{uid}/hard")
async def delete_user_cascade(uid: str, user=Depends(require_admin)):
    if uid == user["id"]:
        raise HTTPException(400, "Não é possível excluir o próprio usuário")
    employee = await db.users.find_one({"id": uid})
    if not employee:
        raise HTTPException(404, "Funcionário não encontrado")

    sales = await db.sales.find({"seller_id": uid}, {"id": 1, "attachments": 1}).to_list(10000)
    sale_ids = [sale["id"] for sale in sales]
    upload_urls = [url for sale in sales for url in sale.get("attachments", [])]
    vales_count = await db.vales.count_documents({"user_id": uid})
    shopee_orders = await db.shopee_orders.find({"user_id": uid}, {"id": 1, "document_url": 1, "images": 1}).to_list(10000)
    for order in shopee_orders:
        upload_urls.extend([order.get("document_url", ""), *order.get("images", [])])

    if sale_ids:
        await db.audit_logs.delete_many({"sale_id": {"$in": sale_ids}})
        await db.sales.delete_many({"seller_id": uid})
    await db.vales.delete_many({"user_id": uid})
    await db.shopee_orders.delete_many({"user_id": uid})
    await db.audit_logs.delete_many({"user_id": uid})
    await db.users.delete_one({"id": uid})

    for url in upload_urls:
        filename = str(url).rsplit("/", 1)[-1]
        if filename and "/" not in filename and ".." not in filename:
            path = UPLOADS_DIR / filename
            if path.exists(): path.unlink()

    return {"ok": True, "deleted_sales": len(sale_ids), "deleted_vales": vales_count, "deleted_shopee_orders": len(shopee_orders)}

# ---------- Categories ----------
class CatIn(BaseModel):
    name: str; order: int = 0; active: bool = True; image_url: Optional[str] = ""

@api.get("/categories")
async def cats(user=Depends(get_user)):
    return await db.categories.find({}, {"_id": 0}).sort("order", 1).to_list(500)

@api.post("/categories")
async def cat_create(body: CatIn, user=Depends(require_admin)):
    d = {"id": new_id(), **body.model_dump(), "created_at": now_iso()}
    await db.categories.insert_one(d); d.pop("_id", None); return d

@api.put("/categories/{cid}")
async def cat_upd(cid: str, body: CatIn, user=Depends(require_admin)):
    await db.categories.update_one({"id": cid}, {"$set": body.model_dump()})
    return await db.categories.find_one({"id": cid}, {"_id": 0})

@api.delete("/categories/{cid}")
async def cat_del(cid: str, user=Depends(require_admin)):
    await db.categories.update_one({"id": cid}, {"$set": {"active": False}}); return {"ok": True}

# ---------- Lookups ----------
class NameIn(BaseModel):
    name: str; active: bool = True

def crud_lookup(coll):
    @api.get(f"/{coll}")
    async def _list(user=Depends(get_user)):
        return await db[coll].find({}, {"_id": 0}).to_list(500)
    @api.post(f"/{coll}")
    async def _create(body: NameIn, user=Depends(require_admin)):
        d = {"id": new_id(), **body.model_dump()}; await db[coll].insert_one(d); d.pop("_id", None); return d
    @api.delete(f"/{coll}/{{cid}}")
    async def _del(cid: str, user=Depends(require_admin)):
        await db[coll].update_one({"id": cid}, {"$set": {"active": False}}); return {"ok": True}

crud_lookup("channels"); crud_lookup("payment_methods"); crud_lookup("units")

# ---------- Products ----------
class Variation(BaseModel):
    id: Optional[str] = None; name: str; price: float = 0; active: bool = True

class ProductIn(BaseModel):
    name: str; category_id: str; description: Optional[str] = ""
    price: float = 0; price_type: str = "fixed"; unit: str = "Unidade"
    sku: Optional[str] = ""; active: bool = True; order: int = 0
    variations: List[Variation] = []; tiers: List[Dict[str, Any]] = []
    m2_min_price: Optional[float] = 0; m2_price: Optional[float] = 0
    image_url: Optional[str] = ""; favorite: bool = False
    is_starting_price: bool = False

@api.get("/products")
async def prods(user=Depends(get_user)):
    return await db.products.find({}, {"_id": 0}).sort([("favorite", -1), ("order", 1)]).to_list(2000)

@api.post("/products")
async def prod_create(body: ProductIn, user=Depends(require_staff)):
    d = body.model_dump(); d["id"] = new_id()
    for v in d.get("variations", []):
        if not v.get("id"): v["id"] = new_id()
    d["created_at"] = now_iso()
    await db.products.insert_one(d); d.pop("_id", None); return d

@api.put("/products/{pid}")
async def prod_upd(pid: str, body: ProductIn, user=Depends(require_staff)):
    d = body.model_dump()
    for v in d.get("variations", []):
        if not v.get("id"): v["id"] = new_id()
    await db.products.update_one({"id": pid}, {"$set": d})
    return await db.products.find_one({"id": pid}, {"_id": 0})

@api.delete("/products/{pid}")
async def prod_del(pid: str, user=Depends(require_admin)):
    await db.products.update_one({"id": pid}, {"$set": {"active": False}}); return {"ok": True}

@api.put("/products/{pid}/favorite")
async def prod_fav(pid: str, payload: Dict[str, Any], user=Depends(require_staff)):
    await db.products.update_one({"id": pid}, {"$set": {"favorite": bool(payload.get("favorite"))}})
    return {"ok": True}

# ---------- Uploads (images) ----------
def save_file_bytes(content: bytes, ext: str) -> str:
    fn = f"{new_id()}.{ext.lstrip('.').lower()}"
    (UPLOADS_DIR / fn).write_bytes(content)
    return f"/api/uploads/{fn}"

@api.post("/uploads")
async def upload_file(file: UploadFile = File(...), user=Depends(get_user)):
    content = await file.read()
    if len(content) > 8 * 1024 * 1024: raise HTTPException(400, "Arquivo maior que 8MB")
    ext = (file.filename.rsplit(".", 1)[-1] or "bin").lower()
    if ext not in ("png","jpg","jpeg","webp","gif","pdf"): raise HTTPException(400, "Formato inválido")
    url = save_file_bytes(content, ext)
    return {"url": url}

@api.get("/uploads/{fn}")
async def serve_upload(fn: str):
    if "/" in fn or ".." in fn: raise HTTPException(400)
    p = UPLOADS_DIR / fn
    if not p.exists(): raise HTTPException(404)
    ext = fn.rsplit(".", 1)[-1].lower()
    mime = {"png":"image/png","jpg":"image/jpeg","jpeg":"image/jpeg","webp":"image/webp","gif":"image/gif","pdf":"application/pdf"}.get(ext, "application/octet-stream")
    return FastResponse(p.read_bytes(), media_type=mime)

# ---------- Import CSV/XLSX ----------
@api.post("/products/import/preview")
async def import_preview(file: UploadFile = File(...), user=Depends(require_admin)):
    content = await file.read()
    try:
        if file.filename.lower().endswith(".csv"): df = pd.read_csv(io.BytesIO(content))
        else: df = pd.read_excel(io.BytesIO(content))
    except Exception as e: raise HTTPException(400, f"Erro ao ler arquivo: {e}")
    df.columns = [c.strip().lower() for c in df.columns]
    required = ["categoria", "produto", "preco"]
    missing = [c for c in required if c not in df.columns]
    if missing: raise HTTPException(400, f"Colunas faltando: {missing}")
    rows, errors = [], []
    for i, r in df.iterrows():
        try:
            rows.append({"categoria": str(r.get("categoria", "")).strip(), "produto": str(r.get("produto", "")).strip(),
                "variacao": str(r.get("variacao", "") or "").strip(), "preco": float(r.get("preco", 0) or 0),
                "unidade": str(r.get("unidade", "Unidade") or "Unidade").strip(),
                "tipo_preco": str(r.get("tipo_preco", "fixed") or "fixed").strip().lower(),
                "ativo": bool(r.get("ativo", True))})
        except Exception as e: errors.append({"line": int(i) + 2, "error": str(e)})
    return {"rows": rows, "errors": errors, "count": len(rows)}

@api.post("/products/import/confirm")
async def import_confirm(payload: Dict[str, Any], user=Depends(require_admin)):
    rows = payload.get("rows", []); created, updated = 0, 0
    for r in rows:
        cat = await db.categories.find_one({"name": r["categoria"]})
        if not cat:
            cat = {"id": new_id(), "name": r["categoria"], "order": 999, "active": True, "created_at": now_iso()}
            await db.categories.insert_one(cat)
        existing = await db.products.find_one({"name": r["produto"], "category_id": cat["id"]})
        if existing:
            if r["variacao"]:
                variations = existing.get("variations", [])
                if not any(v["name"] == r["variacao"] for v in variations):
                    variations.append({"id": new_id(), "name": r["variacao"], "price": r["preco"], "active": True})
                    await db.products.update_one({"id": existing["id"]}, {"$set": {"variations": variations}})
                    updated += 1
        else:
            doc = {"id": new_id(), "name": r["produto"], "category_id": cat["id"], "description": "",
                "price": r["preco"], "price_type": r["tipo_preco"], "unit": r["unidade"], "sku": "",
                "active": r["ativo"], "order": 0, "variations": [], "tiers": [], "m2_min_price": 0, "m2_price": 0,
                "image_url": "", "favorite": False, "is_starting_price": False, "created_at": now_iso()}
            if r["variacao"]:
                doc["variations"] = [{"id": new_id(), "name": r["variacao"], "price": r["preco"], "active": True}]
            await db.products.insert_one(doc); created += 1
    return {"created": created, "updated": updated}

# ---------- Customers ----------
class CustomerIn(BaseModel):
    name: str; phone: str = ""; notes: str = ""

@api.get("/customers")
async def cust_list(q: Optional[str] = None, user=Depends(get_user)):
    query = {}
    if q: query = {"$or": [{"name": {"$regex": q, "$options": "i"}}, {"phone": {"$regex": q, "$options": "i"}}]}
    return await db.customers.find(query, {"_id": 0}).sort("name", 1).to_list(500)

@api.post("/customers")
async def cust_create(body: CustomerIn, user=Depends(get_user)):
    if body.phone:
        ex = await db.customers.find_one({"phone": body.phone})
        if ex: return {k: v for k, v in ex.items() if k != "_id"}
    d = {"id": new_id(), **body.model_dump(), "created_at": now_iso()}
    await db.customers.insert_one(d); d.pop("_id", None); return d

@api.put("/customers/{cid}")
async def cust_upd(cid: str, body: CustomerIn, user=Depends(get_user)):
    await db.customers.update_one({"id": cid}, {"$set": body.model_dump()})
    return await db.customers.find_one({"id": cid}, {"_id": 0})

@api.delete("/customers/{cid}")
async def cust_del(cid: str, user=Depends(require_admin)):
    c = await db.customers.find_one({"id": cid})
    if not c:
        raise HTTPException(404, "Cliente não encontrado")
    linked = await db.sales.count_documents({"customer_id": cid})
    if linked > 0:
        raise HTTPException(400, f"Cliente possui {linked} pedido(s) vinculado(s). Exclua ou cancele os pedidos antes.")
    await db.customers.delete_one({"id": cid})
    await db.audit_logs.insert_one({"id": new_id(), "user_id": user["id"], "action": "customer_delete",
        "customer_id": cid, "customer_name": c.get("name"), "at": now_iso()})
    return {"ok": True}

@api.get("/customers/{cid}")
async def cust_get(cid: str, user=Depends(get_user)):
    c = await db.customers.find_one({"id": cid}, {"_id": 0})
    if not c: raise HTTPException(404)
    sales = await db.sales.find({"customer_id": cid}, {"_id": 0}).sort("created_at", -1).to_list(500)
    total = sum(s.get("total", 0) for s in sales)
    pending = sum(s.get("balance", 0) for s in sales)
    return {"customer": c, "sales": sales, "total_spent": total, "pending": pending, "orders_count": len(sales)}

# ---------- Sales ----------
class SaleItem(BaseModel):
    product_id: str; variation_id: Optional[str] = None
    product_name: str; variation_name: Optional[str] = ""
    quantity: float = 1; catalog_price: float = 0; unit_price: float = 0
    discount: float = 0; subtotal: float = 0
    m2_data: Optional[Dict[str, Any]] = None; notes: Optional[str] = ""
    image_url: Optional[str] = ""

class Payment(BaseModel):
    method: str; amount: float

class SaleIn(BaseModel):
    customer_id: Optional[str] = None; customer_name: str = ""; customer_phone: str = ""
    items: List[SaleItem]; discount: float = 0; surcharge: float = 0
    total: float; paid: float = 0; payments: List[Payment] = []
    channel: str = "Loja"; status: str = "PEDIDO RECEBIDO"
    delivery_date: Optional[str] = None; notes: str = ""
    attachments: List[str] = []
    send_to_production: bool = True

async def next_order_number():
    counter = await db.counters.find_one_and_update({"id": "order"}, {"$inc": {"seq": 1}}, upsert=True, return_document=True)
    return (counter.get("seq", 1) if counter else 1)

async def ensure_customer(name: str, phone: str) -> Optional[str]:
    """Auto-create/find customer by phone."""
    if not phone and not name: return None
    if phone:
        ex = await db.customers.find_one({"phone": phone})
        if ex: return ex["id"]
    cid = new_id()
    await db.customers.insert_one({"id": cid, "name": name or "Cliente", "phone": phone, "notes": "", "created_at": now_iso()})
    return cid

@api.post("/sales")
async def sale_create(body: SaleIn, user=Depends(get_user)):
    now = datetime.now(timezone.utc)
    order_no = await next_order_number()
    balance = round(body.total - body.paid, 2)
    d = body.model_dump()
    if not d.get("customer_id"):
        d["customer_id"] = await ensure_customer(d.get("customer_name", ""), d.get("customer_phone", ""))
    d.update({"id": new_id(), "order_number": order_no, "seller_id": user["id"], "seller_name": user["name"],
        "balance": balance, "created_at": now.isoformat(), "day": now.day, "month": now.month, "year": now.year,
        "weekday": now.strftime("%A"), "cancelled": False})
    await db.sales.insert_one(d); d.pop("_id", None)
    await db.audit_logs.insert_one({"id": new_id(), "user_id": user["id"], "user_name": user["name"],
        "action": "sale_create", "sale_id": d["id"], "at": now.isoformat()})
    return d

@api.get("/sales")
async def sale_list(user=Depends(get_user), start: Optional[str] = None, end: Optional[str] = None,
                    seller_id: Optional[str] = None, status: Optional[str] = None, q: Optional[str] = None):
    query = {}
    if user["role"] == "vendedor": query["seller_id"] = user["id"]
    if seller_id: query["seller_id"] = seller_id
    if status: query["status"] = status
    if start or end:
        rng = {}
        if start: rng["$gte"] = start
        if end: rng["$lte"] = end + "T23:59:59"
        query["created_at"] = rng
    if q:
        query["$or"] = [{"customer_name": {"$regex": q, "$options": "i"}}, {"customer_phone": {"$regex": q, "$options": "i"}}]
    return await db.sales.find(query, {"_id": 0}).sort("created_at", -1).to_list(2000)

@api.get("/sales/{sid}")
async def sale_get(sid: str, user=Depends(get_user)):
    s = await db.sales.find_one({"id": sid}, {"_id": 0})
    if not s: raise HTTPException(404)
    if user["role"] == "vendedor" and s.get("seller_id") != user["id"]: raise HTTPException(403)
    return s

@api.put("/sales/{sid}")
async def sale_upd(sid: str, body: SaleIn, user=Depends(get_user)):
    s = await db.sales.find_one({"id": sid})
    if not s: raise HTTPException(404)
    if user["role"] == "vendedor" and s.get("seller_id") != user["id"]: raise HTTPException(403)
    d = body.model_dump()
    d["balance"] = round(body.total - body.paid, 2)
    if not d.get("customer_id"):
        d["customer_id"] = await ensure_customer(d.get("customer_name", ""), d.get("customer_phone", ""))
    await db.sales.update_one({"id": sid}, {"$set": d})
    await db.audit_logs.insert_one({"id": new_id(), "user_id": user["id"], "user_name": user["name"],
        "action": "sale_update", "sale_id": sid, "at": now_iso()})
    return await db.sales.find_one({"id": sid}, {"_id": 0})

@api.post("/sales/{sid}/duplicate")
async def sale_dup(sid: str, user=Depends(get_user)):
    s = await db.sales.find_one({"id": sid}, {"_id": 0})
    if not s: raise HTTPException(404)
    now = datetime.now(timezone.utc)
    order_no = await next_order_number()
    new_sale = {**s, "id": new_id(), "order_number": order_no, "seller_id": user["id"], "seller_name": user["name"],
                "created_at": now.isoformat(), "day": now.day, "month": now.month, "year": now.year,
                "weekday": now.strftime("%A"), "cancelled": False, "status": "PEDIDO RECEBIDO",
                "paid": 0, "payments": [], "balance": s.get("total", 0), "attachments": []}
    await db.sales.insert_one(new_sale); new_sale.pop("_id", None); return new_sale

@api.put("/sales/{sid}/status")
async def sale_status(sid: str, payload: Dict[str, Any], user=Depends(get_user)):
    status = payload["status"]
    now = now_iso()
    update = {"$set": {"status": status}}
    if status == "ENTREGUE":
        update["$set"]["delivered_at"] = now
    else:
        update["$unset"] = {"delivered_at": ""}
    await db.sales.update_one({"id": sid}, update)
    await db.audit_logs.insert_one({"id": new_id(), "user_id": user["id"], "action": "status_change",
        "sale_id": sid, "status": status, "at": now})
    return {"ok": True}

@api.post("/sales/{sid}/payment")
async def sale_pay(sid: str, body: Payment, user=Depends(get_user)):
    s = await db.sales.find_one({"id": sid})
    if not s: raise HTTPException(404)
    payments = s.get("payments", []) + [{"method": body.method, "amount": body.amount, "at": now_iso()}]
    paid = round(s.get("paid", 0) + body.amount, 2); balance = round(s["total"] - paid, 2)
    await db.sales.update_one({"id": sid}, {"$set": {"payments": payments, "paid": paid, "balance": balance}})
    return {"ok": True, "paid": paid, "balance": balance}

@api.post("/sales/{sid}/attachments")
async def sale_attach(sid: str, payload: Dict[str, Any], user=Depends(get_user)):
    url = payload.get("url")
    if not url: raise HTTPException(400)
    await db.sales.update_one({"id": sid}, {"$push": {"attachments": url}})
    return {"ok": True}

@api.delete("/sales/{sid}/attachments")
async def sale_detach(sid: str, url: str, user=Depends(get_user)):
    await db.sales.update_one({"id": sid}, {"$pull": {"attachments": url}})
    return {"ok": True}

@api.delete("/sales/{sid}")
async def sale_cancel(sid: str, user=Depends(require_admin)):
    await db.sales.update_one({"id": sid}, {"$set": {"cancelled": True, "status": "CANCELADO"}})
    await db.audit_logs.insert_one({"id": new_id(), "user_id": user["id"], "action": "sale_cancel",
        "sale_id": sid, "at": now_iso()})
    return {"ok": True}

@api.delete("/sales/{sid}/hard")
async def sale_hard_delete(sid: str, user=Depends(require_admin)):
    sale = await db.sales.find_one({"id": sid})
    if not sale:
        raise HTTPException(404, "Pedido não encontrado")
    if not sale.get("cancelled") and sale.get("status") != "CANCELADO":
        raise HTTPException(400, "Só é possível excluir permanentemente pedidos cancelados")
    await db.sales.delete_one({"id": sid})
    await db.audit_logs.insert_one({"id": new_id(), "user_id": user["id"], "action": "sale_hard_delete",
        "sale_id": sid, "order_number": sale.get("order_number"), "at": now_iso()})
    return {"ok": True}

# ---------- PDF: Note / Production Order ----------
def _fmt_brl(v: float) -> str:
    try: return "R$ " + f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception: return "R$ 0,00"

async def _build_pdf(sale: dict, mode: str) -> bytes:
    """mode = 'note' or 'production'"""
    s = await db.settings.find_one({"id": "main"}) or {}
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15*mm, rightMargin=15*mm, topMargin=12*mm, bottomMargin=12*mm)
    styles = getSampleStyleSheet()
    story = []
    # Header
    title = "NOTA DO PEDIDO" if mode == "note" else "ORDEM DE PRODUÇÃO"
    logo_path = ROOT_DIR.parent / "frontend" / "public" / "riosul-logo.png"
    header_cells = []
    if logo_path.exists():
        header_cells.append(RLImage(str(logo_path), width=45*mm, height=22*mm))
    else:
        header_cells.append(Paragraph("<b>RIO SUL FESTAS & GRÁFICA</b>", styles["Title"]))
    company_info = f"<b>{s.get('company_name','Rio Sul Festas & Gráfica')}</b><br/>{s.get('address','')}<br/>Tel: {s.get('phone','')} · WhatsApp: {s.get('whatsapp','')}<br/>{s.get('email','')} · CNPJ: {s.get('cnpj','')}"
    header_cells.append(Paragraph(company_info, styles["Normal"]))
    header_table = Table([header_cells], colWidths=[55*mm, 120*mm])
    header_table.setStyle(TableStyle([("VALIGN", (0,0), (-1,-1), "TOP")]))
    story.append(header_table)
    story.append(Spacer(1, 4*mm))
    title_bar = Table([[Paragraph(f"<b>{title}</b>", styles["Heading2"]), Paragraph(f"<b>Nº {sale.get('order_number','-')}</b>", styles["Heading2"])]], colWidths=[100*mm, 75*mm])
    title_bar.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),colors.HexColor("#111827")),
        ("TEXTCOLOR",(0,0),(-1,-1),colors.white), ("ALIGN",(1,0),(1,0),"RIGHT"),
        ("LEFTPADDING",(0,0),(-1,-1),6), ("RIGHTPADDING",(0,0),(-1,-1),6),
        ("TOPPADDING",(0,0),(-1,-1),4), ("BOTTOMPADDING",(0,0),(-1,-1),4)]))
    story.append(title_bar); story.append(Spacer(1, 3*mm))
    # Meta
    from datetime import datetime as _dt
    created = sale.get("created_at","")[:10]
    meta = [[f"Cliente: {sale.get('customer_name','-')}", f"Data: {created}"],
            [f"Telefone: {sale.get('customer_phone','-')}", f"Vendedor: {sale.get('seller_name','-')}"],
            [f"Canal: {sale.get('channel','-')}", f"Status: {sale.get('status','-')}"],
            [f"Prazo: {sale.get('delivery_date') or '-'}", f"Pagamento: {', '.join([p.get('method','') for p in sale.get('payments',[])]) or '-'}"]]
    mt = Table(meta, colWidths=[95*mm, 80*mm])
    mt.setStyle(TableStyle([("BOX",(0,0),(-1,-1),0.5,colors.grey), ("INNERGRID",(0,0),(-1,-1),0.25,colors.lightgrey),
        ("FONTSIZE",(0,0),(-1,-1),9), ("LEFTPADDING",(0,0),(-1,-1),5), ("TOPPADDING",(0,0),(-1,-1),3), ("BOTTOMPADDING",(0,0),(-1,-1),3)]))
    story.append(mt); story.append(Spacer(1, 4*mm))
    # Items
    if mode == "note":
        header = ["Qtd", "Descrição", "Unit.", "Total"]
        rows = [[f"{it.get('quantity',0)}", f"{it.get('product_name','')}{(' - ' + it['variation_name']) if it.get('variation_name') else ''}",
                 _fmt_brl(it.get("unit_price",0)), _fmt_brl(it.get("subtotal",0))] for it in sale.get("items", [])]
        colw = [15*mm, 110*mm, 25*mm, 25*mm]
    else:
        header = ["Qtd", "Descrição", "Observações"]
        rows = [[f"{it.get('quantity',0)}", f"{it.get('product_name','')}{(' - ' + it['variation_name']) if it.get('variation_name') else ''}",
                 it.get("notes","") or ""] for it in sale.get("items", [])]
        colw = [15*mm, 90*mm, 70*mm]
    it_table = Table([header] + rows, colWidths=colw, repeatRows=1)
    it_table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#EC4899")),
        ("TEXTCOLOR",(0,0),(-1,0),colors.white), ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("GRID",(0,0),(-1,-1),0.5,colors.grey), ("FONTSIZE",(0,0),(-1,-1),9),
        ("LEFTPADDING",(0,0),(-1,-1),4), ("TOPPADDING",(0,0),(-1,-1),3), ("BOTTOMPADDING",(0,0),(-1,-1),3),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white, colors.HexColor("#F9FAFB")])]))
    story.append(it_table); story.append(Spacer(1, 3*mm))
    # Totals only for note
    if mode == "note":
        totals = [["Subtotal", _fmt_brl(sum(i.get("subtotal",0) for i in sale.get("items",[])))],
                  ["Desconto", _fmt_brl(sale.get("discount",0))],
                  ["Acréscimo", _fmt_brl(sale.get("surcharge",0))],
                  ["TOTAL", _fmt_brl(sale.get("total",0))],
                  ["Pago", _fmt_brl(sale.get("paid",0))],
                  ["SALDO", _fmt_brl(sale.get("balance",0))]]
        tt = Table(totals, colWidths=[130*mm, 45*mm])
        tt.setStyle(TableStyle([("FONTSIZE",(0,0),(-1,-1),10),("ALIGN",(1,0),(1,-1),"RIGHT"),
            ("BACKGROUND",(0,3),(-1,3),colors.HexColor("#06B6D4")),("TEXTCOLOR",(0,3),(-1,3),colors.white),
            ("FONTNAME",(0,3),(-1,3),"Helvetica-Bold"), ("FONTNAME",(0,5),(-1,5),"Helvetica-Bold"),
            ("BACKGROUND",(0,5),(-1,5),colors.HexColor("#EAB308")),
            ("BOX",(0,0),(-1,-1),0.5,colors.grey), ("LEFTPADDING",(0,0),(-1,-1),6),
            ("TOPPADDING",(0,0),(-1,-1),4), ("BOTTOMPADDING",(0,0),(-1,-1),4)]))
        story.append(tt)
    if sale.get("notes"):
        story.append(Spacer(1, 4*mm))
        story.append(Paragraph(f"<b>Observações:</b> {sale.get('notes','')}", styles["Normal"]))
    # Attachments (production order)
    if mode == "production" and sale.get("attachments"):
        story.append(Spacer(1, 4*mm))
        story.append(Paragraph("<b>Referências / Artes:</b>", styles["Heading3"]))
        for att in sale.get("attachments", [])[:6]:
            try:
                if att.startswith("/api/uploads/"):
                    fn = att.split("/")[-1]
                    p = UPLOADS_DIR / fn
                    if p.exists():
                        story.append(RLImage(str(p), width=80*mm, height=60*mm))
                        story.append(Spacer(1, 2*mm))
            except Exception: pass
    if s.get("receipt_footer"):
        story.append(Spacer(1, 6*mm))
        story.append(Paragraph(f"<i>{s.get('receipt_footer')}</i>", styles["Italic"]))
    doc.build(story)
    return buf.getvalue()

@api.get("/sales/{sid}/pdf/note")
async def sale_pdf_note(sid: str, user=Depends(get_user)):
    s = await db.sales.find_one({"id": sid}, {"_id": 0})
    if not s: raise HTTPException(404)
    data = await _build_pdf(s, "note")
    return StreamingResponse(io.BytesIO(data), media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=pedido_{s.get('order_number')}.pdf"})

@api.get("/sales/{sid}/pdf/production")
async def sale_pdf_prod(sid: str, user=Depends(get_user)):
    s = await db.sales.find_one({"id": sid}, {"_id": 0})
    if not s: raise HTTPException(404)
    data = await _build_pdf(s, "production")
    return StreamingResponse(io.BytesIO(data), media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=os_{s.get('order_number')}.pdf"})

# ---------- Dashboard ----------
@api.get("/dashboard")
async def dashboard(user=Depends(get_user)):
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    q = {"cancelled": {"$ne": True}}
    if user["role"] == "vendedor": q["seller_id"] = user["id"]
    async def _q(m): return await db.sales.find({**q, **m}, {"_id": 0}).to_list(5000)
    today_sales = await _q({"created_at": {"$gte": today}})
    month_sales = await _q({"created_at": {"$gte": month_start}})
    all_open = await _q({"status": {"$nin": ["ENTREGUE", "CANCELADO"]}})
    ready = await _q({"status": "PRONTO"})
    in_prod = await _q({"status": {"$in": ["EM PRODUÇÃO","ARTE APROVADA","ARTE EM CRIAÇÃO"]}})
    def st(a): return round(sum(x.get("total",0) for x in a),2)
    def sb(a): return round(sum(x.get("balance",0) for x in a),2)
    late = [s for s in all_open if s.get("delivery_date") and s["delivery_date"] < today]
    by_seller = {}
    for s in month_sales:
        k = s.get("seller_id"); by_seller.setdefault(k, {"seller_name": s.get("seller_name"), "count": 0, "total": 0})
        by_seller[k]["count"] += 1; by_seller[k]["total"] += s.get("total", 0)
    by_channel = {}
    for s in month_sales:
        k = s.get("channel","Outro"); by_channel[k] = by_channel.get(k,0) + s.get("total",0)
    daily = {}
    for s in month_sales:
        d = s.get("created_at","")[:10]; daily[d] = daily.get(d,0) + s.get("total",0)
    return {"vendas_hoje": len(today_sales), "faturamento_hoje": st(today_sales), "faturamento_mes": st(month_sales),
        "pedidos_hoje": len(today_sales), "ticket_medio": round(st(today_sales)/len(today_sales),2) if today_sales else 0,
        "valores_a_receber": sb(all_open), "pedidos_producao": len(in_prod), "pedidos_prontos": len(ready),
        "pedidos_atrasados": len(late), "by_seller": list(by_seller.values()),
        "by_channel": [{"name":k,"total":round(v,2)} for k,v in by_channel.items()],
        "daily": [{"date":k,"total":round(v,2)} for k,v in sorted(daily.items())]}

@api.get("/cash/closure")
async def closure(date: Optional[str] = None, seller_id: Optional[str] = None, user=Depends(get_user)):
    if not date: date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    q = {"created_at": {"$gte": date, "$lte": date + "T23:59:59"}, "cancelled": {"$ne": True}}
    if seller_id: q["seller_id"] = seller_id
    sales = await db.sales.find(q, {"_id": 0}).to_list(5000)
    by_method = {}; total_sold=0; total_received=0; total_pending=0
    for s in sales:
        total_sold += s.get("total",0); total_received += s.get("paid",0); total_pending += s.get("balance",0)
        for p in s.get("payments",[]): by_method[p["method"]] = by_method.get(p["method"],0) + p["amount"]
    return {"date": date, "by_method": [{"method":k,"total":round(v,2)} for k,v in by_method.items()],
        "total_sold": round(total_sold,2), "total_received": round(total_received,2),
        "total_pending": round(total_pending,2), "count": len(sales),
        "ticket_medio": round(total_sold/len(sales),2) if sales else 0}

# ---------- Vales ----------
class ValeIn(BaseModel):
    user_id: str; amount: float; date: Optional[str] = None; notes: str = ""

@api.get("/vales")
async def vales_list(user_id: Optional[str] = None, user=Depends(get_user)):
    q = {}
    if user["role"] in {"vendedor", "producao"}: q["user_id"] = user["id"]
    elif user_id: q["user_id"] = user_id
    return await db.vales.find(q, {"_id": 0}).sort("date", -1).to_list(1000)

@api.post("/vales")
async def vales_create(body: ValeIn, user=Depends(require_staff)):
    if user["role"] != "admin" and body.user_id != user["id"]:
        raise HTTPException(403, "Você só pode registrar vale para seu próprio usuário")
    d = body.model_dump()
    if not d.get("date"): d["date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d["id"] = new_id(); d["created_at"] = now_iso()
    u = await db.users.find_one({"id": body.user_id}); d["user_name"] = u["name"] if u else ""
    await db.vales.insert_one(d); d.pop("_id", None); return d

@api.delete("/vales/{vid}")
async def vales_del(vid: str, user=Depends(require_admin)):
    await db.vales.delete_one({"id": vid}); return {"ok": True}

# ---------- Reports ----------
@api.get("/reports/sales")
async def report_sales(start: Optional[str] = None, end: Optional[str] = None,
                       group_by: str = "day", user=Depends(require_admin)):
    q = {"cancelled": {"$ne": True}}
    if start or end:
        rng = {}
        if start: rng["$gte"] = start
        if end: rng["$lte"] = end + "T23:59:59"
        q["created_at"] = rng
    sales = await db.sales.find(q, {"_id": 0}).to_list(10000); groups = {}
    for s in sales:
        if group_by == "day": k = s.get("created_at","")[:10]
        elif group_by == "seller": k = s.get("seller_name","")
        elif group_by == "channel": k = s.get("channel","")
        elif group_by == "month": k = s.get("created_at","")[:7]
        else: k = "all"
        groups.setdefault(k, {"count":0,"total":0,"paid":0,"balance":0})
        groups[k]["count"] += 1; groups[k]["total"] += s.get("total",0)
        groups[k]["paid"] += s.get("paid",0); groups[k]["balance"] += s.get("balance",0)
    return [{"key":k, **{kk:round(vv,2) for kk,vv in v.items()}} for k,v in sorted(groups.items())]

@api.get("/reports/top-products")
async def report_top(user=Depends(require_admin)):
    sales = await db.sales.find({"cancelled": {"$ne": True}}, {"_id": 0}).to_list(10000); counts = {}
    for s in sales:
        for it in s.get("items", []):
            k = it.get("product_name",""); counts.setdefault(k, {"count":0,"total":0})
            counts[k]["count"] += it.get("quantity",0); counts[k]["total"] += it.get("subtotal",0)
    result = [{"name":k, **{kk:round(vv,2) for kk,vv in v.items()}} for k,v in counts.items()]
    result.sort(key=lambda x: x["total"], reverse=True); return result[:50]

# ---------- Settings ----------
@api.get("/settings")
async def settings_get(user=Depends(get_user)):
    s = await db.settings.find_one({"id": "main"}, {"_id": 0}) or {}; return s

@api.put("/settings")
async def settings_upd(body: Dict[str, Any], user=Depends(require_admin)):
    body.pop("_id", None); body["id"] = "main"
    await db.settings.update_one({"id": "main"}, {"$set": body}, upsert=True)
    return await db.settings.find_one({"id": "main"}, {"_id": 0})

# ---------- Price Tables ----------
class PriceTableIn(BaseModel):
    title: str; category_id: Optional[str] = None
    image_url: Optional[str] = ""; active: bool = True

@api.get("/price-tables")
async def pt_list(user=Depends(get_user)):
    return await db.price_tables.find({}, {"_id": 0}).sort("created_at", -1).to_list(500)

@api.post("/price-tables")
async def pt_create(body: PriceTableIn, user=Depends(require_admin)):
    d = {"id": new_id(), **body.model_dump(), "created_at": now_iso(), "updated_at": now_iso()}
    await db.price_tables.insert_one(d); d.pop("_id", None); return d

@api.put("/price-tables/{tid}")
async def pt_upd(tid: str, body: PriceTableIn, user=Depends(require_admin)):
    upd = {**body.model_dump(), "updated_at": now_iso()}
    await db.price_tables.update_one({"id": tid}, {"$set": upd})
    return await db.price_tables.find_one({"id": tid}, {"_id": 0})

@api.delete("/price-tables/{tid}")
async def pt_del(tid: str, user=Depends(require_admin)):
    await db.price_tables.delete_one({"id": tid}); return {"ok": True}

# ---------- Central Shopee: ZIP import ----------
SHOPEE_MAX_FILES = 200
SHOPEE_MAX_UNCOMPRESSED = 200 * 1024 * 1024  # 200MB

def _safe_zip_extract(zip_bytes: bytes):
    """Yield (filename, content) safely."""
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    if len(zf.infolist()) > SHOPEE_MAX_FILES:
        raise HTTPException(400, "ZIP com muitos arquivos")
    total = 0
    for info in zf.infolist():
        if info.is_dir(): continue
        # Path traversal protection
        name = info.filename
        if name.startswith("/") or ".." in name or "\x00" in name: continue
        if info.file_size > 20 * 1024 * 1024: continue
        total += info.file_size
        if total > SHOPEE_MAX_UNCOMPRESSED: raise HTTPException(400, "ZIP excede tamanho descompactado permitido")
        with zf.open(info) as f: content = f.read()
        yield name, content

def _split_zpl_labels(zpl_text: str) -> List[str]:
    """Split ZPL stream into individual labels (^XA...^XZ)."""
    matches = re.findall(r"\^XA.*?\^XZ", zpl_text, flags=re.DOTALL)
    return matches or ([zpl_text] if zpl_text.strip() else [])

def _extract_shopee_info_zpl(zpl_text: str) -> dict:
    """Extract customer name and order number from a raw ZPL label.
    Looks at ^FD (field data) values which hold printable label text.
    """
    result = {"customer_name": None, "order_number": None, "raw_text": ""}
    try:
        # Pull every ^FDvalue^FS
        fields = re.findall(r"\^FD([^\^]*)\^FS", zpl_text)
        # Cleanup lines
        lines = [f.strip() for f in fields if f and f.strip()]
        result["raw_text"] = "\n".join(lines)[:3000]
        text = "\n".join(lines)

        # Order number: Shopee IDs typically 14-20 digits, e.g., 2410XXXXXXXXXXXX
        m = re.search(r"(?:N[º°]?\s*(?:do\s*)?[Pp]edido|Order\s*(?:No|ID)|C[óo]digo\s*do\s*Pedido|BR\d{15,})[:\s]*([A-Z0-9]{10,25})", text)
        if not m:
            m = re.search(r"\bBR\d{15,20}\b", text)
            if m:
                result["order_number"] = m.group(0).strip()
        else:
            result["order_number"] = m.group(1).strip()
        if not result["order_number"]:
            m = re.search(r"\b(\d{15,20})\b", text)
            if m: result["order_number"] = m.group(1).strip()

        # Customer name: look for label after "Destinatário"/"Recebedor"/"Ship to"
        for i, l in enumerate(lines):
            if re.match(r"^(destinat[áa]rio|recebedor|ship\s*to|para|nome do destinat[áa]rio|entregar)\s*[:\-]?\s*(.*)$", l, re.I):
                # value may be on same line after colon or next line
                same = re.split(r"[:\-]", l, maxsplit=1)
                if len(same) > 1 and same[1].strip():
                    result["customer_name"] = same[1].strip()
                elif i + 1 < len(lines):
                    result["customer_name"] = lines[i + 1].strip()
                break
        if not result["customer_name"]:
            # Fallback: first CAPITALIZED name-like line (2+ words, letters only)
            for l in lines:
                if re.match(r"^[A-ZÀ-Ÿ][A-Za-zÀ-ÿ\.\s]{4,60}$", l) and len(l.split()) >= 2 and not any(w in l.upper() for w in ("SHOPEE","BRASIL","RUA","AV","AVENIDA","CEP","CNPJ","NF","BR")):
                    result["customer_name"] = l.strip(); break
    except Exception as e:
        result["error"] = str(e)
    return result

def _zpl_to_pdf(zpl_text: str) -> bytes:
    """Render ZPL to PDF via Labelary public API (203 dpi = 8 dpmm, 4x6")."""
    import httpx
    labels = _split_zpl_labels(zpl_text)
    if not labels:
        raise HTTPException(400, "ZPL vazio")
    # Concatenate all labels and let Labelary paginate via index 0 = first;
    # but a cleaner approach: request each label then merge with pypdf.
    writer = PdfWriter()
    with httpx.Client(timeout=30.0) as client_http:
        for idx, lb in enumerate(labels):
            r = client_http.post(
                "http://api.labelary.com/v1/printers/8dpmm/labels/4x6/0/",
                content=lb.encode("utf-8"),
                headers={"Accept": "application/pdf", "Content-Type": "application/x-www-form-urlencoded"},
            )
            if r.status_code != 200:
                raise HTTPException(502, f"Falha ao renderizar etiqueta {idx+1}: Labelary {r.status_code}")
            reader = PdfReader(io.BytesIO(r.content))
            for pg in reader.pages: writer.add_page(pg)
    buf = io.BytesIO(); writer.write(buf); return buf.getvalue()

def _extract_shopee_info(pdf_bytes: bytes) -> dict:
    """Extract customer and order number from PDF text."""
    result = {"customer_name": None, "order_number": None, "raw_text": ""}
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            text_parts = [p.extract_text() or "" for p in pdf.pages]
            text = "\n".join(text_parts)
        result["raw_text"] = text[:3000]
        # Order number patterns
        m = re.search(r"(?:N[º°]?\s*(?:do\s*)?[Pp]edido|Order\s*(?:No|ID)|C[óo]digo\s*do\s*Pedido)[:\s]*([A-Z0-9]{6,25})", text)
        if not m: m = re.search(r"\b(\d{15,20})\b", text)  # long Shopee IDs
        if not m: m = re.search(r"\b([A-Z]{2}\d{10,18})\b", text)  # tracking-like
        if m: result["order_number"] = m.group(1).strip()
        # Customer name patterns
        m = re.search(r"(?:Destinat[áa]rio|Recipient|Nome|To|Para|Cliente)[:\s]+([A-Z][A-Za-zÀ-ÿ\s]{2,60})", text)
        if m: result["customer_name"] = m.group(1).strip().split("\n")[0]
        else:
            # Try: first CAPITAL name after "Ship to" style
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            for i, l in enumerate(lines):
                if re.match(r"^(SHIP\s*TO|ENTREGAR|DELIVER\s*TO)", l, re.I):
                    for j in range(i+1, min(i+4, len(lines))):
                        if re.match(r"^[A-ZÀ-Ÿ][A-Za-zÀ-ÿ\s]{2,60}$", lines[j]):
                            result["customer_name"] = lines[j]; break
                    break
    except Exception as e:
        result["error"] = str(e)
    return result

@api.post("/shopee/convert-zpl")
async def shopee_convert_zpl(file: UploadFile = File(...), user=Depends(get_user)):
    """Convert a Shopee ZIP (containing ZPL/TXT/PRN) directly to a single merged PDF
    with all labels — same behavior as the Converter_Shopee.ps1 script."""
    content = await file.read()
    if len(content) > 30 * 1024 * 1024: raise HTTPException(400, "ZIP maior que 30MB")
    if not (file.filename or "").lower().endswith(".zip"): raise HTTPException(400, "Envie um arquivo .zip")
    if content[:2] != b"PK": raise HTTPException(400, "Arquivo não é um ZIP válido")
    combined_parts: List[str] = []
    try:
        for name, data in _safe_zip_extract(content):
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if ext not in ("zpl", "txt", "prn"): continue
            try:
                combined_parts.append(data.decode("utf-8", errors="ignore"))
            except Exception:
                continue
    except HTTPException: raise
    except Exception as e: raise HTTPException(400, f"Erro processando ZIP: {e}")
    if not combined_parts:
        raise HTTPException(400, "Não encontrei TXT/ZPL/PRN dentro do ZIP")
    combined = "\r\n".join(combined_parts)
    if "^XA" not in combined:
        raise HTTPException(400, "Arquivos sem etiquetas ZPL válidas")
    pdf_bytes = _zpl_to_pdf(combined)
    return StreamingResponse(io.BytesIO(pdf_bytes), media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=Etiquetas_Shopee.pdf"})

@api.post("/shopee/import")
async def shopee_import(file: UploadFile = File(...), user=Depends(get_user)):
    content = await file.read()
    if len(content) > 30 * 1024 * 1024: raise HTTPException(400, "ZIP maior que 30MB")
    if not (file.filename or "").lower().endswith(".zip"): raise HTTPException(400, "Envie um arquivo .zip")
    if content[:2] != b"PK": raise HTTPException(400, "Arquivo não é um ZIP válido")
    imported = []; skipped = []; duplicates = []
    try:
        for name, data in _safe_zip_extract(content):
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if ext in ("zpl", "txt", "prn"):
                # Shopee sends labels in ZPL text. Split, extract info, render to PDF via Labelary.
                try:
                    zpl_text = data.decode("utf-8", errors="ignore")
                except Exception:
                    skipped.append({"file": name, "reason": "não foi possível ler o arquivo"}); continue
                if "^XA" not in zpl_text:
                    skipped.append({"file": name, "reason": "arquivo sem etiquetas ZPL válidas"}); continue
                labels = _split_zpl_labels(zpl_text)
                for lb_idx, lb in enumerate(labels):
                    info = _extract_shopee_info_zpl(lb)
                    order_no = info.get("order_number") or f"S-{new_id()[:8].upper()}"
                    if await db.shopee_orders.find_one({"order_number": order_no, "identified": True}):
                        duplicates.append(order_no); continue
                    try:
                        pdf_bytes = _zpl_to_pdf(lb)
                    except HTTPException as e:
                        skipped.append({"file": name, "reason": f"etiqueta {lb_idx+1}: {e.detail}"}); continue
                    except Exception as e:
                        skipped.append({"file": name, "reason": f"etiqueta {lb_idx+1}: {e}"}); continue
                    url = save_file_bytes(pdf_bytes, "pdf")
                    doc = {"id": new_id(), "order_number": order_no,
                        "customer_name": info.get("customer_name") or None,
                        "identified": bool(info.get("order_number")) and bool(info.get("customer_name")),
                        "source_file": name, "page_index": lb_idx,
                        "document_url": url, "images": [], "status": "AGUARDANDO IMAGEM",
                        "notes": "", "created_at": now_iso(), "user_id": user["id"],
                        "source_format": "zpl"}
                    await db.shopee_orders.insert_one(doc); doc.pop("_id", None); imported.append(doc)
            elif ext == "pdf":
                # split PDF into pages, each page as separate order
                try:
                    reader = PdfReader(io.BytesIO(data))
                except Exception:
                    skipped.append({"file": name, "reason": "PDF inválido"}); continue
                for pg_idx in range(len(reader.pages)):
                    writer = PdfWriter(); writer.add_page(reader.pages[pg_idx])
                    buf = io.BytesIO(); writer.write(buf); pg_bytes = buf.getvalue()
                    info = _extract_shopee_info(pg_bytes)
                    order_no = info.get("order_number") or f"S-{new_id()[:8].upper()}"
                    if await db.shopee_orders.find_one({"order_number": order_no, "identified": True}):
                        duplicates.append(order_no); continue
                    url = save_file_bytes(pg_bytes, "pdf")
                    doc = {"id": new_id(), "order_number": order_no,
                        "customer_name": info.get("customer_name") or None,
                        "identified": bool(info.get("order_number")) and bool(info.get("customer_name")),
                        "source_file": name, "page_index": pg_idx,
                        "document_url": url, "images": [], "status": "AGUARDANDO IMAGEM",
                        "notes": "", "created_at": now_iso(), "user_id": user["id"]}
                    await db.shopee_orders.insert_one(doc); doc.pop("_id", None); imported.append(doc)
            elif ext in ("png","jpg","jpeg","webp"):
                url = save_file_bytes(data, ext)
                doc = {"id": new_id(), "order_number": f"IMG-{new_id()[:8].upper()}",
                    "customer_name": None, "identified": False,
                    "source_file": name, "document_url": url, "images": [], "status": "AGUARDANDO IMAGEM",
                    "notes": "", "created_at": now_iso(), "user_id": user["id"], "is_image": True}
                await db.shopee_orders.insert_one(doc); doc.pop("_id", None); imported.append(doc)
            else:
                skipped.append({"file": name, "reason": f"formato .{ext} não suportado"})
    except HTTPException: raise
    except Exception as e: raise HTTPException(400, f"Erro processando ZIP: {e}")
    return {"imported": len(imported), "orders": imported, "skipped": skipped, "duplicates": duplicates}

@api.get("/shopee/orders")
async def shopee_list(status: Optional[str] = None, q: Optional[str] = None,
                      start: Optional[str] = None, end: Optional[str] = None, user=Depends(get_user)):
    query = {}
    if status: query["status"] = status
    if start or end:
        rng = {}
        if start: rng["$gte"] = start
        if end: rng["$lte"] = end + "T23:59:59"
        query["created_at"] = rng
    if q:
        query["$or"] = [{"order_number": {"$regex": q, "$options": "i"}},
                        {"customer_name": {"$regex": q, "$options": "i"}}]
    return await db.shopee_orders.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)

@api.get("/shopee/orders/{oid}")
async def shopee_get(oid: str, user=Depends(get_user)):
    d = await db.shopee_orders.find_one({"id": oid}, {"_id": 0})
    if not d: raise HTTPException(404)
    return d

class ShopeeUpd(BaseModel):
    customer_name: Optional[str] = None; order_number: Optional[str] = None
    status: Optional[str] = None; notes: Optional[str] = None
    images: Optional[List[str]] = None

@api.put("/shopee/orders/{oid}")
async def shopee_upd(oid: str, body: ShopeeUpd, user=Depends(get_user)):
    upd = {k: v for k, v in body.model_dump().items() if v is not None}
    await db.shopee_orders.update_one({"id": oid}, {"$set": upd})
    return await db.shopee_orders.find_one({"id": oid}, {"_id": 0})

@api.post("/shopee/orders/{oid}/images")
async def shopee_add_img(oid: str, payload: Dict[str, Any], user=Depends(get_user)):
    url = payload.get("url")
    if not url: raise HTTPException(400)
    await db.shopee_orders.update_one({"id": oid}, {"$push": {"images": url}})
    return {"ok": True}

@api.delete("/shopee/orders/{oid}")
async def shopee_del(oid: str, user=Depends(require_admin)):
    await db.shopee_orders.delete_one({"id": oid}); return {"ok": True}

def _build_ficha_pdf(order: dict) -> bytes:
    """Build separation sheet PDF."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=10*mm, rightMargin=10*mm, topMargin=10*mm, bottomMargin=10*mm)
    styles = getSampleStyleSheet(); story = []
    logo_path = ROOT_DIR.parent / "frontend" / "public" / "riosul-logo.png"
    if logo_path.exists():
        story.append(RLImage(str(logo_path), width=50*mm, height=25*mm))
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph("<b>PEDIDO SHOPEE</b>", styles["Title"]))
    story.append(Spacer(1, 2*mm))
    order_no = order.get("order_number","-"); cust = order.get("customer_name") or "NÃO IDENTIFICADO"
    story.append(Paragraph(f"<font size=22><b>Nº {order_no}</b></font>", styles["Normal"]))
    story.append(Spacer(1, 2*mm))
    story.append(Paragraph(f"<font size=18>Cliente: <b>{cust}</b></font>", styles["Normal"]))
    story.append(Spacer(1, 4*mm))
    imgs = order.get("images", [])
    if imgs:
        for u in imgs[:2]:
            fn = u.split("/")[-1]; p = UPLOADS_DIR / fn
            if p.exists():
                try:
                    story.append(RLImage(str(p), width=170*mm, height=170*mm, kind="proportional"))
                    story.append(Spacer(1, 3*mm))
                except Exception: pass
    else:
        story.append(Paragraph("<font size=14 color='#EC4899'><b>⚠ AGUARDANDO IMAGEM DO PRODUTO</b></font>", styles["Normal"]))
    if order.get("notes"):
        story.append(Spacer(1, 3*mm))
        story.append(Paragraph(f"<b>Observações:</b> {order.get('notes','')}", styles["Normal"]))
    doc.build(story); return buf.getvalue()

@api.get("/shopee/orders/{oid}/ficha")
async def shopee_ficha(oid: str, user=Depends(get_user)):
    o = await db.shopee_orders.find_one({"id": oid}, {"_id": 0})
    if not o: raise HTTPException(404)
    data = _build_ficha_pdf(o)
    return StreamingResponse(io.BytesIO(data), media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=ficha_{o.get('order_number')}.pdf"})

@api.post("/shopee/batch-pdf")
async def shopee_batch(payload: Dict[str, Any], user=Depends(get_user)):
    """mode: 'documents' | 'fichas' | 'both'. ids: list of order ids or 'all'."""
    ids = payload.get("ids", []); mode = payload.get("mode", "both")
    if ids == "all":
        docs = await db.shopee_orders.find({}, {"_id": 0}).sort("customer_name", 1).to_list(1000)
    else:
        docs = await db.shopee_orders.find({"id": {"$in": ids}}, {"_id": 0}).to_list(1000)
    docs.sort(key=lambda x: (x.get("customer_name") or "ZZZ", x.get("order_number") or ""))
    writer = PdfWriter()
    for o in docs:
        if mode in ("documents", "both") and o.get("document_url"):
            fn = o["document_url"].split("/")[-1]; p = UPLOADS_DIR / fn
            if p.exists() and fn.endswith(".pdf"):
                try:
                    for pg in PdfReader(str(p)).pages: writer.add_page(pg)
                except Exception: pass
        if mode in ("fichas", "both"):
            ficha_bytes = _build_ficha_pdf(o)
            for pg in PdfReader(io.BytesIO(ficha_bytes)).pages: writer.add_page(pg)
    out = io.BytesIO(); writer.write(out); out.seek(0)
    return StreamingResponse(out, media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=pedidos_shopee.pdf"})

app.include_router(api)

@app.on_event("shutdown")
async def _shutdown(): client.close()
