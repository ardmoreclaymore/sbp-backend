import os
import math
import requests
from datetime import datetime, timezone
from supabase import create_client

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

HYPIXEL_BAZAAR_URL = "https://api.hypixel.net/v2/skyblock/bazaar"
MINIMUM_PRICE = 100_000


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


def nice_name(product_id):
    return product_id.replace("_", " ").title()


def pct_change(old, new):
    if old <= 0:
        return 0.0
    return ((new - old) / old) * 100


def get_recent_history(item_id, limit=20):
    result = (
        supabase.table("price_snapshots")
        .select("price,created_at")
        .eq("item_id", item_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )

    rows = result.data or []
    rows.reverse()
    return rows


def score_item(product_id, quick):
    buy_price = safe_float(quick.get("buyPrice"))
    sell_price = safe_float(quick.get("sellPrice"))
    current_price = buy_price if buy_price > 0 else sell_price

    buy_volume = safe_float(quick.get("buyVolume"))
    sell_volume = safe_float(quick.get("sellVolume"))
    buy_moving_week = safe_float(quick.get("buyMovingWeek"))
    sell_moving_week = safe_float(quick.get("sellMovingWeek"))
    buy_orders = safe_float(quick.get("buyOrders"))
    sell_orders = safe_float(quick.get("sellOrders"))

    history = get_recent_history(product_id, 20)
    old_price = safe_float(history[0]["price"]) if len(history) >= 2 else current_price
    momentum = pct_change(old_price, current_price)

    spread_pct = 0
    if buy_price > 0 and sell_price > 0:
        spread_pct = ((buy_price - sell_price) / buy_price) * 100

    volume_score = min(10.0, math.log10(max(1.0, buy_moving_week + sell_moving_week)) * 1.3)

    order_pressure = 0
    if buy_orders + sell_orders > 0:
        order_pressure = ((buy_orders - sell_orders) / max(1.0, buy_orders + sell_orders)) * 10

    forecast_change = (momentum * 0.45) + (spread_pct * 0.18) + (volume_score * 0.35) + (order_pressure * 0.25)
    forecast_change = max(-25, min(35, forecast_change))

    confidence = 45
    confidence += min(25, len(history) * 2)
    confidence += min(20, volume_score * 2)
    confidence -= min(15, abs(spread_pct) * 0.4)
    confidence = max(35, min(92, confidence))

    total_week_volume = buy_moving_week + sell_moving_week

    if total_week_volume > 5_000_000:
        demand = "Very High"
    elif total_week_volume > 700_000:
        demand = "High"
    elif total_week_volume > 100_000:
        demand = "Medium"
    else:
        demand = "Low"

    if len(history) < 3:
        risk = "Needs more history"
    elif abs(momentum) > 20:
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

    return {
        "item_id": product_id,
        "name": nice_name(product_id),
        "current_price": round(current_price, 2),
        "forecast_change_pct": round(forecast_change, 3),
        "confidence": round(confidence, 1),
        "driver": driver,
        "demand": demand,
        "risk": risk,
        "reason": driver,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }


def collect_bazaar():
    response = requests.get(HYPIXEL_BAZAAR_URL, timeout=30)
    response.raise_for_status()
    payload = response.json()

    if not payload.get("success"):
        raise RuntimeError("Hypixel Bazaar API failed.")

    products = payload.get("products", {})
    now = datetime.now(timezone.utc).isoformat()

    item_rows = []
    snapshot_rows = []
    prediction_rows = []

    for product_id, product in products.items():
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
            "current_price": current_price,
            "buy_price": buy_price,
            "sell_price": sell_price,
            "buy_volume": safe_float(quick.get("buyVolume")),
            "sell_volume": safe_float(quick.get("sellVolume")),
            "buy_moving_week": safe_float(quick.get("buyMovingWeek")),
            "sell_moving_week": safe_float(quick.get("sellMovingWeek")),
            "updated_at": now,
        })

        snapshot_rows.append({
            "item_id": product_id,
            "price": current_price,
            "buy_price": buy_price,
            "sell_price": sell_price,
            "buy_volume": safe_float(quick.get("buyVolume")),
            "sell_volume": safe_float(quick.get("sellVolume")),
            "buy_moving_week": safe_float(quick.get("buyMovingWeek")),
            "sell_moving_week": safe_float(quick.get("sellMovingWeek")),
            "created_at": now,
        })

        prediction_rows.append(score_item(product_id, quick))

    if item_rows:
        supabase.table("items").upsert(item_rows).execute()

    if snapshot_rows:
        supabase.table("price_snapshots").insert(snapshot_rows).execute()

    if prediction_rows:
        supabase.table("predictions").upsert(prediction_rows).execute()

    print(f"Saved {len(item_rows)} items, {len(snapshot_rows)} snapshots, {len(prediction_rows)} predictions.")


if __name__ == "__main__":
    collect_bazaar()
