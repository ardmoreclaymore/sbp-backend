from normalizers import safe_float, spread_pct, pct_change


def demand_label(score):
    if score >= 70:
        return "Very High"
    if score >= 45:
        return "High"
    if score >= 22:
        return "Medium"
    return "Low"


def direction_from_change(change_pct):
    if change_pct > 2.5:
        return "UP"
    if change_pct < -2.5:
        return "DOWN"
    return "STABLE"


def manipulation_flags(item):
    flags = []
    source = str(item.get("source", "")).lower()
    price = safe_float(item.get("current_price"))
    volume = safe_float(item.get("volume_24h") or item.get("volume"))
    listed = safe_float(item.get("listed_count"))
    spread = safe_float(item.get("spread_pct"))
    change_5m = abs(safe_float(item.get("price_change_5m_pct")))
    if price > 0 and volume <= 0 and source == "bazaar":
        flags.append("price without visible volume")
    if spread >= 15:
        flags.append("wide spread")
    if listed > 0 and listed <= 3 and source == "auction":
        flags.append("thin AH floor")
    if change_5m >= 18 and volume <= 5:
        flags.append("thin-volume pump/drop")
    if change_5m >= 35:
        flags.append("extreme short-term volatility")
    return flags


def manipulation_score(item):
    flags = manipulation_flags(item)
    score = len(flags) * 18
    spread = safe_float(item.get("spread_pct"))
    change_5m = abs(safe_float(item.get("price_change_5m_pct")))
    listed = safe_float(item.get("listed_count"))
    score += min(25, spread * 0.65)
    score += min(30, change_5m * 0.8)
    if 0 < listed <= 2:
        score += 18
    return max(0, min(100, round(score, 2)))


def factor_bonus(item, matched_factors):
    bonus = 0.0
    notes = []
    for factor in (matched_factors or [])[:8]:
        reliability = safe_float(factor.get("reliability_score"), 50)
        impact_min = safe_float(factor.get("estimated_impact_min_pct"), 0)
        impact_max = safe_float(factor.get("estimated_impact_max_pct"), 0)
        impact = (impact_min + impact_max) / 2 if impact_min or impact_max else 0
        match = safe_float(factor.get("match_score"), 1)
        weighted = impact * (reliability / 100.0) * min(match, 10) / 10.0
        bonus += weighted
        name = factor.get("variable_name")
        if name:
            notes.append(str(name))
    return bonus, notes[:5]


