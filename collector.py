import os
import re
import math
import time
import hashlib
from datetime import datetime, timezone

import requests
from supabase import create_client

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

print("SBP FINAL COLLECTOR ALL AH + ALL BZ VERSION RUNNING")

HYPIXEL_BAZAAR_URL = "https://api.hypixel.net/v2/skyblock/bazaar"
HYPIXEL_AUCTIONS_URL = "https://api.hypixel.net/v2/skyblock/auctions"
HYPIXEL_ELECTION_URL = "https://api.hypixel.net/v2/resources/skyblock/election"

MINIMUM_PRICE = int(os.getenv("MINIMUM_PRICE", "0"))

# Use "all" for a full AH sweep. Use a number like "10" for testing.
# With MINIMUM_PRICE=0, this collects cheap items too, including wheat-level Bazaar products.
AH_MAX_PAGES = os.getenv("AH_MAX_PAGES", "all").strip().lower()

SLEEP_BETWEEN_AH_PAGES = float(os.getenv("SLEEP_BETWEEN_AH_PAGES", "0.25"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "45"))
UPSERT_CHUNK_SIZE = int(os.getenv("UPSERT_CHUNK_SIZE", "500"))

# Meta is subjective. Set this manually in Render env later if you want a verified label.
# Example: CURRENT_META_OVERRIDE="Kuudra / Aurora attribute demand"
CURRENT_META_OVERRIDE = os.getenv("CURRENT_META_OVERRIDE", "").strip()


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def safe_float(value, fallback=0.0):
    try:
        if value is None:
            return fallback
        value = float(value)
        if math.isnan(value) or math.isinf(value):
            return fallback
        return value
    except Exception:
        return fallback


def pct_change(old, new):
    old = safe_float(old)
    new = safe_float(new)
    if old <= 0:
        return 0.0
    return ((new - old) / old) * 100


def nice_name(product_id):
    return str(product_id).replace("_", " ").title()


def clean_name(name):
    if not name:
        return "Unknown Item"
    name = re.sub(r"§.", "", str(name))
    return " ".join(name.split()).strip()


def stable_ah_id(item_name):
    cleaned = clean_name(item_name).lower()
    digest = hashlib.sha1(cleaned.encode("utf-8")).hexdigest()[:14]
    return f"AH:{digest}"


def get_json(url, params=None):
    response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
    if response.status_code == 429:
        raise RuntimeError(f"Rate limited while requesting {url}. Try a slower schedule or fewer AH pages.")
    response.raise_for_status()
    return response.json()


def chunked(rows, size=UPSERT_CHUNK_SIZE):
    for i in range(0, len(rows), size):
        yield rows[i:i + size]


def upsert_rows(table, rows):
    if not rows:
        return
    for chunk in chunked(rows):
        supabase.table(table).upsert(chunk).execute()


def insert_rows(table, rows):
    if not rows:
        return
    for chunk in chunked(rows):
        supabase.table(table).insert(chunk).execute()


def fetch_previous_prices():
    previous = {}
    page_size = 1000
    start = 0

    while True:
        end = start + page_size - 1
        result = (
            supabase.table("items")
            .select("id,current_price")
            .range(start, end)
            .execute()
        )
        data = result.data or []
        for row in data:
            previous[row["id"]] = safe_float(row.get("current_price"))
        if len(data) < page_size:
            break
        start += page_size

    return previous


