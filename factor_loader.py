"""
factor_loader.py

Backend helper for loading prediction factors from Supabase.

Put this file in your sbp-backend repo.
Then predictor.py can call load_prediction_factors(supabase).
"""

def load_prediction_factors(supabase):
    """
    Returns all enabled prediction factors from Supabase.

    Expected table:
    public.prediction_factors
    """
    try:
        response = (
            supabase.table("prediction_factors")
            .select("*")
            .eq("enabled", True)
            .execute()
        )
        return response.data or []
    except Exception as exc:
        print(f"[factor_loader] Could not load prediction factors: {exc}")
        return []


def match_factors_to_item(item, factors):
    """
    Simple first-pass matcher.
    This does not replace your predictor; it gives predictor.py usable matched factors.

    item should be a dict with keys like:
    name, category, source, tags
    """
    item_name = str(item.get("name", "")).lower()
    item_category = str(item.get("category", "")).lower()
    item_tags = " ".join(map(str, item.get("tags") or [])).lower()

    matched = []

    for factor in factors:
        variable_name = str(factor.get("variable_name") or "").lower()
        category = str(factor.get("category") or "").lower()
        item_group = str(factor.get("item_group") or "").lower()
        raw_blob = str(factor.get("raw_data") or "").lower()

        score = 0

        if item_group and item_group in item_name:
            score += 5
        if item_group and item_group in item_tags:
            score += 4
        if category and category in item_category:
            score += 3
        if variable_name and variable_name in item_name:
            score += 3
        if item_category and item_category in raw_blob:
            score += 1

        if score > 0:
            factor_copy = dict(factor)
            factor_copy["match_score"] = score
            matched.append(factor_copy)

    matched.sort(key=lambda x: x.get("match_score", 0), reverse=True)
    return matched[:25]
