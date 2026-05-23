import os

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = (
    os.getenv("SUPABASE_SERVICE_KEY")
    or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    or os.getenv("SUPABASE_KEY")
)

PROJECT_NAME = "SBP SkyBlock Price Predictor"
VERSION = "backend-clean-v7-ah-bz"

HYPIXEL_BAZAAR_URL = "https://api.hypixel.net/v2/skyblock/bazaar"
HYPIXEL_AUCTIONS_URL = "https://api.hypixel.net/v2/skyblock/auctions"
SKYBLOCK_TOOLS_ELECTION_URL = "https://skyblock.tools/election/"
OUTCROCALCULATOR_URL = "https://outcrocalculator.com/"

REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "25"))
MINIMUM_PRICE = float(os.getenv("MINIMUM_PRICE", "0"))
AH_MAX_PAGES = os.getenv("AH_MAX_PAGES", "all")
SNAPSHOT_KEEP_DAYS = int(os.getenv("SNAPSHOT_KEEP_DAYS", "14"))
SEARCH_LIMIT = int(os.getenv("SEARCH_LIMIT", "50"))
TOP_LIMIT = int(os.getenv("TOP_LIMIT", "20"))
ITEM_HISTORY_LIMIT = int(os.getenv("ITEM_HISTORY_LIMIT", "120"))
