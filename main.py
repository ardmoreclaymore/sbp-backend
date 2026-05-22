import os
from fastapi import FastAPI
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


@app.get("/")
def home():
    return {
        "status": "online",
        "project": "SBP SkyBlock Price Predictor",
        "version": "ah-bz-context-v1"
    }


@app.get("/api/context")
def context():
    result = (
        supabase.table("market_context")
        .select("*")
        .order("updated_at", desc=True)
        .execute()
    )

    rows = result.data or []
    return {row["key"]: row for row in rows}


@app.get("/api/top5")
def top5():
    result = (
        supabase.table("predictions")
        .select("*")
        .order("forecast_change_pct", desc=True)
        .limit(5)
        .execute()
    )
    return result.data


@app.get("/api/top20")
def top20():
    result = (
        supabase.table("predictions")
        .select("*")
        .order("forecast_change_pct", desc=True)
        .limit(20)
        .execute()
    )
    return result.data


@app.get("/api/items")
def all_items():
    """
    Returns all collected items above the collector's MINIMUM_PRICE.
    This now includes Bazaar items and Auction House LBIN items.
    """
    result = (
        supabase.table("items")
        .select("id,name,current_price,source,updated_at")
        .order("current_price", desc=True)
        .limit(10000)
        .execute()
    )
    return result.data


@app.get("/api/item/{item_id}")
def item(item_id: str):
    prediction = (
        supabase.table("predictions")
        .select("*")
        .eq("item_id", item_id)
        .limit(1)
        .execute()
    )

    # One month at 5-minute collection intervals:
    # 12 snapshots/hour * 24 hours/day * 30 days = 8640 snapshots.
    history = (
        supabase.table("price_snapshots")
        .select("price,created_at")
        .eq("item_id", item_id)
        .order("created_at", desc=True)
        .limit(9000)
        .execute()
    )

    history_rows = history.data or []
    history_rows.reverse()

    return {
        "prediction": prediction.data[0] if prediction.data else None,
        "history": history_rows
    }


@app.get("/api/search")
def search(q: str = ""):
    result = (
        supabase.table("items")
        .select("id,name,current_price,source")
        .ilike("name", f"%{q}%")
        .limit(100)
        .execute()
    )
    return result.data
