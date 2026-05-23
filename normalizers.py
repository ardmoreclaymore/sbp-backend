import re
import math


def safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        if isinstance(value, float) and math.isnan(value):
            return default
        return float(value)
    except Exception:
        return default


def safe_int(value, default=0):
    try:
        if value is None:
            return default
        return int(float(value))
    except Exception:
        return default


def clean_name(value):
    value = str(value or "").strip()
    value = re.sub(r"§.", "", value)
    value = re.sub(r"\s+", " ", value)
    return value


def slug(value):
    value = clean_name(value).upper()
    value = re.sub(r"[^A-Z0-9]+", "_", value)
    value = value.strip("_")
    return value or "UNKNOWN"


def ah_item_id(name):
    return f"AH_{slug(name)}"


def bz_name(product_id):
    return clean_name(product_id.replace("_", " ").title())


def pct_change(old, new):
    old = safe_float(old)
    new = safe_float(new)
    if old <= 0:
        return 0.0
    return ((new - old) / old) * 100.0


def spread_pct(buy_price, sell_price):
    buy = safe_float(buy_price)
    sell = safe_float(sell_price)
    if buy <= 0 or sell <= 0:
        return 0.0
    mid = (buy + sell) / 2
    if mid <= 0:
        return 0.0
    return abs(sell - buy) / mid * 100.0


def category_guess(name):
    n = clean_name(name).lower()
    rules = [
        ("ENCHANTMENT", ["enchantment", "ultimate", "book"]),
        ("PET", [" pet", "griffin", "dragon pet", "tiger", "sheep", "gdrag", "edrag"]),
        ("DUNGEON", ["necron", "storm", "maxor", "goldor", "shadow assassin", "hyperion", "terminator", "wither"]),
        ("SLAYER", ["reaper", "atomsplit", "voidgloom", "warden", "tarantula", "revenant", "sven", "inferno"]),
        ("MINING", ["gemstone", "drill", "divan", "titanium", "mithril", "fuel", "amber", "jade", "sapphire", "ruby"]),
        ("FARMING", ["wheat", "carrot", "potato", "melon", "pumpkin", "mushroom", "cocoa", "cactus", "crop"]),
        ("FISHING", ["shark", "rod", "bait", "fish", "squid", "sea creature"]),
        ("KUUDRA", ["aurora", "terror", "crimson", "fervor", "attribute", "kuudra", "mandible"]),
        ("COSMETIC", ["skin", "dye", "helmet skin", "rune", "cloak"]),
    ]
    for category, needles in rules:
        if any(x in n for x in needles):
            return category
    return "GENERAL"