def score_market_item(item_id, name, source, current_price, previous_price, quick=None, ah_count=0):
    quick = quick or {}

    buy_price = safe_float(quick.get("buyPrice"))
    sell_price = safe_float(quick.get("sellPrice"))
    buy_volume = safe_float(quick.get("buyVolume"))
    sell_volume = safe_float(quick.get("sellVolume"))
    buy_moving_week = safe_float(quick.get("buyMovingWeek"))
    sell_moving_week = safe_float(quick.get("sellMovingWeek"))
    buy_orders = safe_float(quick.get("buyOrders"))
    sell_orders = safe_float(quick.get("sellOrders"))

    momentum = pct_change(previous_price, current_price) if previous_price else 0.0

    spread_pct = 0.0
    if buy_price > 0 and sell_price > 0:
        spread_pct = ((buy_price - sell_price) / buy_price) * 100

    if source == "bazaar":
        total_week_volume = buy_moving_week + sell_moving_week
        volume_score = min(10.0, math.log10(max(1.0, total_week_volume)) * 1.25)
        order_pressure = 0.0
        if buy_orders + sell_orders > 0:
            order_pressure = ((buy_orders - sell_orders) / max(1.0, buy_orders + sell_orders)) * 10

        forecast_change = (
            momentum * 0.45
            + spread_pct * 0.18
            + volume_score * 0.35
            + order_pressure * 0.25
        )

        if total_week_volume > 5_000_000:
            demand = "Very High"
        elif total_week_volume > 700_000:
            demand = "High"
        elif total_week_volume > 100_000:
            demand = "Medium"
        else:
            demand = "Low"

        if abs(momentum) > 20:
            risk = "Volatile"
        elif abs(spread_pct) > 8:
            risk = "Wide spread"
        else:
            risk = "Normal"

        if momentum > 5:
            driver = "Positive price momentum"
        elif order_pressure > 2:
            driver = "Buy order pressure"
        elif volume_score > 7:
            driver = "High weekly volume"
        elif spread_pct > 3:
            driver = "Bazaar spread opportunity"
        else:
            driver = "Stable market activity"

        confidence = 45 + min(22, volume_score * 2.1) - min(12, abs(spread_pct) * 0.35)
        confidence += min(12, abs(momentum) * 0.4)

    else:
        # AH prediction is only a placeholder signal until the real AI replaces it.
        listing_score = min(10.0, math.log10(max(1.0, ah_count)) * 3.0)
        forecast_change = momentum * 0.5 + listing_score * 0.6
        demand = "Unknown"
        risk = "AH listing risk" if ah_count <= 2 else "Normal"
        driver = "Lowest BIN movement"
        confidence = 40 + min(18, listing_score * 2) + min(12, abs(momentum) * 0.3)

    forecast_change = max(-25.0, min(35.0, forecast_change))
    confidence = max(35.0, min(92.0, confidence))

    return {
        "item_id": item_id,
        "name": name,
        "current_price": round(current_price, 2),
        "forecast_change_pct": round(forecast_change, 3),
        "confidence": round(confidence, 1),
        "driver": driver,
        "demand": demand,
        "risk": risk,
        "reason": driver,
        "updated_at": utc_now()
    }


def collect_bazaar(previous_prices):
    print("Pulling Bazaar data...")
    payload = get_json(HYPIXEL_BAZAAR_URL)

    if not payload.get("success"):
        raise RuntimeError("Hypixel Bazaar API did not return success.")

    now = utc_now()
    item_rows = []
    snapshot_rows = []
    prediction_rows = []

    for product_id, product in payload.get("products", {}).items():
        quick = product.get("quick_status", {})

        buy_price = safe_float(quick.get("buyPrice"))
        sell_price = safe_float(quick.get("sellPrice"))
        current_price = buy_price if buy_price > 0 else sell_price

        if current_price < MINIMUM_PRICE:
            continue

        item_rows.append({
            "id": product_id,
            "name": nice_name(product_id),
            "source": "bazaar",
            "current_price": round(current_price, 2),
            "buy_price": round(buy_price, 2),
            "sell_price": round(sell_price, 2),
            "buy_volume": safe_float(quick.get("buyVolume")),
            "sell_volume": safe_float(quick.get("sellVolume")),
            "buy_moving_week": safe_float(quick.get("buyMovingWeek")),
            "sell_moving_week": safe_float(quick.get("sellMovingWeek")),
            "updated_at": now,
        })

        snapshot_rows.append({
            "item_id": product_id,
            "price": round(current_price, 2),
            "buy_price": round(buy_price, 2),
            "sell_price": round(sell_price, 2),
            "buy_volume": safe_float(quick.get("buyVolume")),
            "sell_volume": safe_float(quick.get("sellVolume")),
            "buy_moving_week": safe_float(quick.get("buyMovingWeek")),
            "sell_moving_week": safe_float(quick.get("sellMovingWeek")),
            "created_at": now,
        })

        prediction_rows.append(
            score_market_item(
                item_id=product_id,
                name=nice_name(product_id),
                source="bazaar",
                current_price=current_price,
                previous_price=previous_prices.get(product_id),
                quick=quick
            )
        )

    return item_rows, snapshot_rows, prediction_rows


def fetch_auction_pages():
    print("Pulling Auction House data...")
    first = get_json(HYPIXEL_AUCTIONS_URL, {"page": 0})

    if not first.get("success"):
        raise RuntimeError("Hypixel Auction API did not return success.")

    total_pages = int(first.get("totalPages", 1))

    if AH_MAX_PAGES != "all":
        total_pages = min(total_pages, max(1, int(AH_MAX_PAGES)))

    auctions = []
    for page in range(total_pages):
        if page == 0:
            payload = first
        else:
            payload = get_json(HYPIXEL_AUCTIONS_URL, {"page": page})
            time.sleep(SLEEP_BETWEEN_AH_PAGES)

        page_auctions = payload.get("auctions", [])
        auctions.extend(page_auctions)
        print(f"AH page {page + 1}/{total_pages} | total auctions collected: {len(auctions)}")

    return auctions


