from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client

from config import SUPABASE_URL, SUPABASE_SERVICE_KEY, PROJECT_NAME, VERSION, SEARCH_LIMIT, TOP_LIMIT, ITEM_HISTORY_LIMIT

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY / SUPABASE_SERVICE_ROLE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
app = FastAPI(title=PROJECT_NAME, version=VERSION)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])


@app.get("/")
def root():
    return {"status": "online", "project": PROJECT_NAME, "version": VERSION, "message": "API online. Use /api/context, /api/top20, /api/items, /api/search, /api/item/{item_id}."}


@app.get("/api/context")
def api_context():
    try:
        response = supabase.table("market_context").select("*").eq("id", 1).limit(1).execute()
        rows = response.data or []
        if rows:
            return rows[0]
        return {"project_name": PROJECT_NAME, "current_mayor": "Loading mayor data", "current_perks": [], "election_candidates": [], "current_meta": "Loading market context", "meta_methods": [], "tracked_items_total": 0, "tracked_bazaar_items": 0, "tracked_auction_items": 0, "ai_factor_1": "Loading tracked items", "ai_factor_2": "Prediction engine loading", "source_status": [], "updated_at": None}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/stats")
def api_stats():
    return api_context()



def _dedupe_key(row):
    name = str(row.get("name") or row.get("item_name") or "").strip().lower()
    source = str(row.get("source") or row.get("market_type") or "").strip().lower()
    return f"{source}|{name}"


def _parse_time(value):
    from datetime import datetime, timezone
    if not value:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return datetime.fromtimestamp(0, tz=timezone.utc)


def _better_duplicate(candidate, current):
    """
    Pick the live/current duplicate.

    Duplicate AH rows happened because older collector versions generated different
    item IDs for the same item name. Keep the newest row first. If timestamps tie,
    keep the cheaper AH row because AH represents lowest BIN.
    """
    if current is None:
        return candidate

    candidate_time = _parse_time(candidate.get("updated_at"))
    current_time = _parse_time(current.get("updated_at"))

    if candidate_time > current_time:
        return candidate
    if candidate_time < current_time:
        return current

    source = str(candidate.get("source") or current.get("source") or "").lower()
    if source == "auction":
        cand_price = float(candidate.get("current_price") or 0)
        curr_price = float(current.get("current_price") or 0)
        if cand_price > 0 and (curr_price <= 0 or cand_price < curr_price):
            return candidate

    cand_score = float(candidate.get("rank_score") or candidate.get("forecast_change_pct") or 0)
    curr_score = float(current.get("rank_score") or current.get("forecast_change_pct") or 0)
    return candidate if cand_score > curr_score else current


def _dedupe_rows(rows):
    deduped = {}
    for row in rows or []:
        key = _dedupe_key(row)
        if not key.strip("|"):
            key = str(row.get("item_id") or row.get("id") or len(deduped))
        deduped[key] = _better_duplicate(row, deduped.get(key))
    return list(deduped.values())

@app.get("/api/top20")
def api_top20(limit: int = Query(TOP_LIMIT, ge=1, le=100), hide_manipulated: bool = False):
    """
    Safe + deduped Top 20 endpoint.

    Duplicate rows can exist from old AH ID formats. This returns one row per
    source/name pair and falls back cleanly if schema columns differ.
    """
    try:
        raw_limit = min(max(limit * 8, 80), 800)

        try:
            response = (
                supabase.table("predictions")
                .select("*")
                .order("rank_score", desc=True)
                .limit(raw_limit)
                .execute()
            )
            rows = response.data or []
        except Exception as rank_exc:
            print(f"/api/top20 rank_score order failed, falling back to forecast_change_pct: {rank_exc}")
            try:
                response = (
                    supabase.table("predictions")
                    .select("*")
                    .order("forecast_change_pct", desc=True)
                    .limit(raw_limit)
                    .execute()
                )
                rows = response.data or []
            except Exception as forecast_exc:
                print(f"/api/top20 forecast order failed, falling back to plain select: {forecast_exc}")
                response = (
                    supabase.table("predictions")
                    .select("*")
                    .limit(raw_limit)
                    .execute()
                )
                rows = response.data or []

        if hide_manipulated:
            rows = [
                row for row in rows
                if float(row.get("manipulation_score") or 0) < 50
            ]

        rows = _dedupe_rows(rows)

        if not rows:
            item_response = (
                supabase.table("items")
                .select("*")
                .order("current_price", desc=True)
                .limit(raw_limit)
                .execute()
            )

            fallback_rows = []
            for item in _dedupe_rows(item_response.data or []):
                fallback_rows.append({
                    "item_id": item.get("id"),
                    "name": item.get("name"),
                    "source": item.get("source"),
                    "current_price": item.get("current_price"),
                    "forecast_change_pct": 0,
                    "rank_score": 0,
                    "predicted_direction": "STABLE",
                    "confidence": 0,
                    "certainty": 0,
                    "manipulation_score": 0,
                    "reason": "Waiting for prediction data",
                    "risk": "No prediction row yet",
                    "market_type": item.get("market_type"),
                    "category": item.get("category"),
                    "updated_at": item.get("updated_at"),
                })
            rows = fallback_rows

        rows.sort(key=lambda row: float(row.get("rank_score") or row.get("forecast_change_pct") or 0), reverse=True)
        return rows[:limit]

    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

@app.get("/api/items")
def api_items(limit: int = Query(SEARCH_LIMIT, ge=1, le=200)):
    try:
        response = supabase.table("items").select("*").order("current_price", desc=True).limit(limit).execute()
        return response.data or []
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/search")
def api_search(q: str = Query("", min_length=0), source: str = Query("", min_length=0), limit: int = Query(SEARCH_LIMIT, ge=1, le=100)):
    try:
        # Pull extra rows before dedupe because old collector IDs may create duplicates.
        raw_limit = min(max(limit * 8, 80), 800)

        query = supabase.table("items").select("*")
        if q:
            query = query.ilike("name", f"%{q}%")
        if source:
            source_l = source.lower()
            if source_l in ["auction", "ah"]:
                query = query.eq("source", "auction")
            elif source_l in ["bazaar", "bz"]:
                query = query.eq("source", "bazaar")

        response = query.order("updated_at", desc=True).limit(raw_limit).execute()
        rows = _dedupe_rows(response.data or [])

        # For display: expensive first, but without duplicate names.
        rows.sort(key=lambda row: float(row.get("current_price") or 0), reverse=True)
        return rows[:limit]

    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

@app.get("/api/item/{item_id}")
def api_item(item_id: str):
    try:
        item_resp = supabase.table("items").select("*").eq("id", item_id).limit(1).execute()
        item_rows = item_resp.data or []
        if not item_rows:
            raise HTTPException(status_code=404, detail="Item not found")
        pred_resp = supabase.table("predictions").select("*").eq("item_id", item_id).limit(1).execute()
        hist_resp = supabase.table("price_snapshots").select("*").eq("item_id", item_id).order("created_at", desc=False).limit(ITEM_HISTORY_LIMIT).execute()
        pred_rows = pred_resp.data or []
        return {"item": item_rows[0], "prediction": pred_rows[0] if pred_rows else {}, "history": hist_resp.data or []}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
