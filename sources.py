import requests
from bs4 import BeautifulSoup

from config import (
    REQUEST_TIMEOUT,
    HYPIXEL_BAZAAR_URL,
    HYPIXEL_AUCTIONS_URL,
    SKYBLOCK_TOOLS_ELECTION_URL,
    OUTCROCALCULATOR_URL,
)


def get_json(url, params=None):
    response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


def get_text(url):
    response = requests.get(
        url,
        timeout=REQUEST_TIMEOUT,
        headers={"User-Agent": "SBP/1.0 market context parser"},
    )
    response.raise_for_status()
    return response.text


def fetch_bazaar():
    data = get_json(HYPIXEL_BAZAAR_URL)
    return data.get("products", {}) or {}


def fetch_auction_page(page=0):
    return get_json(HYPIXEL_AUCTIONS_URL, params={"page": page})


def fetch_current_mayor_context():
    try:
        html = get_text(SKYBLOCK_TOOLS_ELECTION_URL)
        soup = BeautifulSoup(html, "html.parser")
        text = " ".join(soup.get_text(" ").split())
        mayor = "Loading mayor data"
        known = ["Aatrox", "Cole", "Diana", "Diaz", "Foxy", "Marina", "Paul", "Derpy", "Jerry", "Scorpius", "Finnegan", "Barry"]
        for name in known:
            if name.lower() in text.lower():
                mayor = name
                break
        return {"current_mayor": mayor, "current_perks": [], "election_candidates": [], "source": SKYBLOCK_TOOLS_ELECTION_URL, "ok": True}
    except Exception as exc:
        return {"current_mayor": "Mayor source unavailable", "current_perks": [], "election_candidates": [], "source": SKYBLOCK_TOOLS_ELECTION_URL, "ok": False, "error": str(exc)}


def fetch_meta_context():
    try:
        html = get_text(OUTCROCALCULATOR_URL)
        soup = BeautifulSoup(html, "html.parser")
        text = " ".join(soup.get_text(" ").split())
        methods = []
        for word in ["farming", "mining", "kuudra", "dungeon", "rift", "slayer", "bazaar", "auction", "flip", "forge", "garden"]:
            if word.lower() in text.lower():
                methods.append(word.title())
        methods = list(dict.fromkeys(methods))[:12]
        current_meta = ", ".join(methods) if methods else "Meta source parsed, no methods extracted"
        return {"current_meta": current_meta, "meta_methods": methods, "source": OUTCROCALCULATOR_URL, "ok": True}
    except Exception as exc:
        return {"current_meta": "Meta source unavailable", "meta_methods": [], "source": OUTCROCALCULATOR_URL, "ok": False, "error": str(exc)}
