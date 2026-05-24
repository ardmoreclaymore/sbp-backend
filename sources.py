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

# Official Hypixel resource endpoint for current mayor/election data.
# Kept here instead of config.py so you only need to replace sources.py.
HYPIXEL_ELECTION_URL = "https://api.hypixel.net/v2/resources/skyblock/election"


def get_json(url, params=None):
    response = requests.get(
        url,
        params=params,
        timeout=REQUEST_TIMEOUT,
        headers={"User-Agent": "SBP/1.0 market collector"},
    )
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


def strip_mc_codes(value):
    if value is None:
        return ""
    return re.sub(r"§.", "", str(value)).strip()


def fetch_bazaar():
    data = get_json(HYPIXEL_BAZAAR_URL)
    return data.get("products", {}) or {}


def fetch_auction_page(page=0):
    return get_json(HYPIXEL_AUCTIONS_URL, params={"page": page})


def _perk_names(perks):
    names = []
    for perk in perks or []:
        if isinstance(perk, dict):
            name = perk.get("name") or perk.get("key") or perk.get("perk")
            if name:
                names.append(strip_mc_codes(name))
        elif perk:
            names.append(strip_mc_codes(perk))
    return [name for name in names if name]


def _safe_candidates(candidates):
    cleaned = []

    for candidate in candidates or []:
        if not isinstance(candidate, dict):
            continue

        perks = _perk_names(candidate.get("perks") or [])
        cleaned.append({
            "name": candidate.get("name") or "Unknown",
            "key": candidate.get("key"),
            "votes": candidate.get("votes") or 0,
            "perks": perks,
        })

    cleaned.sort(key=lambda row: row.get("votes") or 0, reverse=True)
    return cleaned


def _parse_hypixel_election_payload(payload):
    mayor = payload.get("mayor") or {}
    current = payload.get("current") or {}

    # Hypixel has used slightly different shapes over time, so this is defensive.
    current_mayor = mayor.get("name") or current.get("mayor", {}).get("name") or "Unknown mayor"
    current_mayor_key = mayor.get("key") or current.get("mayor", {}).get("key")
    current_perks = _perk_names(mayor.get("perks") or current.get("mayor", {}).get("perks") or [])

    minister = mayor.get("minister") or current.get("minister") or {}
    current_minister = None
    current_minister_key = None
    current_minister_perk = None
    current_minister_perk_description = None

    if isinstance(minister, dict) and minister:
        current_minister = minister.get("name")
        current_minister_key = minister.get("key")

        perk = minister.get("perk") or minister.get("ministerPerk") or {}
        if isinstance(perk, dict):
            current_minister_perk = perk.get("name") or perk.get("key")
            current_minister_perk_description = perk.get("description") or perk.get("desc")
        elif perk:
            current_minister_perk = str(perk)

    election = payload.get("current") or payload.get("election") or {}
    election_year = election.get("year") or payload.get("year")
    election_candidates = _safe_candidates(election.get("candidates") or payload.get("candidates") or [])

    return {
        "current_mayor": current_mayor,
        "current_mayor_key": current_mayor_key,
        "current_perks": current_perks,
        "current_mayor_perks": ", ".join(current_perks),
        "current_minister": current_minister,
        "current_minister_key": current_minister_key,
        "current_minister_perk": current_minister_perk,
        "current_minister_perk_description": current_minister_perk_description,
        "election_year": election_year,
        "election_candidates": election_candidates,
        "source": HYPIXEL_ELECTION_URL,
        "ok": True,
        "raw": payload,
    }


def fetch_current_mayor_context():
    """
    Uses the official Hypixel election resource endpoint.

    Returns mayor + minister data in the column names your v7 frontend/API can read:
    - current_mayor
    - current_mayor_key
    - current_perks
    - current_mayor_perks
    - current_minister
    - current_minister_key
    - current_minister_perk
    - current_minister_perk_description
    - election_year
    - election_candidates
    """
    try:
        payload = get_json(HYPIXEL_ELECTION_URL)
        return _parse_hypixel_election_payload(payload)

    except Exception as exc:
        # Fallback to SkyBlock.Tools only for a rough mayor name, never for minister.
        try:
            html = get_text(SKYBLOCK_TOOLS_ELECTION_URL)
            soup = BeautifulSoup(html, "html.parser")
            text = " ".join(soup.get_text(" ").split())

            mayor = "Mayor source unavailable"
            known = [
                "Aatrox", "Cole", "Diana", "Diaz", "Foxy", "Marina",
                "Paul", "Derpy", "Jerry", "Scorpius", "Finnegan", "Barry"
            ]

            for name in known:
                if name.lower() in text.lower():
                    mayor = name
                    break

            return {
                "current_mayor": mayor,
                "current_mayor_key": None,
                "current_perks": [],
                "current_mayor_perks": "",
                "current_minister": None,
                "current_minister_key": None,
                "current_minister_perk": None,
                "current_minister_perk_description": None,
                "election_year": None,
                "election_candidates": [],
                "source": SKYBLOCK_TOOLS_ELECTION_URL,
                "ok": False,
                "error": f"Hypixel election API failed: {exc}",
            }

        except Exception as fallback_exc:
            return {
                "current_mayor": "Mayor source unavailable",
                "current_mayor_key": None,
                "current_perks": [],
                "current_mayor_perks": "",
                "current_minister": None,
                "current_minister_key": None,
                "current_minister_perk": None,
                "current_minister_perk_description": None,
                "election_year": None,
                "election_candidates": [],
                "source": HYPIXEL_ELECTION_URL,
                "ok": False,
                "error": f"{exc}; fallback failed: {fallback_exc}",
            }


def fetch_meta_context():
    """
    Meta is not an official Hypixel API field.
    This only parses a rough context feed and should not be treated as guaranteed truth.
    """
    try:
        html = get_text(OUTCROCALCULATOR_URL)
        soup = BeautifulSoup(html, "html.parser")
        text = " ".join(soup.get_text(" ").split())

        methods = []
        for word in [
            "farming", "mining", "kuudra", "dungeon", "rift", "slayer",
            "bazaar", "auction", "flip", "forge", "garden"
        ]:
            if word.lower() in text.lower():
                methods.append(word.title())

        methods = list(dict.fromkeys(methods))[:12]
        current_meta = ", ".join(methods) if methods else "Meta source parsed, no methods extracted"

        return {
            "current_meta": current_meta,
            "meta_methods": methods,
            "source": OUTCROCALCULATOR_URL,
            "ok": True,
        }

    except Exception as exc:
        return {
            "current_meta": "Meta source unavailable",
            "meta_methods": [],
            "source": OUTCROCALCULATOR_URL,
            "ok": False,
            "error": str(exc),
        }
