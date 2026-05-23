"""Backtest stored predictions once future prices exist in price_snapshots.

Run this after the site has collected data for at least 24h/7d. It compares old
predictions to actual later snapshots and stores direction/range/error results.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from supabase import create_client

from config import SUPABASE_SERVICE_KEY, SUPABASE_URL
from normalizers import pct_change, safe_float

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def get_actual_price(item_id: str, target_time: datetime) -> tuple[float, str | None]:
    # Find nearest snapshot at/after target_time.
    result = (
        supabase.table("price_snapshots")
        .select("price,created_at")
        .eq("item_id", item_id)
        .gte("created_at", target_time.isoformat())
        .order("created_at")
        .limit(1)
        .execute()
    )
    if not result.data:
        return 0.0, None
    row = result.data[0]
    return safe_float(row.get("price")), row.get("created_at")


def direction(old_price: float, new_price: float) -> str:
    change = pct_change(old_price, new_price)
    if change > 2:
        return "up"
    if change < -2:
        return "down"
    return "stable"


def run_backtest(hours: int = 24, limit: int = 1000) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    preds = (
        supabase.table("predictions")
        .select("item_id,name,current_price,predicted_direction,expected_price,expected_low,expected_high,updated_at")
        .lt("updated_at", cutoff.isoformat())
        .limit(limit)
        .execute()
    ).data or []

    rows: list[dict[str, Any]] = []
    for pred in preds:
        created = parse_time(pred["updated_at"])
        target = created + timedelta(hours=hours)
        actual_price, actual_time = get_actual_price(pred["item_id"], target)
        if actual_price <= 0:
            continue
        current = safe_float(pred.get("current_price"))
        predicted_price = safe_float(pred.get("expected_price"))
        expected_low = safe_float(pred.get("expected_low"))
        expected_high = safe_float(pred.get("expected_high"))
        actual_direction = direction(current, actual_price)
        predicted_direction = str(pred.get("predicted_direction") or "stable").lower()
        direction_correct = actual_direction == predicted_direction
        range_hit = expected_low <= actual_price <= expected_high if expected_low and expected_high else False
        err = abs(pct_change(actual_price, predicted_price)) if actual_price else 0.0
        rows.append({
            "item_id": pred["item_id"],
            "prediction_created_at": pred["updated_at"],
            "target_time": actual_time,
            "predicted_direction": predicted_direction,
            "predicted_price": round(predicted_price, 2),
            "expected_low": round(expected_low, 2),
            "expected_high": round(expected_high, 2),
            "actual_price": round(actual_price, 2),
            "direction_correct": direction_correct,
            "range_hit": range_hit,
            "error_pct": round(err, 3),
            "notes": f"{hours}h backtest for {pred.get('name')}",
        })

    if rows:
        for i in range(0, len(rows), 500):
            supabase.table("prediction_backtests").insert(rows[i:i+500]).execute()
    print(f"Backtested {len(rows)} mature predictions over {hours}h horizon.")


if __name__ == "__main__":
    run_backtest(hours=24)
