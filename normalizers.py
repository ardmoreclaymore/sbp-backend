"""Name and category normalization for Hypixel SkyBlock market data."""

from __future__ import annotations

import hashlib
import re
from statistics import median
from typing import Any, Iterable

COLOR_CODE_RE = re.compile(r"§.")
MULTISPACE_RE = re.compile(r"\s+")

# Common reforges/prefixes. This is not perfect, but it prevents the site showing
# Withered Hyperion, Heroic Hyperion, Suspicious Hyperion, etc. as unrelated items.
REFORGE_PREFIXES = {
    "ancient", "necrotic", "loving", "wise", "fierce", "pure", "spiked", "renowned", "giant",
    "perfect", "jaded", "submerged", "mossy", "bustling", "rooted", "warped", "heroic",
    "withered", "fabled", "suspicious", "dirty", "spicy", "sharp", "legendary", "epic",
    "fair", "fast", "gentle", "odd", "rapid", "unreal", "precise", "spiritual", "hasty",
    "heated", "auspicious", "fleet", "mithraic", "refined", "blessed", "moil", "toil",
    "bountiful", "fruitful", "magnetic", "chomp", "salty", "treacherous", "lucky", "stiff",
    "waxed", "fortified", "strengthened", "glistening", "fortuitous", "silky", "bloody",
    "shaded", "itchy", "hurtful", "sighted", "bizarre", "sweet", "strange", "pleasant",
}

RARITY_WORDS = {
    "COMMON", "UNCOMMON", "RARE", "EPIC", "LEGENDARY", "MYTHIC", "DIVINE", "SPECIAL", "VERY SPECIAL", "SUPREME"
}

CATEGORY_KEYWORDS = {
    "slayer": ["reaper", "rev", "revenant", "tara", "tarantula", "sven", "wolf", "voidgloom", "enderman", "eman", "blaze", "demonlord", "riftstalker", "vampire", "maddox"],
    "dungeon": ["wither", "necron", "storm", "maxor", "goldor", "shadow assassin", "livid", "giant", "hyperion", "valkyrie", "scylla", "astraea", "bonzo", "spirit", "adaptive", "catacombs", "f7", "m7", "terminator"],
    "diana": ["griffin", "chimera", "daedalus", "ancient claw", "minos", "shelmet", "crown of greed", "washed-up souvenir", "dwarf turtle", "antique remedies", "crochet tiger", "minotaur"],
    "mining": ["divan", "drill", "gemstone", "mithril", "titanium", "goblin", "sorrow", "glacite", "amber", "jade", "sapphire", "ruby", "amethyst", "topaz", "opal", "jasper", "onyx", "aquamarine", "peridot", "citrine", "fuel", "plasma", "volta", "sludge"],
    "farming": ["wheat", "carrot", "potato", "melon", "pumpkin", "cocoa", "cactus", "mushroom", "nether wart", "cropie", "squash", "fermento", "compost", "pest", "garden", "rancher", "lotus"],
    "fishing": ["shark", "magmafish", "bait", "sea creature", "rod", "fishing", "marina", "trophy", "lava shell", "fish"],
    "kuudra": ["kuudra", "aurora", "terror", "crimson", "fervor", "hollow", "attribute", "mana pool", "mana regen", "veteran", "vitality", "dominance", "lifeline"],
    "rift": ["rift", "vampire", "motif", "timecharm", "bloodbadge", "snake-in-a-boot", "berberis", "living metal"],
    "pet": ["pet", "kat", "shelmet", "pet item", "exp share", "pet skin"],
    "cosmetic": ["skin", "dye", "rune", "hatccessory", "helmet skin", "fire sale", "cape"],
    "accessory": ["artifact", "relic", "talisman", "ring", "accessory", "hegemony", "artifact of control"],
    "fuel": ["hyper catalyst", "catalyst", "plasma bucket", "enchanted lava bucket", "fuel", "hamster wheel", "foul flesh"],
    "npc_flip": ["stock of stonks", "enchanted book", "bits", "booster cookie"],
}


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = COLOR_CODE_RE.sub("", str(value))
    text = text.replace("✪", "").replace("⚚", "")
    text = MULTISPACE_RE.sub(" ", text)
    return text.strip()


def nice_bazaar_name(product_id: str) -> str:
    return clean_text(str(product_id).replace("_", " ").title())


def strip_reforge_prefix(name: str) -> str:
    parts = clean_text(name).split()
    if len(parts) > 1 and parts[0].lower() in REFORGE_PREFIXES:
        return " ".join(parts[1:])
    return clean_text(name)


def normalise_ah_name(name: str) -> str:
    cleaned = clean_text(name)
    cleaned = strip_reforge_prefix(cleaned)
    # Remove common star suffix noise if it appears in copied names.
    cleaned = re.sub(r"\s*\[[^\]]*\]$", "", cleaned).strip()
    return cleaned or "Unknown Item"


def stable_ah_id(item_name: str) -> str:
    norm = normalise_ah_name(item_name).lower()
    digest = hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]
    return f"AH:{digest}"


def safe_float(value: Any, fallback: float = 0.0) -> float:
    try:
        if value is None:
            return fallback
        num = float(value)
        if num != num or num in (float("inf"), float("-inf")):
            return fallback
        return num
    except Exception:
        return fallback


def safe_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return fallback


def pct_change(old: Any, new: Any) -> float:
    old_f = safe_float(old)
    new_f = safe_float(new)
    if old_f <= 0:
        return 0.0
    return ((new_f - old_f) / old_f) * 100.0


def robust_median(values: Iterable[Any]) -> float:
    nums = sorted(safe_float(v) for v in values if safe_float(v) > 0)
    if not nums:
        return 0.0
    return float(median(nums))


def infer_item_tags(name: str, source: str = "") -> list[str]:
    lower = clean_text(name).lower()
    tags: list[str] = []
    for category, words in CATEGORY_KEYWORDS.items():
        if any(word in lower for word in words):
            tags.append(category)
    if source == "bazaar" and not tags:
        tags.append("bazaar_material")
    if source == "auction" and not tags:
        tags.append("auction_general")
    return tags


def infer_market_bucket(name: str, source: str = "") -> str:
    tags = infer_item_tags(name, source)
    priority = ["diana", "slayer", "dungeon", "kuudra", "mining", "farming", "fishing", "rift", "cosmetic", "pet", "accessory", "fuel", "bazaar_material", "auction_general"]
    for tag in priority:
        if tag in tags:
            return tag
    return "general"


def parse_rarity_from_lore(lore: str | None) -> str:
    text = clean_text(lore).upper()
    for rarity in sorted(RARITY_WORDS, key=len, reverse=True):
        if rarity in text:
            return rarity
    return "UNKNOWN"
