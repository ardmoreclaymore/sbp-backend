"""SBP configuration helpers.

Environment variables are intentionally plain so the same code works on any host.
Do not expose SUPABASE_SERVICE_KEY in frontend code.
"""

from __future__ import annotations

import os

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

# Official Hypixel resources.
HYPIXEL_BAZAAR_URL = os.getenv("HYPIXEL_BAZAAR_URL", "https://api.hypixel.net/v2/skyblock/bazaar")
HYPIXEL_AUCTIONS_URL = os.getenv("HYPIXEL_AUCTIONS_URL", "https://api.hypixel.net/v2/skyblock/auctions")
HYPIXEL_ELECTION_URL = os.getenv("HYPIXEL_ELECTION_URL", "https://api.hypixel.net/v2/resources/skyblock/election")

# User-requested external context sources.
SKYBLOCK_TOOLS_ELECTION_URL = os.getenv("SKYBLOCK_TOOLS_ELECTION_URL", "https://skyblock.tools/election/")
OUTCRO_URL = os.getenv("OUTCRO_URL", "https://outcrocalculator.com/")
COFLNET_API_BASE = os.getenv("COFLNET_API_BASE", "https://sky.coflnet.com/api")

# Collection controls.
MINIMUM_PRICE = int(os.getenv("MINIMUM_PRICE", "0"))  # 0 keeps wheat-level cheap Bazaar products.
AH_MAX_PAGES = os.getenv("AH_MAX_PAGES", "all").strip().lower()  # all, or a number while testing.
SLEEP_BETWEEN_AH_PAGES = float(os.getenv("SLEEP_BETWEEN_AH_PAGES", "0.20"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "45"))
UPSERT_CHUNK_SIZE = int(os.getenv("UPSERT_CHUNK_SIZE", "500"))

# Coflnet is useful, but querying it for every AH item every 5 min is not polite or scalable.
# This limits enrichment to highest-priority AH items. Set 0 to disable.
COFLNET_ENRICH_TOP_N = int(os.getenv("COFLNET_ENRICH_TOP_N", "75"))
COFLNET_PAGE_SIZE = int(os.getenv("COFLNET_PAGE_SIZE", "100"))
COFLNET_PARTNER_TOKEN = os.getenv("COFLNET_PARTNER_TOKEN", "").strip()

# Manual override if a source is temporarily down or if you want to label a meta precisely.
CURRENT_META_OVERRIDE = os.getenv("CURRENT_META_OVERRIDE", "").strip()

# Prediction limits.
MAX_CONFIDENCE_WITHOUT_BACKTEST = float(os.getenv("MAX_CONFIDENCE_WITHOUT_BACKTEST", "86"))
MAX_FORECAST_ABS_PCT = float(os.getenv("MAX_FORECAST_ABS_PCT", "65"))

# Frontend/documentation.
DISCORD_INVITE_URL = os.getenv("DISCORD_INVITE_URL", "https://discord.gg/srDavhPaAw")
PROJECT_NAME = os.getenv("PROJECT_NAME", "SBP SkyBlock Price Predictor")
