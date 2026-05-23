"""External source collectors for SBP.

The collector uses official Hypixel endpoints for complete BZ/AH coverage, then
adds user-requested context sources where they are safe to use. Coflnet is used
as optional enrichment rather than 20k-per-run scraping.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any

import requests
from bs4 import BeautifulSoup

from config import (
    COFLNET_API_BASE,
    COFLNET_PAGE_SIZE,
    COFLNET_PARTNER_TOKEN,
    CURRENT_META_OVERRIDE,
    HYPIXEL_AUCTIONS_URL,
    HYPIXEL_BAZAAR_URL,
    HYPIXEL_ELECTION_URL,
    OUTCRO_URL,
    REQUEST_TIMEOUT,
    SKYBLOCK_TOOLS_ELECTION_URL,
)
from normalizers import clean_text, safe_float, safe_int


@dataclass
class SourceStatus:
    name: str
    url: str
    status: str
    message: str
    updated_at: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_json(url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> dict[str, Any] | list[Any]:
    response = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
    if response.status_code == 429:
        raise RuntimeError(f"Rate limited by {url}. Slow the schedule, cache more, or reduce enrichment.")
    response.raise_for_status()
    return response.json()


def get_text(url: str) -> str:
    headers = {
        "User-Agent": "SBP market context crawler; respectful 5-minute cache; contact via website owner"
    }
    response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    if response.status_code == 429:
        raise RuntimeError(f"Rate limited by {url}.")
    response.raise_for_status()
    return response.text


def fetch_hypixel_bazaar() -> dict[str, Any]:
    payload = get_json(HYPIXEL_BAZAAR_URL)
    if not isinstance(payload, dict) or not payload.get("success"):
        raise RuntimeError("Hypixel Bazaar API did not return success=true")
    return payload


def fetch_hypixel_auction_pages(max_pages: str = "all", sleep_between_pages: float = 0.20) -> list[dict[str, Any]]:
    first = get_json(HYPIXEL_AUCTIONS_URL, {"page": 0})
    if not isinstance(first, dict) or not first.get("success"):
        raise RuntimeError("Hypixel Auction API did not return success=true")
    total_pages = safe_int(first.get("totalPages"), 1)
    if max_pages != "all":
        total_pages = min(total_pages, max(1, safe_int(max_pages, 1)))

    auctions: list[dict[str, Any]] = []
    for page in range(total_pages):
        payload = first if page == 0 else get_json(HYPIXEL_AUCTIONS_URL, {"page": page})
        if not isinstance(payload, dict):
            continue
        auctions.extend(payload.get("auctions", []) or [])
        if page + 1 < total_pages:
            time.sleep(sleep_between_pages)
    return auctions


def fetch_hypixel_election() -> dict[str, Any]:
    payload = get_json(HYPIXEL_ELECTION_URL)
    if not isinstance(payload, dict):
        raise RuntimeError("Hypixel election response was not a JSON object")
    return payload


def parse_hypixel_election(payload: dict[str, Any]) -> dict[str, Any]:
    mayor = payload.get("mayor") or {}
    current_name = mayor.get("name") or "Unknown"
    current_perks = []
    for perk in mayor.get("perks") or []:
        if isinstance(perk, dict):
            current_perks.append(perk.get("name") or "")
        else:
            current_perks.append(str(perk))
    current_perks = [clean_text(p) for p in current_perks if clean_text(p)]

    election = payload.get("current") or payload.get("currentElection") or {}
    candidates = []
    for cand in election.get("candidates") or []:
        perks = []
        for perk in cand.get("perks") or []:
            perks.append(clean_text(perk.get("name") if isinstance(perk, dict) else perk))
        candidates.append({
            "name": clean_text(cand.get("name")),
            "votes": safe_int(cand.get("votes")),
            "perks": [p for p in perks if p],
        })
    candidates.sort(key=lambda x: x.get("votes", 0), reverse=True)

    return {
        "current_mayor": current_name,
        "current_perks": current_perks,
        "candidates": candidates,
        "raw_source": "Hypixel election API",
    }


def fetch_skyblock_tools_election() -> dict[str, Any]:
    html = get_text(SKYBLOCK_TOOLS_ELECTION_URL)
    soup = BeautifulSoup(html, "html.parser")
    text_lines = [clean_text(line) for line in soup.get_text("\n").splitlines() if clean_text(line)]

    current_mayor = "Unknown"
    candidates: list[dict[str, Any]] = []
    perks: list[str] = []
    for i, line in enumerate(text_lines):
        if line == "Currently Elected Mayor":
            # Usually lines after current perks contain the mayor name.
            for later in text_lines[i + 1:i + 18]:
                if re.fullmatch(r"[A-Za-z ]+", later) and later not in {"Perks", "Ongoing Election"}:
                    current_mayor = later
        m = re.match(r"^([A-Za-z ]+) \(([0-9,]+) votes\)$", line)
        if m:
            candidates.append({"name": clean_text(m.group(1)), "votes": safe_int(m.group(2).replace(",", "")), "perks": []})
        if line not in {"Perks", "Currently Elected Mayor"} and len(line) < 60:
            if any(keyword in line.lower() for keyword in ["ritual", "slayer", "mining", "fishing", "forge", "dungeon", "spree", "exchange", "trading"]):
                perks.append(line)

    candidates.sort(key=lambda x: x.get("votes", 0), reverse=True)
    return {
        "current_mayor": current_mayor,
        "current_perks": perks[:8],
        "candidates": candidates[:10],
        "raw_source": "SkyBlock.Tools election page",
    }


def fetch_current_mayor_context() -> tuple[dict[str, Any], SourceStatus]:
    now = utc_now()
    try:
        hypixel = parse_hypixel_election(fetch_hypixel_election())
        if hypixel.get("current_mayor") and hypixel["current_mayor"] != "Unknown":
            return hypixel, SourceStatus("Hypixel election", HYPIXEL_ELECTION_URL, "ok", "Used official election API", now)
    except Exception as exc:
        hypixel_error = str(exc)
    else:
        hypixel_error = "No usable official election payload"

    try:
        tools = fetch_skyblock_tools_election()
        return tools, SourceStatus("SkyBlock.Tools election", SKYBLOCK_TOOLS_ELECTION_URL, "fallback_ok", f"Official API failed: {hypixel_error}", now)
    except Exception as exc:
        return {
            "current_mayor": "Unknown",
            "current_perks": [],
            "candidates": [],
            "raw_source": "none",
        }, SourceStatus("Election", SKYBLOCK_TOOLS_ELECTION_URL, "error", f"Hypixel: {hypixel_error}; SkyBlock.Tools: {exc}", now)


def fetch_outcro_meta_methods(limit: int = 30) -> tuple[list[dict[str, Any]], SourceStatus]:
    now = utc_now()
    if CURRENT_META_OVERRIDE:
        return [{"name": CURRENT_META_OVERRIDE, "profit_per_hour": None, "source": "manual override"}], SourceStatus("Current metas", "manual", "override", "Used CURRENT_META_OVERRIDE", now)
    try:
        html = get_text(OUTCRO_URL)
        soup = BeautifulSoup(html, "html.parser")
        lines = [clean_text(x) for x in soup.get_text("\n").splitlines() if clean_text(x)]
        methods: list[dict[str, Any]] = []
        # The public page exposes method names and profit strings in text. Parse conservatively.
        for line in lines:
            if len(methods) >= limit:
                break
            if "Calculator defaults" in line or re.search(r"\b\d+(?:\.\d+)?[MBK]\b", line):
                name = line.replace("Calculator defaults", "").replace("Loading default inputs", "")
                name = re.sub(r"\s+\|.*$", "", name).strip()
                if name and not any(m["name"] == name for m in methods):
                    m = re.search(r"(\d+(?:\.\d+)?)\s*([KMB])", name)
                    profit = None
                    if m:
                        mult = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[m.group(2)]
                        profit = safe_float(m.group(1)) * mult
                    methods.append({"name": name[:160], "profit_per_hour": profit, "source": OUTCRO_URL})
        status = "ok" if methods else "empty"
        return methods, SourceStatus("OutcroCalculator", OUTCRO_URL, status, f"Parsed {len(methods)} visible meta/MMM methods", now)
    except Exception as exc:
        return [], SourceStatus("OutcroCalculator", OUTCRO_URL, "error", str(exc), now)


def coflnet_headers() -> dict[str, str]:
    headers = {"User-Agent": "SBP market enrichment; cached; low-volume"}
    if COFLNET_PARTNER_TOKEN:
        headers["Authorization"] = f"Bearer {COFLNET_PARTNER_TOKEN}"
    return headers


def fetch_coflnet_item_analysis(item_tag: str, days: int = 7) -> dict[str, Any] | None:
    """Return Coflnet analysis for one item tag if available.

    The public free tier supports 1-7 days according to Coflnet docs. Higher windows may need premium.
    """
    if not item_tag:
        return None
    url = f"{COFLNET_API_BASE}/item/price/{item_tag}/analysis"
    try:
        payload = get_json(url, {"days": max(1, min(7, int(days)))}, headers=coflnet_headers())
        if isinstance(payload, dict):
            return payload
    except Exception:
        return None
    return None


def fetch_coflnet_sold(item_tag: str, page_size: int | None = None) -> list[dict[str, Any]]:
    if not item_tag:
        return []
    params: dict[str, Any] = {"page": 0, "pageSize": page_size or COFLNET_PAGE_SIZE}
    if COFLNET_PARTNER_TOKEN:
        params["token"] = COFLNET_PARTNER_TOKEN
    try:
        payload = get_json(f"{COFLNET_API_BASE}/auctions/tag/{item_tag}/sold", params=params, headers=coflnet_headers())
        if isinstance(payload, list):
            return [x for x in payload if isinstance(x, dict)]
    except Exception:
        return []
    return []


def source_status_row(status: SourceStatus) -> dict[str, Any]:
    row = asdict(status)
    row["id"] = status.name.lower().replace(" ", "_")[:64]
    return row