def score_item(item, history=None, matched_factors=None):
    history = history or []
    matched_factors = matched_factors or []
    current = safe_float(item.get("current_price"))
    buy = safe_float(item.get("buy_price"))
    sell = safe_float(item.get("sell_price"))
    volume = safe_float(item.get("volume_24h") or item.get("volume"))
    listed = safe_float(item.get("listed_count"))
    spread = safe_float(item.get("spread_pct"))
    if spread <= 0:
        spread = spread_pct(buy, sell)
    prev_price = None
    if history:
        for row in history:
            p = safe_float(row.get("price") or row.get("current_price") or row.get("sell_price") or row.get("buy_price"))
            if p > 0:
                prev_price = p
                break
    recent_change = pct_change(prev_price, current) if prev_price else safe_float(item.get("price_change_5m_pct"))
    score = 0.0
    reasons = []
    if recent_change > 0:
        score += min(22, recent_change * 1.8)
        reasons.append("recent price strength")
    elif recent_change < 0:
        score += max(-22, recent_change * 1.6)
        reasons.append("recent price weakness")
    if volume > 0:
        score += min(16, volume ** 0.5 / 25)
        reasons.append("visible market volume")
    if spread > 0 and spread < 4:
        score += 7
        reasons.append("tight spread")
    elif spread >= 12:
        score -= min(20, spread * 0.8)
        reasons.append("wide spread risk")
    if listed > 0:
        if listed <= 3:
            score -= 10
            reasons.append("thin AH listing depth")
        elif listed >= 20:
            score += 5
            reasons.append("healthy listing depth")
    f_bonus, f_notes = factor_bonus(item, matched_factors)
    if f_bonus:
        score += max(-18, min(18, f_bonus))
        reasons.append("factor-bank match")
    manip = manipulation_score(item)
    flags = manipulation_flags(item)
    if manip >= 45:
        score -= min(35, manip * 0.45)
        reasons.append("manual boosting/manipulation risk")
    forecast_change_pct = max(-55, min(75, score / 2.2))
    predicted_direction = direction_from_change(forecast_change_pct)
    base_certainty = 50 + min(28, abs(score) * 0.55)
    if volume <= 0:
        base_certainty -= 8
    if manip >= 45:
        base_certainty -= 18
    if spread >= 15:
        base_certainty -= 8
    certainty = max(22, min(88, base_certainty))
    expected_price = current * (1 + forecast_change_pct / 100.0) if current > 0 else None
    expected_low = expected_price * 0.92 if expected_price else None
    expected_high = expected_price * 1.10 if expected_price else None
    demand_score = max(0, min(100, score + 45))
    demand = demand_label(demand_score)
    supply = "Low" if 0 < listed <= 3 else "Medium" if listed < 20 else "High"
    risk_text = "Wide spread / manipulation risk" if flags else "Normal market risk"
    top_outcomes = []
    if expected_price:
        top_outcomes = [
            {"label": "base path", "probability": round(certainty, 1), "target_price": round(expected_price, 2)},
            {"label": "bullish path", "probability": round(max(5, certainty - 18), 1), "target_price": round(expected_price * 1.12, 2)},
            {"label": "bearish path", "probability": round(max(5, 100 - certainty), 1), "target_price": round(expected_price * 0.88, 2)},
            {"label": "flat path", "probability": 30, "target_price": round(current, 2)},
            {"label": "manipulation unwind", "probability": round(min(65, manip), 1), "target_price": round(current * 0.82, 2)},
        ]
    return {
        "item_id": item.get("id"),
        "name": item.get("name"),
        "source": item.get("source"),
        "current_price": current,
        "forecast_change_pct": round(forecast_change_pct, 2),
        "rank_score": round(score, 2),
        "predicted_direction": predicted_direction,
        "confidence": round(certainty, 1),
        "certainty": round(certainty, 1),
        "expected_price": round(expected_price, 2) if expected_price else None,
        "expected_low": round(expected_low, 2) if expected_low else None,
        "expected_high": round(expected_high, 2) if expected_high else None,
        "timeframe": "24h-7d",
        "driver": ", ".join(reasons[:4]) or "neutral market signals",
        "reason": "; ".join(reasons[:7]) or "No strong directional signals yet.",
        "risk": risk_text,
        "risk_factors": risk_text,
        "manipulation_score": manip,
        "manipulation_flags": flags,
        "top_outcomes": top_outcomes,
        "similar_cases": "Heuristic until enough backtest rows are collected.",
        "tags": f_notes,
        "demand": demand,
        "supply": supply,
        "volume": safe_float(item.get("volume")),
        "volume_24h": safe_float(item.get("volume_24h")),
        "buy_price": safe_float(item.get("buy_price")),
        "sell_price": safe_float(item.get("sell_price")),
        "spread_pct": safe_float(item.get("spread_pct")),
        "buy_volume": safe_float(item.get("buy_volume")),
        "sell_volume": safe_float(item.get("sell_volume")),
        "buy_moving_week": safe_float(item.get("buy_moving_week")),
        "sell_moving_week": safe_float(item.get("sell_moving_week")),
        "buy_orders": safe_float(item.get("buy_orders")),
        "sell_orders": safe_float(item.get("sell_orders")),
        "listed_count": int(safe_float(item.get("listed_count"))),
        "sold_count_24h": int(safe_float(item.get("sold_count_24h"))),
        "market_type": item.get("market_type"),
        "category": item.get("category"),
        "raw_data": item.get("raw_data") or {},
    }
