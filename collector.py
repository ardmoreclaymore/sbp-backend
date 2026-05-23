from datetime import datetime, timezone, timedelta
from statistics import median

from supabase import create_client

from config import SUPABASE_URL, SUPABASE_SERVICE_KEY, PROJECT_NAME, VERSION, MINIMUM_PRICE, AH_MAX_PAGES, SNAPSHOT_KEEP_DAYS
from sources import fetch_bazaar, fetch_auction_page, fetch_current_mayor_context, fetch_meta_context
from normalizers import safe_float, safe_int, bz_name, ah_item_id, category_guess, spread_pct, pct_change
from predictor import score_item
from factor_loader import load_prediction_factors, match_factors_to_item

print("COLLECTOR VERSION: AH_BZ_V7_FIXED")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY / SUPABASE_SERVICE_ROLE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def chunked(items, size=500):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def get_recent_history(item_id, limit=20):
    try:
        response = supabase.table("price_snapshots").select("price,current_price,buy_price,sell_price,created_at").eq("item_id", item_id).order("created_at", desc=True).limit(limit).execute()
        return response.data or []
    except Exception as exc:
        print(f"History unavailable for {item_id}: {exc}")
        return []


def upsert_rows(table, rows, conflict_key=None, batch_size=500):
    if not rows:
        return
    for batch in chunked(rows, batch_size):
        query = supabase.table(table)
        if conflict_key:
            query.upsert(batch, on_conflict=conflict_key).execute()
        else:
            query.insert(batch).execute()


def collect_bazaar_items():
    products = fetch_bazaar()
    updated_at = now_iso()
    items = []
    snapshots = []
    for product_id, product in products.items():
        quick = product.get("quick_status", {}) or {}
        sell_price = safe_float(quick.get("sellPrice"))
        buy_price = safe_float(quick.get("buyPrice"))
        current_price = sell_price or buy_price
        if current_price < MINIMUM_PRICE:
            continue
        name = bz_name(product_id)
        spread = spread_pct(buy_price, sell_price)
        buy_volume = safe_float(quick.get("buyVolume"))
        sell_volume = safe_float(quick.get("sellVolume"))
        buy_moving_week = safe_float(quick.get("buyMovingWeek"))
        sell_moving_week = safe_float(quick.get("sellMovingWeek"))
        volume_24h = buy_volume + sell_volume
        buy_orders = safe_float(quick.get("buyOrders"))
        sell_orders = safe_float(quick.get("sellOrders"))
        row = {
            "id": product_id,
            "name": name,
            "source": "bazaar",
            "market_type": "bazaar",
            "source_tag": "BZ",
            "category": category_guess(name),
            "current_price": current_price,
            "buy_price": buy_price,
            "sell_price": sell_price,
            "spread_pct": spread,
            "buy_volume": buy_volume,
            "sell_volume": sell_volume,
            "buy_moving_week": buy_moving_week,
            "sell_moving_week": sell_moving_week,
            "buy_orders": buy_orders,
            "sell_orders": sell_orders,
            "volume": volume_24h,
            "volume_24h": volume_24h,
            "listed_count": safe_int(sell_orders),
            "sold_count_24h": None,
            "price_change_5m_pct": None,
            "history_points": 0,
            "example_names": [],
            "tags": ["bazaar"],
            "updated_at": updated_at,
            "raw_data": quick,
        }
        items.append(row)
        snapshots.append({
            "item_id": product_id,
            "price": current_price,
            "current_price": current_price,
            "buy_price": buy_price,
            "sell_price": sell_price,
            "buy_volume": buy_volume,
            "sell_volume": sell_volume,
            "buy_moving_week": buy_moving_week,
            "sell_moving_week": sell_moving_week,
            "buy_orders": buy_orders,
            "sell_orders": sell_orders,
            "volume": volume_24h,
            "volume_24h": volume_24h,
            "listed_count": safe_int(sell_orders),
            "spread_pct": spread,
            "source": "bazaar",
            "market_type": "bazaar",
            "raw_data": quick,
            "created_at": updated_at,
        })
    return items, snapshots


