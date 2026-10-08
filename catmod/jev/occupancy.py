"""Standardized catastrophe occupancy / vulnerability codes.

Messy broker strings ("whse", "steel-shed", "storage") collapse onto HAZUS-like codes.
"""

from __future__ import annotations

import re

from catmod.jev.primitives import choice_answer
from catmod.schemas import ChoiceAnswer

OCCUPANCY_CRITERIA: dict[str, str] = {
    "RES_SF": "Single-family dwelling, house, home, SFD, residential bungalow.",
    "informal_iron_sheet": "Informal dwelling, mabati, iron sheet, corrugated sheet house.",
    "semi_permanent": "Semi-permanent dwelling, timber frame with masonry infill, wattle and daub.",
    "permanent_masonry": "Permanent masonry house, stone or brick dwelling, burned brick.",
    "concrete_rcc": "Reinforced-concrete frame, RCC, concrete multi-storey.",
    "RES_MF": "Multi-family, apartment, condo, flats, tenement.",
    "COM_RET": "Retail shop, store, mall, supermarket.",
    "COM_OFF": "Office, office tower, professional building.",
    "COM_WHSE": "Warehouse, whse, steel-shed, storage, depot, distribution center, godown.",
    "COM_HOT": "Hotel, motel, inn, resort.",
    "IND_HVY": "Heavy industrial, plant, refinery, mill, foundry.",
    "IND_LGT": "Light industrial, workshop, light manufacturing.",
    "AGR": "Agricultural, barn, farm, greenhouse, silo.",
    "EDU": "School, university, campus, education.",
    "HEA": "Hospital, clinic, healthcare, medical.",
    "REL": "Church, mosque, temple, religious.",
    "GOV": "Government, municipal, courthouse, fire station.",
    "MIX": "Mixed use, live-work.",
    "UNK": "Unknown, blank, unstructured, cannot classify.",
}

_ALIASES: dict[str, str] = {
    "whse": "COM_WHSE",
    "whs": "COM_WHSE",
    "warehouse": "COM_WHSE",
    "warehouses": "COM_WHSE",
    "warehousing": "COM_WHSE",
    "steel-shed": "COM_WHSE",
    "steelshed": "COM_WHSE",
    "steel shed": "COM_WHSE",
    "shed": "COM_WHSE",
    "storage": "COM_WHSE",
    "storehouse": "COM_WHSE",
    "depot": "COM_WHSE",
    "godown": "COM_WHSE",
    "distribution": "COM_WHSE",
    "dc": "COM_WHSE",
    "logistics": "COM_WHSE",
    "cold storage": "COM_WHSE",
    "sfd": "RES_SF",
    "sfh": "RES_SF",
    "single family": "RES_SF",
    "single-family": "RES_SF",
    "dwelling": "RES_SF",
    "house": "RES_SF",
    "home": "RES_SF",
    "residential": "RES_SF",
    "res": "RES_SF",
    "bungalow": "RES_SF",
    "informal iron sheet": "informal_iron_sheet",
    "iron sheet": "informal_iron_sheet",
    "mabati": "informal_iron_sheet",
    "informal": "informal_iron_sheet",
    "semi permanent": "semi_permanent",
    "semi-permanent": "semi_permanent",
    "semipermanent": "semi_permanent",
    "permanent masonry": "permanent_masonry",
    "masonry": "permanent_masonry",
    "burned brick": "permanent_masonry",
    "concrete rcc": "concrete_rcc",
    "rcc": "concrete_rcc",
    "reinforced concrete": "concrete_rcc",
    "apartment": "RES_MF",
    "apt": "RES_MF",
    "condo": "RES_MF",
    "condominium": "RES_MF",
    "multi-family": "RES_MF",
    "multifamily": "RES_MF",
    "flats": "RES_MF",
    "retail": "COM_RET",
    "shop": "COM_RET",
    "store": "COM_RET",
    "mall": "COM_RET",
    "supermarket": "COM_RET",
    "office": "COM_OFF",
    "offices": "COM_OFF",
    "office tower": "COM_OFF",
    "office-tower": "COM_OFF",
    "hotel": "COM_HOT",
    "motel": "COM_HOT",
    "inn": "COM_HOT",
    "resort": "COM_HOT",
    "industrial": "IND_HVY",
    "plant": "IND_HVY",
    "refinery": "IND_HVY",
    "mill": "IND_HVY",
    "foundry": "IND_HVY",
    "factory": "IND_LGT",
    "workshop": "IND_LGT",
    "light industrial": "IND_LGT",
    "farm": "AGR",
    "barn": "AGR",
    "agriculture": "AGR",
    "agricultural": "AGR",
    "greenhouse": "AGR",
    "school": "EDU",
    "university": "EDU",
    "campus": "EDU",
    "hospital": "HEA",
    "clinic": "HEA",
    "healthcare": "HEA",
    "church": "REL",
    "mosque": "REL",
    "temple": "REL",
    "government": "GOV",
    "municipal": "GOV",
    "mixed": "MIX",
    "unknown": "UNK",
    "unstructured_pdf": "UNK",
}

_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")


def _normalize(text: str) -> str:
    return _TOKEN_SPLIT.sub(" ", (text or "").lower()).strip()


def classify_occupancy(raw: str) -> ChoiceAnswer:
    """Single-pass, non-autoregressive occupancy Choice."""
    norm = _normalize(raw)
    logits = {code: -4.0 for code in OCCUPANCY_CRITERIA}
    logits["UNK"] = -0.5 if not norm else -2.5

    if norm in _ALIASES:
        logits[_ALIASES[norm]] = 12.0
    if norm.replace(" ", "-") in _ALIASES:
        logits[_ALIASES[norm.replace(" ", "-")]] = 12.0

    for alias, code in _ALIASES.items():
        if alias == norm:
            continue
        if alias in norm or (len(alias) >= 4 and alias in f" {norm} "):
            logits[code] = max(logits[code], 6.0 + min(len(alias), 8) * 0.25)

    tokens = set(norm.split())
    keyword_boosts = {
        "COM_WHSE": {"whse", "warehouse", "storage", "shed", "depot", "logistics", "godown"},
        "RES_SF": {"house", "home", "dwelling", "sfd", "residential"},
        "informal_iron_sheet": {"mabati", "informal"},
        "semi_permanent": {"semi", "wattle"},
        "permanent_masonry": {"masonry", "brick"},
        "concrete_rcc": {"rcc", "reinforced"},
        "RES_MF": {"apartment", "condo", "flats", "multifamily"},
        "COM_OFF": {"office", "tower"},
        "COM_RET": {"retail", "shop", "mall", "store"},
        "COM_HOT": {"hotel", "motel", "resort"},
        "IND_HVY": {"plant", "refinery", "mill", "heavy"},
        "IND_LGT": {"workshop", "factory", "light"},
        "AGR": {"farm", "barn", "ag", "silo"},
        "EDU": {"school", "university", "campus"},
        "HEA": {"hospital", "clinic", "medical"},
        "GOV": {"government", "municipal", "courthouse"},
    }
    for code, words in keyword_boosts.items():
        hit = len(tokens & words)
        if hit:
            logits[code] = max(logits[code], 3.5 * hit)

    return choice_answer(OCCUPANCY_CRITERIA, logits)  # type: ignore[arg-type]
