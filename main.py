import os
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def safe_execute(query, fallback):
    try:
        result = query.execute()
        return result.data or fallback
    except Exception as exc:
        print("Supabase query failed:", exc)
        return fallback


def fetch_all_items(limit=10000):
    rows = []
    page = 1000
    start = 0

    while len(rows) < limit:
        end = min(start + page - 1, limit - 1)
        result = safe_execute(
            supabase.table("items")
            .select("id,name,current_price,source,updated_at")
            .order("current_price", desc=True)
            .range(start, end),
            []
        )
        rows.extend(result)
        if len(result) < page:
            break
        start += page

    return rows


@app.get("/")
def home():
    return {
        "status": "online",
        "project": "SBP SkyBlock Price Predictor",
        "version": "screenshot-ui-mayor-minister-v1"
    }


@app.get("/api/items")
def all_items(limit: int = Query(10000, ge=1, le=50000)):
    return fetch_all_items(limit=limit)


@app.get("/api/market-summary")
def market_summary():
    items = fetch_all_items(limit=50000)

    total = len(items)
    bazaar = sum(1 for x in items if x.get("source") == "bazaar")
    auction = sum(1 for x in items if x.get("source") == "auction")

    newest = None
    for row in items:
        updated = row.get("updated_at")
        if updated and (newest is None or updated > newest):
            newest = updated

    return {
        "tracked_items": total,
        "bazaar_items": bazaar,
        "auction_items": auction,
        "last_updated": newest
    }


@app.get("/api/context")
def context():
    fallback = {
        "current_mayor": "Loading mayor data",
        "current_mayor_perks": "No mayor perks parsed yet.",
        "current_minister": "Minister unavailable",
        "current_minister_perk": "Minister perk unavailable",
        "current_minister_perk_description": "",
        "current_meta": "Market context feed",
        "ai_factor_1": "Work in progress",
        "ai_factor_2": "Work in progress",
        "updated_at": None
    }

    data = safe_execute(
        supabase.table("market_context").select("*").eq("id", 1).limit(1),
        []
    )

    if not data:
        return fallback

    row = data[0]
    return {
        "current_mayor": row.get("current_mayor") or fallback["current_mayor"],
        "current_mayor_perks": row.get("current_mayor_perks") or fallback["current_mayor_perks"],
        "current_minister": row.get("current_minister") or fallback["current_minister"],
        "current_minister_perk": row.get("current_minister_perk") or fallback["current_minister_perk"],
        "current_minister_perk_description": row.get("current_minister_perk_description") or fallback["current_minister_perk_description"],
        "current_meta": row.get("current_meta") or fallback["current_meta"],
        "ai_factor_1": row.get("ai_factor_1") or fallback["ai_factor_1"],
        "ai_factor_2": row.get("ai_factor_2") or fallback["ai_factor_2"],
        "updated_at": row.get("updated_at")
    }


@app.get("/api/top20")
def top20():
    return safe_execute(
        supabase.table("predictions")
        .select("*")
        .order("forecast_change_pct", desc=True)
        .limit(20),
        []
    )


@app.get("/api/top5")
def top5():
    return safe_execute(
        supabase.table("predictions")
        .select("*")
        .order("forecast_change_pct", desc=True)
        .limit(5),
        []
    )


@app.get("/api/item/{item_id}")
def item(item_id: str):
    prediction = safe_execute(
        supabase.table("predictions")
        .select("*")
        .eq("item_id", item_id)
        .limit(1),
        []
    )

    history = safe_execute(
        supabase.table("price_snapshots")
        .select("price,created_at")
        .eq("item_id", item_id)
        .order("created_at", desc=True)
        .limit(9000),
        []
    )

    history.reverse()

    return {
        "prediction": prediction[0] if prediction else None,
        "history": history
    }


@app.get("/api/search")
def search(
    q: str = "",
    source: str = "all",
    limit: int = Query(20, ge=1, le=200)
):
    q = q.strip()

    query = supabase.table("items").select("id,name,current_price,source,updated_at")

    if source in ("bazaar", "auction"):
        query = query.eq("source", source)

    if q:
        query = query.or_(f"id.ilike.%{q}%,name.ilike.%{q}%")

    return safe_execute(
        query.order("current_price", desc=True).limit(limit),
        []
    )