def collect_auction_items():
    updated_at = now_iso()
    grouped = {}
    first = fetch_auction_page(0)
    total_pages = safe_int(first.get("totalPages"), 0)
    pages_to_fetch = total_pages
    if str(AH_MAX_PAGES).lower() != "all":
        pages_to_fetch = min(total_pages, safe_int(AH_MAX_PAGES, 5))
    print(f"Auction pages available: {total_pages}; fetching: {pages_to_fetch}")
    for page in range(pages_to_fetch):
        data = first if page == 0 else fetch_auction_page(page)
        for auction in data.get("auctions", []) or []:
            if not auction.get("bin"):
                continue
            name = str(auction.get("item_name") or "").strip()
            if not name:
                continue
            price = safe_float(auction.get("starting_bid"))
            if price < MINIMUM_PRICE:
                continue
            item_id = ah_item_id(name)
            g = grouped.setdefault(item_id, {"id": item_id, "name": name, "source": "auction", "market_type": "auction", "source_tag": "AH", "category": category_guess(name), "prices": [], "example_names": set(), "listed_count": 0, "raw_examples": []})
            g["prices"].append(price)
            g["listed_count"] += 1
            g["example_names"].add(name)
            if len(g["raw_examples"]) < 3:
                g["raw_examples"].append({"uuid": auction.get("uuid"), "starting_bid": price, "tier": auction.get("tier"), "category": auction.get("category"), "end": auction.get("end")})
    items = []
    snapshots = []
    for item_id, g in grouped.items():
        prices = sorted([p for p in g["prices"] if p > 0])
        if not prices:
            continue
        lowest = prices[0]
        second = prices[1] if len(prices) > 1 else None
        med = median(prices)
        avg = sum(prices) / len(prices)
        spread = pct_change(lowest, second) if second else 0.0
        row = {
            "id": item_id,
            "name": g["name"],
            "source": "auction",
            "market_type": "auction",
            "source_tag": "AH",
            "category": g["category"],
            "current_price": lowest,
            "fair_price": med,
            "median_price": med,
            "avg_price": avg,
            "second_lowest_price": second,
            "buy_price": None,
            "sell_price": lowest,
            "spread_pct": spread,
            "volume": len(prices),
            "volume_24h": len(prices),
            "listed_count": g["listed_count"],
            "sold_count_24h": None,
            "price_change_5m_pct": None,
            "history_points": 0,
            "example_names": sorted(list(g["example_names"]))[:8],
            "tags": ["auction", g["category"]],
            "updated_at": updated_at,
            "raw_data": {"examples": g["raw_examples"]},
        }
        items.append(row)
        snapshots.append({
            "item_id": item_id,
            "price": lowest,
            "current_price": lowest,
            "fair_price": med,
            "median_price": med,
            "avg_price": avg,
            "second_lowest_price": second,
            "buy_price": None,
            "sell_price": lowest,
            "volume": len(prices),
            "volume_24h": len(prices),
            "listed_count": g["listed_count"],
            "spread_pct": spread,
            "source": "auction",
            "market_type": "auction",
            "raw_data": {"examples": g["raw_examples"]},
            "created_at": updated_at,
        })
    return items, snapshots


def build_predictions(items):
    factors = load_prediction_factors(supabase)
    rows = []

    print(f"Fast prediction mode for {len(items)} items")

    for index, item in enumerate(items, start=1):
        matched = match_factors_to_item(item, factors)

        # FAST MODE:
        # Do not fetch Supabase history for every item.
        # 5k+ separate history reads makes the cron too slow and can fail.
        pred = score_item(item, history=[], matched_factors=matched)

        pred["updated_at"] = now_iso()
        rows.append(pred)

        if index % 500 == 0:
            print(f"Built {index}/{len(items)} predictions")

    print(f"Finished building {len(rows)} predictions")
    return rows


def update_market_context(bz_count, ah_count):
    mayor = fetch_current_mayor_context()
    meta = fetch_meta_context()
    source_status = [
        {"name": "Hypixel Bazaar", "ok": True},
        {"name": "Hypixel Auctions", "ok": True},
        {"name": "SkyBlock.Tools Election", "ok": mayor.get("ok"), "source": mayor.get("source")},
        {"name": "OutcroCalculator", "ok": meta.get("ok"), "source": meta.get("source")},
    ]
    context = {
        "id": 1,
        "project_name": PROJECT_NAME,
        "current_mayor": mayor.get("current_mayor"),
        "current_perks": mayor.get("current_perks", []),
        "election_candidates": mayor.get("election_candidates", []),
        "current_meta": meta.get("current_meta"),
        "meta_methods": meta.get("meta_methods", []),
        "tracked_items_total": bz_count + ah_count,
        "tracked_bazaar_items": bz_count,
        "tracked_auction_items": ah_count,
        "ai_factor_1": f"Tracking {bz_count + ah_count:,} total AH + BZ grouped items",
        "ai_factor_2": "Prediction engine uses supply, demand, spreads, manipulation risk, and factor-bank matches",
        "source_status": source_status,
        "updated_at": now_iso(),
    }
    supabase.table("market_context").upsert(context, on_conflict="id").execute()


def cleanup_old_snapshots():
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=SNAPSHOT_KEEP_DAYS)).isoformat()
        supabase.table("price_snapshots").delete().lt("created_at", cutoff).execute()
        print(f"Cleaned snapshots older than {SNAPSHOT_KEEP_DAYS} days")
    except Exception as exc:
        print(f"Snapshot cleanup skipped: {exc}")


def collect_all():
    print(f"SBP collector running: all Bazaar + active Auction House + context + predictions ({VERSION})")
    bz_items, bz_snapshots = collect_bazaar_items()
    print(f"Bazaar collected: {len(bz_items)} items")
    ah_items, ah_snapshots = collect_auction_items()
    print(f"Auction House collected: {len(ah_items)} grouped items")
    all_items = bz_items + ah_items
    all_snapshots = bz_snapshots + ah_snapshots
    print("Building predictions...")
    prediction_rows = build_predictions(all_items)
    print("Writing items...")
    upsert_rows("items", all_items, conflict_key="id", batch_size=500)
    print("Writing snapshots...")
    upsert_rows("price_snapshots", all_snapshots, conflict_key=None, batch_size=500)
    print("Writing predictions...")
    upsert_rows("predictions", prediction_rows, conflict_key="item_id", batch_size=500)
    update_market_context(len(bz_items), len(ah_items))
    cleanup_old_snapshots()
    print(f"Saved {len(all_items)} items ({len(bz_items)} BZ + {len(ah_items)} AH), {len(all_snapshots)} snapshots, {len(prediction_rows)} predictions.")


if __name__ == "__main__":
    collect_all()
