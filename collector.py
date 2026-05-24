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

print("SBP SCREENSHOT WEBSITE COLLECTOR: ALL AH + ALL BZ + MAYOR + MINISTER")

HYPIXEL_BAZAAR_URL = "https://api.hypixel.net/v2/skyblock/bazaar"
HYPIXEL_AUCTIONS_URL = "https://api.hypixel.net/v2/skyblock/auctions"
HYPIXEL_ELECTION_URL = "https://api.hypixel.net/v2/resources/skyblock/election"

# 0 means even wheat-level Bazaar products are tracked.
MINIMUM_PRICE = int(os.getenv("MINIMUM_PRICE", "0"))

# Use "all" for full Auction House sweep. Use 10/25/50 for testing.
AH_MAX_PAGES = os.getenv("AH_MAX_PAGES", "all").strip().lower()

SLEEP_BETWEEN_AH_PAGES = float(os.getenv("SLEEP_BETWEEN_AH_PAGES", "0.25"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "45"))
UPSERT_CHUNK_SIZE = int(os.getenv("UPSERT_CHUNK_SIZE", "500"))

# Optional manual meta label. Do not fake meta automatically.
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


def guess_category(name, source="bazaar"):
    text = (name or "").upper()
    if "KUUDRA" in text:
        return "KUUDRA"
    if "ENCHANT" in text or "BOOK" in text:
        return "ENCHANT"
    if "ESSENCE" in text or "DUNGEON" in text or "NECRON" in text or "STORM" in text or "WITHER" in text:
        return "DUNGEON"
    if "DRAGON" in text or "SLAYER" in text or "REVENANT" in text or "TARANTULA" in text or "SVEN" in text or "VOIDGLOOM" in text or "BLAZE" in text:
        return "SLAYER"
    if "FISH" in text or "SHARK" in text or "ROD" in text:
        return "FISHING"
    if "WHEAT" in text or "CARROT" in text or "POTATO" in text or "MELON" in text or "PUMPKIN" in text or "CACTUS" in text:
        return "FARMING"
    if "MITHRIL" in text or "GEMSTONE" in text or "JADE" in text or "AMBER" in text or "RUBY" in text or "SAPPHIRE" in text:
        return "MINING"
    if source == "auction":
        return "AUCTION"
    return "BAZAAR"


def get_json(url, params=None):
    response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
    if response.status_code == 429:
        raise RuntimeError(f"Rate limited while requesting {url}. Use fewer AH pages or more delay.")
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
        result = (
            supabase.table("items")
            .select("id,current_price")
            .range(start, start + page_size - 1)
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
        spread_pct = ((buy_price - sell_price) / max(1.0, buy_price)) * 100

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

        name = nice_name(product_id)

        item_rows.append({
            "id": product_id,
            "name": name,
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
                name=name,
                source="bazaar",
                current_price=current_price,
                previous_price=previous_prices.get(product_id),
                quick=quick
            )
        )

    print(f"Bazaar items collected: {len(item_rows)}")
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

    print(f"Auction item types collected: {len(item_rows)}")
    return item_rows, snapshot_rows, prediction_rows


def parse_minister_from_payload(payload):
    """
    Hypixel's election resource may change shape over time.
    This parser intentionally reads the current mayor object first and only
    uses minister-like fields if they are actually present.
    It does NOT use the next election leader as current mayor.
    """
    mayor = payload.get("mayor") or {}

    candidates = []
    election = payload.get("current") or payload.get("election") or {}
    if isinstance(election, dict):
        candidates = election.get("candidates") or []

    possible = [
        mayor.get("minister"),
        mayor.get("minister_candidate"),
        mayor.get("ministerCandidate"),
        payload.get("minister"),
        payload.get("current_minister"),
    ]

    for obj in possible:
        if isinstance(obj, dict):
            name = obj.get("name") or obj.get("candidate") or obj.get("mayor")
            perk_obj = obj.get("perk") or obj.get("minister_perk") or obj.get("ministerPerk") or {}
            perk_name = ""
            perk_desc = ""

            if isinstance(perk_obj, dict):
                perk_name = perk_obj.get("name") or perk_obj.get("perk") or ""
                perk_desc = perk_obj.get("description") or perk_obj.get("desc") or ""
            elif isinstance(perk_obj, str):
                perk_name = perk_obj

            if not perk_name:
                perk_name = obj.get("perk_name") or obj.get("perkName") or obj.get("minister_perk_name") or ""
            if not perk_desc:
                perk_desc = obj.get("perk_description") or obj.get("perkDescription") or ""

            if name:
                return name, perk_name or "Unknown minister perk", perk_desc

    # If API does not expose the minister cleanly, don't guess from next election.
    return "Minister unavailable", "Minister perk unavailable", "Hypixel API did not expose a parsed minister field."


def fetch_current_election_context():
    try:
        payload = get_json(HYPIXEL_ELECTION_URL)
        mayor = payload.get("mayor") or {}

        mayor_name = mayor.get("name") or "Unknown mayor"
        perks_raw = mayor.get("perks") or []
        mayor_perks = []

        for perk in perks_raw:
            if isinstance(perk, dict):
                perk_name = perk.get("name")
                if perk_name:
                    mayor_perks.append(perk_name)
            elif isinstance(perk, str):
                mayor_perks.append(perk)

        minister_name, minister_perk, minister_desc = parse_minister_from_payload(payload)

        return {
            "current_mayor": mayor_name,
            "current_mayor_perks": ", ".join(mayor_perks) if mayor_perks else "No mayor perks parsed yet.",
            "current_minister": minister_name,
            "current_minister_perk": minister_perk,
            "current_minister_perk_description": minister_desc,
            "election_year": str(payload.get("lastUpdated") or ""),
            "raw_payload": payload
        }

    except Exception as exc:
        return {
            "current_mayor": f"Unknown mayor ({exc})",
            "current_mayor_perks": "Unavailable",
            "current_minister": "Minister unavailable",
            "current_minister_perk": "Minister perk unavailable",
            "current_minister_perk_description": str(exc),
            "election_year": "",
            "raw_payload": {"error": str(exc)}
        }


def update_market_context(stats):
    election = fetch_current_election_context()

    current_meta = (
        CURRENT_META_OVERRIDE
        if CURRENT_META_OVERRIDE
        else "Market context feed"
    )

    context_row = {
        "id": 1,
        "current_mayor": election["current_mayor"],
        "current_mayor_perks": election["current_mayor_perks"],
        "current_minister": election["current_minister"],
        "current_minister_perk": election["current_minister_perk"],
        "current_minister_perk_description": election["current_minister_perk_description"],
        "current_meta": current_meta,
        "ai_factor_1": f"{stats.get('total_items', 0)} items tracked",
        "ai_factor_2": f"{stats.get('auction_items', 0)} AH item types + {stats.get('bazaar_items', 0)} BZ products",
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
