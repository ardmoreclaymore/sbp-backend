from __future__ import annotations

import json
import os
from typing import Any

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client

from config import PROJECT_NAME, SUPABASE_SERVICE_KEY, SUPABASE_URL

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

app = FastAPI(title=PROJECT_NAME, version="ai-training-ah-bz-v6")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def parse_json_field(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return fallback


def hydrate_prediction(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    row = dict(row)
    row["top_outcomes"] = parse_json_field(row.get("top_outcomes"), [])
    row["manipulation_flags"] = parse_json_field(row.get("manipulation_flags"), [])
    row["tags"] = parse_json_field(row.get("tags"), [])
    return row


@app.get("/")
def home():
    return {
        "status": "online",
        "project": PROJECT_NAME,
        "version": "ai-training-ah-bz-v6",
        "message": "API online. Use /api/stats, /api/top20, /api/items, /api/search, /api/item/{item_id}.",
    }


@app.get("/api/stats")
def stats():
    context = context_endpoint()
    return {
        "tracked_items_total": context.get("tracked_items_total", 0),
        "tracked_bazaar_items": context.get("tracked_bazaar_items", 0),
        "tracked_auction_items": context.get("tracked_auction_items", 0),
        "last_updated": context.get("updated_at"),
        "current_mayor": context.get("current_mayor"),
        "current_meta": context.get("current_meta"),
    }


@app.get("/api/context")
def context_endpoint():
    fallback = {
        "project_name": PROJECT_NAME,
        "current_mayor": "Loading mayor data",
        "current_perks": [],
        "election_candidates": [],
        "current_meta": "Loading AI training context",
        "meta_methods": [],
        "tracked_items_total": 0,
        "tracked_bazaar_items": 0,
        "tracked_auction_items": 0,
        "ai_factor_1": "Loading tracked items",
        "ai_factor_2": "AI training loading",
        "source_status": [],
        "updated_at": None,
    }
    try:
        result = supabase.table("market_context").select("*").eq("id", 1).limit(1).execute()
        if not result.data:
            return fallback
        row = dict(result.data[0])
        for field in ["current_perks", "election_candidates", "meta_methods", "source_status"]:
            row[field] = parse_json_field(row.get(field), [])
        for key, value in fallback.items():
            row.setdefault(key, value)
            if row[key] is None:
                row[key] = value
        return row
    except Exception as exc:
        fallback["error"] = str(exc)
        return fallback


@app.get("/api/top20")
def top20(
    source: str | None = Query(None, description="bazaar, auction, BZ, AH, or blank for all"),
    min_confidence: float = 0,
    hide_manipulated: bool = False,
):
    query = supabase.table("predictions").select("*")
    if source:
        normal = source.lower()
        if normal in {"bz", "bazaar"}:
            query = query.eq("source", "bazaar")
        elif normal in {"ah", "auction"}:
            query = query.eq("source", "auction")
    if min_confidence:
        query = query.gte("confidence", min_confidence)
    if hide_manipulated:
        query = query.lt("manipulation_score", 45)
    result = query.order("rank_score", desc=True).limit(20).execute()
    return [hydrate_prediction(row) for row in (result.data or [])]


@app.get("/api/top5")
def top5():
    result = supabase.table("predictions").select("*").order("rank_score", desc=True).limit(5).execute()
    return [hydrate_prediction(row) for row in (result.data or [])]


@app.get("/api/items")
def all_items(
    source: str | None = None,
    limit: int = Query(50000, ge=1, le=75000),
    sort: str = Query("price", description="price, name, updated, prediction"),
):
    columns = "id,name,current_price,fair_price,source,market_type,category,listed_count,volume_24h,updated_at"
    query = supabase.table("items").select(columns)
    if source:
        normal = source.lower()
        if normal in {"bz", "bazaar"}:
            query = query.eq("source", "bazaar")
        elif normal in {"ah", "auction"}:
            query = query.eq("source", "auction")
    if sort == "name":
        query = query.order("name")
    elif sort == "updated":
        query = query.order("updated_at", desc=True)
    else:
        query = query.order("current_price", desc=True)
    result = query.limit(limit).execute()
    return result.data or []


@app.get("/api/search")
def search(q: str = "", source: str | None = None):
    if not q.strip():
        return []
    columns = "id,name,current_price,fair_price,source,market_type,category,listed_count,volume_24h,updated_at"
    query = supabase.table("items").select(columns).or_(f"id.ilike.%{q}%,name.ilike.%{q}%,source_tag.ilike.%{q}%")
    if source:
        normal = source.lower()
        if normal in {"bz", "bazaar"}:
            query = query.eq("source", "bazaar")
        elif normal in {"ah", "auction"}:
            query = query.eq("source", "auction")
    result = query.order("current_price", desc=True).limit(100).execute()
    return result.data or []


@app.get("/api/item/{item_id}")
def item(item_id: str):
    item_result = supabase.table("items").select("*").eq("id", item_id).limit(1).execute()
    prediction_result = supabase.table("predictions").select("*").eq("item_id", item_id).limit(1).execute()
    history = (
        supabase.table("price_snapshots")
        .select("price,buy_price,sell_price,volume,listed_count,spread_pct,manipulation_score,source,created_at")
        .eq("item_id", item_id)
        .order("created_at", desc=True)
        .limit(9000)
        .execute()
    )
    history_rows = history.data or []
    history_rows.reverse()
    return {
        "item": item_result.data[0] if item_result.data else None,
        "prediction": hydrate_prediction(prediction_result.data[0] if prediction_result.data else None),
        "history": history_rows,
    }


@app.get("/api/source-status")
def source_status():
    try:
        result = supabase.table("source_status").select("*").order("updated_at", desc=True).limit(50).execute()
        return result.data or []
    except Exception as exc:
        return [{"status": "error", "message": str(exc)}]