def collect_auction_house(previous_prices):
    auctions = fetch_auction_pages()

    lowest_bins = {}

    for auction in auctions:
        if not auction.get("bin"):
            continue

        name = clean_name(auction.get("item_name"))
        price = safe_float(auction.get("starting_bid"))

        if not name or price < MINIMUM_PRICE:
            continue

        key = name.lower()

        if key not in lowest_bins:
            lowest_bins[key] = {
                "name": name,
                "current_price": price,
                "count": 1
            }
        else:
            lowest_bins[key]["count"] += 1
            if price < lowest_bins[key]["current_price"]:
                lowest_bins[key]["current_price"] = price

    now = utc_now()
    item_rows = []
    snapshot_rows = []
    prediction_rows = []

    for item in lowest_bins.values():
        item_id = stable_ah_id(item["name"])
        current_price = safe_float(item["current_price"])

        item_rows.append({
            "id": item_id,
            "name": item["name"],
            "source": "auction",
            "current_price": round(current_price, 2),
            "buy_price": 0,
            "sell_price": 0,
            "buy_volume": item.get("count", 0),
            "sell_volume": 0,
            "buy_moving_week": 0,
            "sell_moving_week": 0,
            "updated_at": now,
        })

        snapshot_rows.append({
            "item_id": item_id,
            "price": round(current_price, 2),
            "buy_price": 0,
            "sell_price": 0,
            "buy_volume": item.get("count", 0),
            "sell_volume": 0,
            "buy_moving_week": 0,
            "sell_moving_week": 0,
            "created_at": now,
        })

        prediction_rows.append(
            score_market_item(
                item_id=item_id,
                name=item["name"],
                source="auction",
                current_price=current_price,
                previous_price=previous_prices.get(item_id),
                ah_count=item.get("count", 0)
            )
        )

    return item_rows, snapshot_rows, prediction_rows


def fetch_current_mayor_text():
    try:
        payload = get_json(HYPIXEL_ELECTION_URL)
        mayor = payload.get("mayor") or {}

        name = mayor.get("name") or "Unknown mayor"
        perks_raw = mayor.get("perks") or []
        perks = []

        for perk in perks_raw:
            if isinstance(perk, dict):
                perk_name = perk.get("name")
                if perk_name:
                    perks.append(perk_name)
            elif isinstance(perk, str):
                perks.append(perk)

        if perks:
            return f"{name} — {', '.join(perks[:3])}"
        return name

    except Exception as exc:
        return f"Unknown mayor ({exc})"


def update_market_context(stats):
    current_mayor = fetch_current_mayor_text()

    current_meta = (
        CURRENT_META_OVERRIDE
        if CURRENT_META_OVERRIDE
        else "Work in progress — verified meta source pending"
    )

    context_row = {
        "id": 1,
        "current_mayor": current_mayor,
        "current_meta": current_meta,
        "ai_factor_1": f"{stats.get('total_items', 0)} items tracked",
        "ai_factor_2": "Update/event slot — work in progress",
        "updated_at": utc_now()
    }

    supabase.table("market_context").upsert(context_row).execute()


def collect_all():
    previous_prices = fetch_previous_prices()

    bz_items, bz_snapshots, bz_predictions = collect_bazaar(previous_prices)
    ah_items, ah_snapshots, ah_predictions = collect_auction_house(previous_prices)

    item_rows = bz_items + ah_items
    snapshot_rows = bz_snapshots + ah_snapshots
    prediction_rows = bz_predictions + ah_predictions

    print(f"Upserting {len(item_rows)} items...")
    upsert_rows("items", item_rows)

    print(f"Inserting {len(snapshot_rows)} price snapshots...")
    insert_rows("price_snapshots", snapshot_rows)

    print(f"Upserting {len(prediction_rows)} predictions...")
    upsert_rows("predictions", prediction_rows)

    stats = {
        "bazaar_items": len(bz_items),
        "auction_items": len(ah_items),
        "total_items": len(item_rows),
        "snapshots": len(snapshot_rows),
        "predictions": len(prediction_rows),
        "ah_max_pages": AH_MAX_PAGES,
        "minimum_price": MINIMUM_PRICE
    }

    update_market_context(stats)

    print(
        f"Saved {stats['total_items']} items, "
        f"{stats['snapshots']} snapshots, "
        f"{stats['predictions']} predictions."
    )


if __name__ == "__main__":
    collect_all()
