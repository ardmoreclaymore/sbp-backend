import re
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
    return get_json(HYPIXEL_AUCTIONS_URL, params={"page":def strip_mc_codes(value):
    return re.sub(r"§.", "", str(value or "")).strip()


def fetch_current_mayor_context():
    """
    Uses Hypixel's official SkyBlock election resource.

    This returns:
    - current mayor name/key/perks
    - current minister name/key/perk/description
    - election year/candidates

    No guessing, no hardcoding in the frontend.
    """
    url = "https://api.hypixel.net/v2/resources/skyblock/election"

    try:
        payload = get_json(url)

        mayor = payload.get("mayor") or {}
        minister = mayor.get("minister") or {}
        minister_perk = minister.get("perk") or {}
        election = mayor.get("election") or {}

        mayor_perks = []
        for perk in mayor.get("perks") or []:
            if isinstance(perk, dict):
                name = strip_mc_codes(perk.get("name"))
                if name:
                    mayor_perks.append(name)

        candidates = []
        for candidate in election.get("candidates") or []:
            candidates.append({
                "key": candidate.get("key"),
                "name": candidate.get("name"),
                "votes": candidate.get("votes"),
                "perks": [
                    {
                        "name": strip_mc_codes(p.get("name")),
                        "description": strip_mc_codes(p.get("description")),
                        "minister": bool(p.get("minister")),
                    }
                    for p in candidate.get("perks") or []
                    if isinstance(p, dict)
                ],
            })

        return {
            "current_mayor": mayor.get("name") or "Unknown mayor",
            "current_mayor_key": mayor.get("key"),
            "current_mayor_perks": mayor_perks,
            "current_minister": minister.get("name"),
            "current_minister_key": minister.get("key"),
            "current_minister_perk": strip_mc_codes(minister_perk.get("name")),
            "current_minister_perk_description": strip_mc_codes(minister_perk.get("description")),
            "election_year": election.get("year"),
            "election_candidates": candidates,
            "source": url,
            "ok": bool(payload.get("success", True)),
        }

    except Exception as exc:
        return {
            "current_mayor": "Mayor source unavailable",
            "current_mayor_key": None,
            "current_mayor_perks": [],
            "current_minister": None,
            "current_minister_key": None,
            "current_minister_perk": None,
            "current_minister_perk_description": None,
            "election_year": None,
            "election_candidates": [],
            "source": url,
            "ok": False,
            "error": str(exc),
        }str(exc)}


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
