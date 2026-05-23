from __future__ import annotations

import json
import time
from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean
from typing import Any

from supabase import create_client

from config import (
    AH_MAX_PAGES,
    COFLNET_ENRICH_TOP_N,
    MINIMUM_PRICE,
    PROJECT_NAME,
    SLEEP_BETWEEN_AH_PAGES,
    SUPABASE_SERVICE_KEY,
    SUPABASE_URL,
    UPSERT_CHUNK_SIZE,
)
from normalizers import (
    clean_text,
    infer_item_tags,
    infer_market_bucket,
    nice_bazaar_name,
    normalise_ah_name,
    parse_rarity_from_lore,
    pct_change,
    robust_median,
    safe_float,
    safe_int,
    stable_ah_id,
)
from predictor import MarketSignals, predict_item
from sources import (
    fetch_coflnet_item_analysis,
    fetch_coflnet_sold,
    fetch_current_mayor_context,
    fetch_hypixel_auction_pages,
    fetch_hypixel_bazaar,
    fetch_outcro_meta_methods,
    source_status_row,
)

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def chunked(rows: list[dict[str, Any]], size: int = UPSERT_CHUNK_SIZE):
    for i in range(0, len(rows), size):
        yield rows[i:i + size]


def upsert_rows(table: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    for chunk in chunked(rows):
        supabase.table(table).upsert(chunk).execute()


def insert_rows(table: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    for chunk in chunked(rows):
        supabase.table(table).insert(chunk).execute()


def fetch_previous_items() -> dict[str, dict[str, Any]]:
    """Fetch prior item state for momentum. Keeps the collector one API query per page, not one per item."""
    previous: dict[str, dict[str, Any]] = {}
    page_size = 1000
    start = 0
    columns = "id,current_price,updated_at,history_points,source,listed_count,volume_24h"
    while True:
        result = supabase.table("items").select(columns).range(start, start + page_size - 1).execute()
        data = result.data or []
        for row in data:
            previous[str(row.get("id"))] = row
        if len(data) < page_size:
            break
        start += page_size
    return previous


def make_context() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    status_rows: list[dict[str, Any]] = []
    mayor_context, mayor_status = fetch_current_mayor_context()
    meta_methods, meta_status = fetch_outcro_meta_methods(limit=40)
    status_rows.append(source_status_row(mayor_status))
    status_rows.append(source_status_row(meta_status))

    meta_names = [m.get("name", "") for m in meta_methods if m.get("name")]
    current_meta = "; ".join(meta_names[:8]) if meta_names else "No verified public meta feed parsed"
    context = {
        "current_mayor": mayor_context.get("current_mayor", "Unknown"),
        "current_perks": mayor_context.get("current_perks", []),
        "election_candidates": mayor_context.get("candidates", []),
        "current_meta": current_meta,
        "meta_methods": meta_names,
        "source_status": status_rows,
    }
    return context, status_rows


def collect_bazaar(previous: dict[str, dict[str, Any]], context: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    payload = fetch_hypixel_bazaar()
    now = utc_now()
    item_rows: list[dict[str, Any]] = []
    snapshot_rows: list[dict[str, Any]] = []
    prediction_rows: list[dict[str, Any]] = []

    for product_id, product in (payload.get("products") or {}).items():
        quick = product.get("quick_status") or {}
        buy_price = safe_float(quick.get("buyPrice"))
        sell_price = safe_float(quick.get("sellPrice"))
        # Bazaar buyPrice is instant-sell to buy orders; sellPrice is instant-buy from sell offers.
        # Current market midpoint is more stable than either side alone.
        current_price = 0.0
        if buy_price > 0 and sell_price > 0:
            current_price = (buy_price + sell_price) / 2.0
        else:
            current_price = buy_price or sell_price
        if current_price < MINIMUM_PRICE:
            continue

        name = nice_bazaar_name(product_id)
        prev_row = previous.get(product_id, {})
        prev_price = safe_float(prev_row.get("current_price"))
        history_points = safe_int(prev_row.get("history_points")) + 1
        tags = infer_item_tags(name, "bazaar")
        spread_pct = abs(buy_price - sell_price) / max(current_price, 1.0) * 100.0 if buy_price and sell_price else 0.0
        volume_24h = safe_float(quick.get("buyVolume")) + safe_float(quick.get("sellVolume"))

        item_row = {
            "id": product_id,
            "name": name,
            "source": "bazaar",
            "market_type": "BZ",
            "source_tag": product_id,
            "category": infer_market_bucket(name, "bazaar"),
            "tags": json.dumps(tags),
            "current_price": round(current_price, 4),
            "fair_price": round(current_price, 4),
            "buy_price": round(buy_price, 4),
            "sell_price": round(sell_price, 4),
            "spread_pct": round(spread_pct, 4),
            "buy_volume": safe_float(quick.get("buyVolume")),
            "sell_volume": safe_float(quick.get("sellVolume")),
            "buy_moving_week": safe_float(quick.get("buyMovingWeek")),
            "sell_moving_week": safe_float(quick.get("sellMovingWeek")),
            "buy_orders": safe_int(quick.get("buyOrders")),
            "sell_orders": safe_int(quick.get("sellOrders")),
            "volume_24h": round(volume_24h, 4),
            "listed_count": safe_int(quick.get("sellOrders")),
            "sold_count_24h": 0,
            "price_change_5m_pct": round(pct_change(prev_price, current_price), 4),
            "history_points": history_points,
            "updated_at": now,
        }

        signals = MarketSignals(
            source="bazaar",
            current_price=current_price,
            previous_price=prev_price,
            buy_price=buy_price,
            sell_price=sell_price,
            buy_volume=safe_float(quick.get("buyVolume")),
            sell_volume=safe_float(quick.get("sellVolume")),
            buy_moving_week=safe_float(quick.get("buyMovingWeek")),
            sell_moving_week=safe_float(quick.get("sellMovingWeek")),
            buy_orders=safe_float(quick.get("buyOrders")),
            sell_orders=safe_float(quick.get("sellOrders")),
            listed_count=safe_int(quick.get("sellOrders")),
            history_points=history_points,
            current_mayor=context.get("current_mayor", "Unknown"),
            current_perks=context.get("current_perks", []),
            current_metas=context.get("meta_methods", []),
        )
        prediction = predict_item(product_id, name, signals)

        snapshot_rows.append({
            "item_id": product_id,
            "price": round(current_price, 4),
            "buy_price": round(buy_price, 4),
            "sell_price": round(sell_price, 4),
            "volume": round(volume_24h, 4),
            "listed_count": safe_int(quick.get("sellOrders")),
            "spread_pct": round(spread_pct, 4),
            "manipulation_score": prediction["manipulation_score"],
            "source": "bazaar",
            "created_at": now,
        })
        item_rows.append(item_row)
        prediction_rows.append(prediction)

    return item_rows, snapshot_rows, prediction_rows


def guess_coflnet_tag(item_name: str) -> str:
    cleaned = normalise_ah_name(item_name).upper()
    cleaned = cleaned.replace("'", "").replace("-", " ")
    cleaned = "_".join(part for part in cleaned.split() if part)
    return cleaned[:96]


def group_auctions(auctions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for auction in auctions:
        raw_name = auction.get("item_name") or auction.get("itemName") or "Unknown Item"
        name = normalise_ah_name(raw_name)
        if not name or name == "Unknown Item":
            continue
        price = safe_float(auction.get("starting_bid") or auction.get("startingBid") or auction.get("highestBidAmount"))
        if price <= 0 or price < MINIMUM_PRICE:
            continue
        item_id = stable_ah_id(name)
        group = groups.setdefault(item_id, {
            "id": item_id,
            "name": name,
            "source_tag": guess_coflnet_tag(name),
            "prices": [],
            "bin_prices": [],
            "auction_prices": [],
            "listed_count": 0,
            "bin_count": 0,
            "category": clean_text(auction.get("category")) or "UNKNOWN",
            "tier": clean_text(auction.get("tier")) or parse_rarity_from_lore(auction.get("item_lore")),
            "example_names": set(),
        })
        group["prices"].append(price)
        group["listed_count"] += 1
        group["example_names"].add(clean_text(raw_name))
        if auction.get("bin"):
            group["bin_prices"].append(price)
            group["bin_count"] += 1
        else:
            group["auction_prices"].append(price)
    return groups


def enrich_with_coflnet(groups: dict[str, dict[str, Any]]) -> None:
    if COFLNET_ENRICH_TOP_N <= 0:
        return
    # Prioritize active, expensive, liquid items. Do not hammer Coflnet for every item.
    priority = sorted(
        groups.values(),
        key=lambda g: (safe_int(g.get("listed_count")) * max(1.0, robust_median(g.get("prices", [])))) ,
        reverse=True,
    )[:COFLNET_ENRICH_TOP_N]
    for group in priority:
        tag = group.get("source_tag") or ""
        analysis = fetch_coflnet_item_analysis(tag, days=7)
        if analysis:
            group["coflnet_analysis"] = analysis
            group["coflnet_sales_per_day"] = safe_float(analysis.get("salesPerDay") or analysis.get("sales_per_day"))
            group["coflnet_median"] = safe_float(analysis.get("median") or analysis.get("medianPrice") or analysis.get("median_price"))
            group["coflnet_avg"] = safe_float(analysis.get("average") or analysis.get("avg") or analysis.get("averagePrice"))
            group["coflnet_volatility"] = safe_float(analysis.get("priceCoeffVariation") or analysis.get("priceCoefficientVariation") or analysis.get("priceStdDev"))
        else:
            sold = fetch_coflnet_sold(tag)
            if sold:
                group["coflnet_sold"] = len(sold)
                sold_prices = [safe_float(s.get("highestBidAmount") or s.get("price") or s.get("startingBid")) for s in sold]
                group["coflnet_median"] = robust_median(sold_prices)
                group["coflnet_avg"] = mean([p for p in sold_prices if p > 0]) if any(p > 0 for p in sold_prices) else 0
                group["coflnet_sales_per_day"] = len(sold) / 7.0
        time.sleep(0.05)


def collect_auction_house(previous: dict[str, dict[str, Any]], context: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    auctions = fetch_hypixel_auction_pages(AH_MAX_PAGES, SLEEP_BETWEEN_AH_PAGES)
    groups = group_auctions(auctions)
    enrich_with_coflnet(groups)

    now = utc_now()
    item_rows: list[dict[str, Any]] = []
    snapshot_rows: list[dict[str, Any]] = []
    prediction_rows: list[dict[str, Any]] = []

    for item_id, group in groups.items():
        prices = sorted([safe_float(p) for p in group.get("prices", []) if safe_float(p) > 0])
        bin_prices = sorted([safe_float(p) for p in group.get("bin_prices", []) if safe_float(p) > 0])
        if not prices:
            continue
        current_price = bin_prices[0] if bin_prices else prices[0]
        second_lowest = (bin_prices[1] if len(bin_prices) > 1 else (prices[1] if len(prices) > 1 else 0.0))
        lower_sample = bin_prices[:10] or prices[:10]
        lower_quartile = robust_median(lower_sample[:max(1, len(lower_sample) // 2)])
        median_price = robust_median(bin_prices or prices)
        avg_price = mean(bin_prices or prices)

        prev_row = previous.get(item_id, {})
        prev_price = safe_float(prev_row.get("current_price"))
        history_points = safe_int(prev_row.get("history_points")) + 1
        listed_count = safe_int(group.get("listed_count"))
        sold_count_24h = safe_int(group.get("coflnet_sold"))
        fair_price = lower_quartile or median_price or current_price
        tags = infer_item_tags(group["name"], "auction")

        signals = MarketSignals(
            source="auction",
            current_price=current_price,
            previous_price=prev_price,
            listed_count=listed_count,
            sold_count_24h=sold_count_24h,
            median_price=median_price,
            avg_price=avg_price,
            second_lowest_price=second_lowest,
            lower_quartile_price=lower_quartile,
            coflnet_sales_per_day=safe_float(group.get("coflnet_sales_per_day")),
            coflnet_volatility=safe_float(group.get("coflnet_volatility")),
            coflnet_median=safe_float(group.get("coflnet_median")),
            coflnet_avg=safe_float(group.get("coflnet_avg")),
            history_points=history_points,
            current_mayor=context.get("current_mayor", "Unknown"),
            current_perks=context.get("current_perks", []),
            current_metas=context.get("meta_methods", []),
        )
        prediction = predict_item(item_id, group["name"], signals)

        item_row = {
            "id": item_id,
            "name": group["name"],
            "source": "auction",
            "market_type": "AH",
            "source_tag": group.get("source_tag"),
            "category": infer_market_bucket(group["name"], "auction"),
            "tier": group.get("tier") or "UNKNOWN",
            "tags": json.dumps(tags),
            "current_price": round(current_price, 2),
            "fair_price": round(fair_price, 2),
            "median_price": round(median_price, 2),
            "avg_price": round(avg_price, 2),
            "second_lowest_price": round(second_lowest, 2),
            "buy_price": 0,
            "sell_price": 0,
            "spread_pct": round(((second_lowest - current_price) / current_price) * 100.0, 4) if second_lowest and current_price else 0,
            "buy_volume": listed_count,
            "sell_volume": 0,
            "buy_moving_week": 0,
            "sell_moving_week": 0,
            "buy_orders": 0,
            "sell_orders": 0,
            "volume_24h": sold_count_24h or round(safe_float(group.get("coflnet_sales_per_day")), 2),
            "listed_count": listed_count,
            "sold_count_24h": sold_count_24h,
            "price_change_5m_pct": round(pct_change(prev_price, current_price), 4),
            "history_points": history_points,
            "example_names": json.dumps(sorted(list(group.get("example_names") or []))[:6]),
            "updated_at": now,
        }
        snapshot_rows.append({
            "item_id": item_id,
            "price": round(current_price, 2),
            "buy_price": 0,
            "sell_price": 0,
            "volume": sold_count_24h or listed_count,
            "listed_count": listed_count,
            "spread_pct": item_row["spread_pct"],
            "manipulation_score": prediction["manipulation_score"],
            "source": "auction",
            "created_at": now,
        })
        item_rows.append(item_row)
        prediction_rows.append(prediction)

    return item_rows, snapshot_rows, prediction_rows


def update_market_context(context: dict[str, Any], stats: dict[str, Any], status_rows: list[dict[str, Any]]) -> None:
    now = utc_now()
    row = {
        "id": 1,
        "project_name": PROJECT_NAME,
        "current_mayor": context.get("current_mayor") or "Unknown",
        "current_perks": json.dumps(context.get("current_perks", [])),
        "election_candidates": json.dumps(context.get("election_candidates", [])),
        "current_meta": context.get("current_meta") or "No current meta parsed",
        "meta_methods": json.dumps(context.get("meta_methods", [])),
        "tracked_items_total": stats.get("total_items", 0),
        "tracked_bazaar_items": stats.get("bazaar_items", 0),
        "tracked_auction_items": stats.get("auction_items", 0),
        "ai_factor_1": f"{stats.get('total_items', 0):,} items tracked",
        "ai_factor_2": "AI training: live source + event + manipulation scoring",
        "source_status": json.dumps(status_rows),
        "updated_at": now,
    }
    supabase.table("market_context").upsert(row).execute()
    upsert_rows("source_status", status_rows)


def collect_all() -> None:
    start = time.time()
    print("SBP collector running: all Bazaar + active Auction House + context + AI training predictions")
    previous = fetch_previous_items()
    context, status_rows = make_context()

    bz_items, bz_snapshots, bz_predictions = collect_bazaar(previous, context)
    print(f"Bazaar collected: {len(bz_items)} items")
    ah_items, ah_snapshots, ah_predictions = collect_auction_house(previous, context)
    print(f"Auction House collected: {len(ah_items)} grouped items")

    item_rows = bz_items + ah_items
    snapshot_rows = bz_snapshots + ah_snapshots
    prediction_rows = bz_predictions + ah_predictions

    print(f"Upserting {len(item_rows)} items...")
    upsert_rows("items", item_rows)
    print(f"Inserting {len(snapshot_rows)} snapshots...")
    insert_rows("price_snapshots", snapshot_rows)
    print(f"Upserting {len(prediction_rows)} predictions...")
    upsert_rows("predictions", prediction_rows)

    stats = {
        "bazaar_items": len(bz_items),
        "auction_items": len(ah_items),
        "total_items": len(item_rows),
        "snapshots": len(snapshot_rows),
        "predictions": len(prediction_rows),
        "minimum_price": MINIMUM_PRICE,
        "ah_max_pages": AH_MAX_PAGES,
        "seconds": round(time.time() - start, 2),
    }
    update_market_context(context, stats, status_rows)
    print(
        f"Saved {stats['total_items']:,} items "
        f"({stats['bazaar_items']:,} BZ + {stats['auction_items']:,} AH), "
        f"{stats['snapshots']:,} snapshots, {stats['predictions']:,} predictions "
        f"in {stats['seconds']}s."
    )


if __name__ == "__main__":
    collect_all()
