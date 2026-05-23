"""SBP prediction engine.

This is deliberately explainable. It is not pretending to be a finished ML model;
it is an AI-training/prediction layer that can be backtested and later replaced
or blended with Random Forest/XGBoost outputs.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from config import MAX_CONFIDENCE_WITHOUT_BACKTEST, MAX_FORECAST_ABS_PCT
from normalizers import infer_item_tags, pct_change, robust_median, safe_float, safe_int


@dataclass
class MarketSignals:
    source: str
    current_price: float
    previous_price: float = 0.0
    buy_price: float = 0.0
    sell_price: float = 0.0
    buy_volume: float = 0.0
    sell_volume: float = 0.0
    buy_moving_week: float = 0.0
    sell_moving_week: float = 0.0
    buy_orders: float = 0.0
    sell_orders: float = 0.0
    listed_count: int = 0
    sold_count_24h: int = 0
    median_price: float = 0.0
    avg_price: float = 0.0
    second_lowest_price: float = 0.0
    lower_quartile_price: float = 0.0
    coflnet_sales_per_day: float = 0.0
    coflnet_volatility: float = 0.0
    coflnet_median: float = 0.0
    coflnet_avg: float = 0.0
    history_points: int = 0
    history_hit_rate: float | None = None
    current_mayor: str = "Unknown"
    current_perks: list[str] = field(default_factory=list)
    current_metas: list[str] = field(default_factory=list)


MAYOR_WEIGHTS: dict[str, dict[str, float]] = {
    "aatrox": {"slayer": 26, "combat": 8, "dungeon": 2, "general": 1},
    "diana": {"diana": 34, "pet": 12, "accessory": 6, "combat": 3},
    "paul": {"dungeon": 30, "combat": 4, "fuel": 2},
    "cole": {"mining": 32, "fuel": 8, "mining_material": 12},
    "marina": {"fishing": 31, "pet": 4},
    "finnegan": {"farming": 28, "garden": 12},
    "foxy": {"fishing": 5, "mining": 5, "spooky": 12, "event": 10},
    "derpy": {"dungeon": -6, "minion": 28, "slayer": 10, "general": 4},
    "jerry": {"event": 14, "general": 5},
    "diaz": {"npc_flip": 18, "accessory": 12, "bazaar_material": 5, "general": 4},
    "scorpius": {"dark_auction": 35, "accessory": 16, "general": 5},
}

PERK_WEIGHTS: dict[str, dict[str, float]] = {
    "slayer xp": {"slayer": 12},
    "pathfinder": {"slayer": 18},
    "slashed": {"slayer": 8},
    "mythological": {"diana": 25, "pet": 8},
    "pet xp": {"pet": 10},
    "lucky": {"pet": 6, "diana": 5},
    "mining fiesta": {"mining": 20},
    "molten forge": {"mining": 14, "fuel": 5},
    "mining xp": {"mining": 6},
    "marauder": {"dungeon": 11},
    "benediction": {"dungeon": 9},
    "bonus score": {"dungeon": 16},
    "fishing festival": {"fishing": 18},
    "fishing xp": {"fishing": 6},
    "shopping spree": {"npc_flip": 15},
    "stock exchange": {"accessory": 12, "npc_flip": 12},
    "volume trading": {"accessory": 10},
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def log_score(value: float, scale: float = 1.0, cap: float = 20.0) -> float:
    if value <= 0:
        return 0.0
    return min(cap, math.log10(max(1.0, value)) * scale)


def direction_from_pct(pct: float) -> str:
    if pct > 2.0:
        return "up"
    if pct < -2.0:
        return "down"
    return "stable"


def tag_match_score(item_name: str, metas: list[str]) -> float:
    if not metas:
        return 0.0
    lower_name = item_name.lower()
    score = 0.0
    for meta in metas:
        lower_meta = str(meta).lower()
        words = [w for w in lower_name.split() if len(w) > 3]
        if lower_name in lower_meta or any(w in lower_meta for w in words[:4]):
            score += 9.0
    return min(22.0, score)


def mayor_effect_score(item_name: str, tags: list[str], signals: MarketSignals) -> tuple[float, list[str]]:
    reasons: list[str] = []
    mayor = signals.current_mayor.lower()
    score = 0.0
    for mayor_name, weights in MAYOR_WEIGHTS.items():
        if mayor_name in mayor:
            for tag in tags:
                score += weights.get(tag, 0.0)
            score += weights.get("general", 0.0)
            if score:
                reasons.append(f"{signals.current_mayor} context matches {', '.join(tags[:3])}")
            break
    for perk in signals.current_perks:
        perk_l = perk.lower()
        for key, weights in PERK_WEIGHTS.items():
            if key in perk_l:
                add = sum(weights.get(tag, 0.0) for tag in tags)
                if add:
                    score += add
                    reasons.append(f"Perk '{perk}' supports {', '.join(tags[:2])}")
    return clamp(score, -35.0, 45.0), reasons[:4]


def detect_manipulation(item_name: str, signals: MarketSignals) -> tuple[float, list[str]]:
    """Detect manual boosting/pumps/crashes that should weaken predictions.

    High score = more suspicious.
    """
    risk = 0.0
    flags: list[str] = []
    momentum = pct_change(signals.previous_price, signals.current_price)

    if signals.source == "bazaar":
        weekly_volume = signals.buy_moving_week + signals.sell_moving_week
        instant_volume = signals.buy_volume + signals.sell_volume
        spread_pct = 0.0
        if signals.buy_price > 0 and signals.sell_price > 0:
            spread_pct = abs(signals.buy_price - signals.sell_price) / max(signals.current_price, 1.0) * 100.0
        order_total = signals.buy_orders + signals.sell_orders
        order_imbalance = abs(signals.buy_orders - signals.sell_orders) / max(1.0, order_total)

        if abs(momentum) > 15 and weekly_volume < 50_000:
            risk += 28
            flags.append("large price move on thin Bazaar weekly volume")
        if spread_pct > 12:
            risk += 18
            flags.append("very wide Bazaar spread")
        if order_imbalance > 0.88 and order_total < 12:
            risk += 16
            flags.append("thin one-sided Bazaar orders")
        if abs(momentum) > 30 and instant_volume < 10_000:
            risk += 24
            flags.append("pump/crash pattern without matching instant volume")
    else:
        fair_ref = signals.lower_quartile_price or signals.median_price or signals.coflnet_median
        if fair_ref > 0 and signals.current_price > fair_ref * 1.60:
            risk += 32
            flags.append("lowest BIN is far above lower-quartile/median price")
        if fair_ref > 0 and signals.current_price < fair_ref * 0.62:
            risk += 26
            flags.append("lowest BIN is far below median; possible undercut/crash bait")
        if signals.second_lowest_price > 0 and signals.current_price > 0:
            floor_gap = ((signals.second_lowest_price - signals.current_price) / signals.current_price) * 100.0
            if floor_gap > 45:
                risk += 18
                flags.append("single cheap listing far below next lowest BIN")
        if signals.listed_count <= 2:
            risk += 14
            flags.append("too few AH listings for reliable floor price")
        if abs(momentum) > 20 and signals.listed_count < 5:
            risk += 22
            flags.append("large AH move with very few active listings")
        if signals.coflnet_volatility > 0.45:
            risk += 14
            flags.append("high Coflnet price volatility")

    return clamp(risk, 0.0, 100.0), flags[:6]


def market_signal_score(signals: MarketSignals) -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 0.0
    momentum = pct_change(signals.previous_price, signals.current_price)
    if signals.previous_price > 0:
        score += clamp(momentum * 0.65, -25.0, 25.0)
        if abs(momentum) >= 2:
            reasons.append(f"recent price momentum is {momentum:+.1f}%")

    if signals.source == "bazaar":
        weekly_volume = signals.buy_moving_week + signals.sell_moving_week
        volume_score = log_score(weekly_volume, scale=2.4, cap=18)
        pressure = 0.0
        if signals.buy_orders + signals.sell_orders > 0:
            pressure = ((signals.buy_orders - signals.sell_orders) / max(1.0, signals.buy_orders + signals.sell_orders)) * 14.0
        buy_sell_vol_pressure = 0.0
        if signals.buy_volume + signals.sell_volume > 0:
            buy_sell_vol_pressure = ((signals.buy_volume - signals.sell_volume) / max(1.0, signals.buy_volume + signals.sell_volume)) * 9.0
        spread_pct = 0.0
        if signals.buy_price > 0 and signals.sell_price > 0:
            spread_pct = ((signals.buy_price - signals.sell_price) / max(signals.current_price, 1.0)) * 100.0

        score += volume_score * 0.35
        score += pressure * 0.55
        score += buy_sell_vol_pressure * 0.35
        score += clamp(spread_pct * 0.25, -5, 7)
        if volume_score > 9:
            reasons.append("high Bazaar weekly movement supports real demand")
        if abs(pressure) > 2:
            reasons.append(f"Bazaar order pressure is {pressure:+.1f}")
        if abs(buy_sell_vol_pressure) > 2:
            reasons.append(f"instant buy/sell pressure is {buy_sell_vol_pressure:+.1f}")
    else:
        listing_depth = log_score(signals.listed_count, scale=4.0, cap=12)
        sales_speed = log_score(signals.sold_count_24h or signals.coflnet_sales_per_day, scale=4.0, cap=14)
        score += listing_depth * 0.32
        score += sales_speed * 0.45
        fair_ref = signals.lower_quartile_price or signals.median_price or signals.coflnet_median
        if fair_ref > 0:
            undervalued_pct = ((fair_ref - signals.current_price) / fair_ref) * 100.0
            score += clamp(undervalued_pct * 0.45, -25.0, 25.0)
            if abs(undervalued_pct) > 5:
                reasons.append(f"AH floor differs from fair reference by {undervalued_pct:+.1f}%")
        if signals.listed_count:
            reasons.append(f"{signals.listed_count} active AH listings observed")
        if signals.sold_count_24h or signals.coflnet_sales_per_day:
            reasons.append("recent sold-auction data supports liquidity estimate")

    return clamp(score, -55.0, 55.0), reasons[:5]


def data_quality_score(signals: MarketSignals, manipulation: float) -> float:
    q = 0.0
    if signals.previous_price > 0:
        q += 10
    if signals.history_points >= 12:
        q += 8
    if signals.history_points >= 288:
        q += 8
    if signals.source == "bazaar":
        if signals.buy_moving_week + signals.sell_moving_week > 100_000:
            q += 12
        if signals.buy_orders + signals.sell_orders >= 20:
            q += 6
    else:
        if signals.listed_count >= 8:
            q += 10
        if signals.sold_count_24h >= 5 or signals.coflnet_sales_per_day >= 5:
            q += 12
        if signals.median_price > 0 or signals.coflnet_median > 0:
            q += 6
    q -= manipulation * 0.25
    return clamp(q, -15.0, 45.0)


def build_outcomes(current_price: float, forecast_pct: float, certainty: float, manipulation: float) -> list[dict[str, Any]]:
    # Five future paths. Probability values are approximate and calibrated by signal strength.
    strength = min(1.0, abs(forecast_pct) / 35.0)
    main_prob = clamp(certainty, 35, 86)
    if manipulation > 55:
        main_prob -= 12
    opposite_pct = -forecast_pct * 0.45
    stable_pct = forecast_pct * 0.15
    paths = [
        ("AI base case", forecast_pct, main_prob),
        ("Slower move", forecast_pct * 0.45, max(8, (100 - main_prob) * 0.28)),
        ("Flat/chop", stable_pct, max(5, (100 - main_prob) * 0.24)),
        ("Overreaction spike" if forecast_pct >= 0 else "Overreaction dump", forecast_pct * (1.45 + strength * 0.35), max(4, (100 - main_prob) * 0.20)),
        ("Reversal/manipulation unwind", opposite_pct, max(3, (100 - main_prob) * 0.28)),
    ]
    total = sum(p for _, _, p in paths)
    results: list[dict[str, Any]] = []
    for label, pct, prob in paths:
        norm_prob = prob / total * 100.0 if total else 20.0
        results.append({
            "label": label,
            "change_pct": round(pct, 2),
            "target_price": round(current_price * (1 + pct / 100.0), 2),
            "probability": round(norm_prob, 1),
        })
    return results


def predict_item(item_id: str, item_name: str, signals: MarketSignals) -> dict[str, Any]:
    tags = infer_item_tags(item_name, signals.source)
    signal_score, signal_reasons = market_signal_score(signals)
    mayor_score, mayor_reasons = mayor_effect_score(item_name, tags, signals)
    meta_score = tag_match_score(item_name, signals.current_metas)
    manipulation_score, manipulation_flags = detect_manipulation(item_name, signals)

    conflict_penalty = 0.0
    # If raw market momentum and event/mayor logic disagree, reduce certainty and magnitude.
    raw_momentum = pct_change(signals.previous_price, signals.current_price)
    directional_context = mayor_score + meta_score
    if raw_momentum and directional_context and (raw_momentum > 2 > directional_context or raw_momentum < -2 < directional_context):
        conflict_penalty += 10
    if signal_score * (mayor_score + meta_score) < -25:
        conflict_penalty += 12

    raw_score = signal_score + mayor_score * 0.48 + meta_score * 0.62
    raw_score -= manipulation_score * 0.33
    raw_score -= conflict_penalty * 0.35

    forecast_pct = clamp(raw_score * 0.72, -MAX_FORECAST_ABS_PCT, MAX_FORECAST_ABS_PCT)
    # Strong manipulation should never become a blind “going up” call.
    if manipulation_score >= 65:
        forecast_pct *= 0.35
    elif manipulation_score >= 45:
        forecast_pct *= 0.62

    direction = direction_from_pct(forecast_pct)

    quality = data_quality_score(signals, manipulation_score)
    certainty = 45.0 + quality + min(18.0, abs(forecast_pct) * 0.45) - conflict_penalty - min(25, manipulation_score * 0.28)
    if signals.history_hit_rate is not None:
        # Backtest stats override heuristic confidence when available.
        certainty = 0.55 * certainty + 0.45 * (signals.history_hit_rate * 100.0)
    else:
        certainty = min(certainty, MAX_CONFIDENCE_WITHOUT_BACKTEST)
    certainty = clamp(certainty, 25.0, 94.0)

    range_width = 0.025 + (100.0 - certainty) / 100.0 * 0.18 + min(0.18, manipulation_score / 400.0)
    expected_price = signals.current_price * (1 + forecast_pct / 100.0)
    low = expected_price * (1 - range_width)
    high = expected_price * (1 + range_width)
    outcomes = build_outcomes(signals.current_price, forecast_pct, certainty, manipulation_score)

    reasons = []
    reasons.extend(signal_reasons)
    reasons.extend(mayor_reasons)
    if meta_score:
        reasons.append("Outcro/current MMM text overlaps with this item or its category")
    if not reasons:
        reasons.append("Weak signal; prediction mostly based on stable current market data")

    risks = []
    risks.extend(manipulation_flags)
    if conflict_penalty:
        risks.append("market signals conflict with event/meta context")
    if signals.history_points < 12:
        risks.append("limited local snapshot history")
    if not risks:
        risks.append("normal market risk")

    rank_score = forecast_pct * (certainty / 100.0) * max(0.15, 1.0 - manipulation_score / 100.0)

    return {
        "item_id": item_id,
        "name": item_name,
        "source": signals.source,
        "current_price": round(signals.current_price, 2),
        "forecast_change_pct": round(forecast_pct, 3),
        "rank_score": round(rank_score, 4),
        "predicted_direction": direction,
        "confidence": round(certainty, 1),
        "certainty": round(certainty, 1),
        "expected_price": round(expected_price, 2),
        "expected_low": round(low, 2),
        "expected_high": round(high, 2),
        "timeframe": "24h-7d",
        "driver": reasons[0],
        "reason": "; ".join(reasons[:7]),
        "risk": risks[0],
        "risk_factors": "; ".join(risks[:7]),
        "manipulation_score": round(manipulation_score, 1),
        "manipulation_flags": json.dumps(manipulation_flags),
        "top_outcomes": json.dumps(outcomes),
        "similar_cases": "heuristic until backtest table is populated" if signals.history_hit_rate is None else f"backtest hit rate {signals.history_hit_rate:.1%}",
        "tags": json.dumps(tags),
        "updated_at": utc_now(),
    }
