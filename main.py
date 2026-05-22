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
        "version": "ah-bz-context-safe-v2"
    }


@app.get("/api/top5")
def top5():
    result = (
        supabase.table("predictions")
        .select("*")
        .order("forecast_change_pct", desc=True)
        .limit(5)
        .execute()
    )
    return result.data or []


@app.get("/api/top20")
def top20():
    result = (
        supabase.table("predictions")
        .select("*")
        .order("forecast_change_pct", desc=True)
        .limit(20)
        .execute()
    )
    return result.data or []


@app.get("/api/items")
def all_items():
    """
    Returns the full item pool currently stored in Supabase.

    Your collector is responsible for deciding which items are stored.
    Right now that should include:
    - Bazaar items over your minimum price filter
    - Auction House lowest BIN items over your minimum price filter
    """
    result = (
        supabase.table("items")
        .select("id,name,current_price,source,updated_at")
        .order("current_price", desc=True)
        .limit(5000)
        .execute()
    )
    return result.data or []


@app.get("/api/context")
def context():
    """
    Safe context endpoint for the website info board.

    This should never crash the website. If the market_context table is missing,
    empty, or has slightly different columns, this returns fallback text instead.
    """
    fallback = {
        "current_mayor": "Loading mayor data",
        "current_meta": "Work in progress — verified meta source pending",
        "ai_factor_1": "AI factor slot",
        "ai_factor_2": "Update/event slot",
        "updated_at": None
    }

    try:
        result = (
            supabase.table("market_context")
            .select("*")
            .limit(1)
            .execute()
        )

        if not result.data:
            return fallback

        row = result.data[0]

        return {
            "current_mayor": (
                row.get("current_mayor")
                or row.get("mayor")
                or row.get("mayor_name")
                or fallback["current_mayor"]
            ),
            "current_meta": (
                row.get("current_meta")
                or row.get("meta")
                or fallback["current_meta"]
            ),
            "ai_factor_1": (
                row.get("ai_factor_1")
                or row.get("factor_1")
                or fallback["ai_factor_1"]
            ),
            "ai_factor_2": (
                row.get("ai_factor_2")
                or row.get("factor_2")
                or fallback["ai_factor_2"]
            ),
            "updated_at": row.get("updated_at")
        }

    except Exception as e:
        # Return 200 with fallback so the frontend does not break.
        fallback["error"] = str(e)
        return fallback


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
    # 9000 gives a small buffer. If less data exists, Supabase returns what exists.
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
    if not q:
        return []

    result = (
        supabase.table("items")
        .select("id,name,current_price,source")
        .or_(f"id.ilike.%{q}%,name.ilike.%{q}%")
        .order("current_price", desc=True)
        .limit(50)
        .execute()
    )
    return result.data or []
