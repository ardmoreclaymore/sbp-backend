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


@app.get("/api/top20")
def api_top20(limit: int = Query(TOP_LIMIT, ge=1, le=100), hide_manipulated: bool = False):
    try:
        query = supabase.table("predictions").select("*")
        if hide_manipulated:
            query = query.lt("manipulation_score", 50)
        response = query.order("rank_score", desc=True).limit(limit).execute()
        return response.data or []
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
        query = supabase.table("items").select("*")
        if q:
            query = query.ilike("name", f"%{q}%")
        if source:
            source_l = source.lower()
            if source_l in ["auction", "ah"]:
                query = query.eq("source", "auction")
            elif source_l in ["bazaar", "bz"]:
                query = query.eq("source", "bazaar")
        response = query.order("current_price", desc=True).limit(limit).execute()
        return response.data or []
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
