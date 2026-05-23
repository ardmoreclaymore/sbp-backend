def load_prediction_factors(supabase):
    try:
        response = supabase.table("prediction_factors").select("*").eq("enabled", True).execute()
        return response.data or []
    except Exception as exc:
        print(f"[factor_loader] prediction_factors unavailable: {exc}")
        return []


def match_factors_to_item(item, factors, limit=25):
    item_name = str(item.get("name", "")).lower()
    item_category = str(item.get("category", "")).lower()
    item_source = str(item.get("source", "")).lower()
    item_tags = str(item.get("tags") or "").lower()
    matched = []
    for factor in factors or []:
        variable_name = str(factor.get("variable_name") or "").lower()
        category = str(factor.get("category") or "").lower()
        item_group = str(factor.get("item_group") or "").lower()
        market_source = str(factor.get("market_source") or "").lower()
        raw_blob = str(factor.get("raw_data") or "").lower()
        score = 0
        if item_group and item_group in item_name:
            score += 7
        if item_group and item_group in item_tags:
            score += 5
        if category and category in item_category:
            score += 4
        if market_source and market_source in item_source:
            score += 3
        if variable_name and variable_name in item_name:
            score += 3
        if item_category and item_category in raw_blob:
            score += 1
        if score > 0:
            copy = dict(factor)
            copy["match_score"] = score
            matched.append(copy)
    matched.sort(key=lambda x: x.get("match_score", 0), reverse=True)
    return matched[:limit]
