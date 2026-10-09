"""Gemini RAG over uploaded portfolios.

Answers come from dataset context only. Treaty payouts stay in the decimal
waterfall and are not computed here.
"""

from __future__ import annotations

import csv
import io
import json
import re
from collections import Counter
from typing import Any

import httpx

from catmod.config import Settings, get_settings
from catmod.ingestion.parser import canonicalize_record

GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
MODEL_NAME = "gemini-3.8-flash"
MODEL_FALLBACKS = ("gemini-3.8-flash", "gemini-2.5-flash")

OPENROUTER_MODEL = "openai/gpt-4.1-nano"
OPENROUTER_FALLBACKS = ("openai/gpt-4o-mini", "meta-llama/llama-3.3-70b-instruct")
OPENROUTER_CHAT_PATH = "/chat/completions"

SYSTEM_PROMPT = (
    "You are an expert catastrophe reinsurance analyst assistant for CatMod. "
    "You are provided with structured context from uploaded portfolio datasets. "
    "Answer the user's natural language question accurately based ONLY on the provided dataset context. "
    "Write complete sentences, the way you would speak the answer aloud. "
    "Do not answer with telegraphic labels, colon lists, or shortened cues. "
    "If filtering rows, return structured matching asset IDs alongside a clear text answer. "
    "Do not calculate treaty payouts, cedant retention, or reinstatement premium. "
    "Those contractual amounts belong to the deterministic waterfall and are outside this answer. "
    "When the question already states those contractual figures, quote them in sentences and do not recompute them."
)

_PAYOUT_KEYS = {
    "allocated_reinsurer_payout",
    "allocated_cedant_retention",
    "covered_loss",
    "reinsurer_payout",
    "cedant_retained_loss",
    "reinstatement_premium_due",
    "layer_loss",
    "exhaustion_ratio",
}

_GREET = {"hello", "hi", "hey", "thanks", "thank", "help", "ok", "okay"}

_STOP = {
    "which",
    "what",
    "where",
    "who",
    "are",
    "the",
    "and",
    "for",
    "with",
    "have",
    "has",
    "from",
    "that",
    "this",
    "into",
    "over",
    "above",
    "under",
    "than",
    "their",
    "there",
    "about",
    "show",
    "list",
    "please",
    "properties",
    "property",
    "assets",
    "asset",
    "portfolio",
    "dataset",
    "summarize",
    "summary",
    "total",
    "exposed",
    "exposure",
    "corridor",
}

_DEPTH_RE = re.compile(
    r"(?:depth|flood).{0,40}?(?:over|above|greater than|>)\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


def parse_csv_text(text: str) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(text or ""))
    rows: list[dict[str, Any]] = []
    for raw in reader:
        if not raw or not any(str(value or "").strip() for value in raw.values()):
            continue
        rows.append(
            canonicalize_record(
                {
                    str(key or "").strip(): _coerce_cell(value)
                    for key, value in raw.items()
                    if key
                }
            )
        )
    return rows


def rows_from_claims(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        row = {key: value for key, value in claim.items() if key not in _PAYOUT_KEYS}
        kept.append(row)
    return kept


def build_dataset_context(
    rows: list[dict[str, Any]],
    *,
    name: str,
    event_id: str | None = None,
) -> dict[str, Any]:
    clean = [_public_row(row) for row in rows]
    return {
        "name": name,
        "event_id": event_id,
        "row_count": len(clean),
        "columns": _columns(clean),
        "summary_stats": _summary(clean),
        "sample_rows": clean[:5],
        "rows": clean,
    }


def _model_chain(settings: Settings) -> list[str]:
    primary = (
        getattr(settings, "gemini_model", None) or MODEL_NAME
    ).strip() or MODEL_NAME
    chain: list[str] = []
    for name in (primary, *MODEL_FALLBACKS):
        if name and name not in chain:
            chain.append(name)
    return chain


def _openrouter_chain(settings: Settings) -> list[str]:
    primary = (
        getattr(settings, "openrouter_model", None) or OPENROUTER_MODEL
    ).strip() or OPENROUTER_MODEL
    extra = getattr(settings, "openrouter_fallbacks", None) or ""
    configured = [name.strip() for name in str(extra).split(",") if name.strip()]
    chain: list[str] = []
    for name in (primary, *configured, *OPENROUTER_FALLBACKS):
        if name and name not in chain:
            chain.append(name)
    return chain


def query_dataset_rag(
    query: str,
    dataset_context: dict[str, Any],
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    question = (query or "").strip()
    if not question:
        return _pack(
            "Ask a question about the portfolio.",
            [],
            _summary([]),
            0.0,
            "local-keyword",
        )
    gemini_key = (getattr(settings, "gemini_api_key", None) or "").strip()
    openrouter_key = (getattr(settings, "openrouter_api_key", None) or "").strip()
    if gemini_key:
        result = _answer_with_gemini(question, dataset_context, gemini_key, settings)
        if result is not None:
            return result
    if openrouter_key:
        result = _answer_with_openrouter(
            question, dataset_context, openrouter_key, settings
        )
        if result is not None:
            return result
    return _local_fallback(question, dataset_context)


def _answer_with_gemini(
    question: str,
    dataset_context: dict[str, Any],
    key: str,
    settings: Settings,
) -> dict[str, Any] | None:
    for model in _model_chain(settings):
        try:
            parsed = _ask_gemini(question, dataset_context, key, model)
        except httpx.HTTPStatusError:
            continue
        except Exception:
            return None
        return _from_model(parsed, dataset_context, f"gemini:{model}")
    return None


def _answer_with_openrouter(
    question: str,
    dataset_context: dict[str, Any],
    key: str,
    settings: Settings,
) -> dict[str, Any] | None:
    base_url = (
        getattr(settings, "openrouter_base_url", None) or "https://openrouter.ai/api/v1"
    ).strip() or "https://openrouter.ai/api/v1"
    timeout = float(getattr(settings, "openrouter_timeout_s", 45.0) or 45.0)
    for model in _openrouter_chain(settings):
        try:
            parsed = _ask_openrouter(
                question,
                dataset_context,
                key,
                model,
                base_url=base_url,
                timeout=timeout,
            )
        except httpx.HTTPStatusError:
            continue
        except Exception:
            continue
        return _from_model(parsed, dataset_context, f"openrouter:{model}")
    return None


SUMMARY_QUESTION = (
    "Write the opening summary of this uploaded dataset in complete natural-language sentences. "
    "Use at least two sentences, spoken as an analyst would say them aloud. "
    "Do not use telegraphic labels, colon lists, or shortened cues such as 'Total TIV is' or 'Occupancy mix:'. "
    "Name the dataset, say how many rows it contains, describe the fields that are actually present, "
    "and describe where the assets sit when coordinates are present. "
    "If insured value or occupancy is missing from the columns, say that in a sentence instead of reporting zero. "
    "Do not calculate treaty payouts, cedant retention, or reinstatement premium."
)


def summarize_dataset(
    dataset_context: dict[str, Any],
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Portfolio summary through Gemini. Jev is not on this path."""
    return query_dataset_rag(SUMMARY_QUESTION, dataset_context, settings)


BRIEFING_QUESTION = (
    "Write a short plain-English risk briefing for an underwriter, using ONLY the "
    "statistics, EP curve, and largest losses in the context. "
    "Open with the book size and the contractual figures (ground-up loss, reinsurer payout, "
    "cedant retention, expected annual loss). "
    "Then describe the EP curve across its return periods. "
    "Then name the largest losses and what drives them, naming occupancy and flood depth. "
    "Quote the contractual amounts exactly as given; do not recompute treaty payouts, "
    "cedant retention, or reinstatement premium. "
    "Finish with one clear underwriting recommendation. "
    "Use complete sentences a person could read aloud, no bullet lists, no telegraphic labels."
)

_BRIEFING_TOP_LOSSES = 10


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _top_losses(
    claims: list[dict[str, Any]], limit: int = _BRIEFING_TOP_LOSSES
) -> list[dict[str, Any]]:
    ranked: list[tuple[float, dict[str, Any]]] = []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        loss = claim.get("modeled_ground_up_loss")
        if loss in (None, ""):
            loss = claim.get("ground_up_loss")
        ranked.append((_float(loss), claim))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    losses: list[dict[str, Any]] = []
    for loss, claim in ranked[:limit]:
        losses.append(
            {
                "asset_id": claim.get("asset_id"),
                "occupancy": claim.get("occupancy")
                or claim.get("occupancy_raw")
                or "Unknown",
                "tiv": _float(claim.get("tiv")),
                "flood_depth_m": claim.get("flood_depth_m"),
                "damage_ratio": _float(claim.get("damage_ratio")),
                "loss": loss,
            }
        )
    return losses


def build_briefing_context(job: dict[str, Any]) -> dict[str, Any]:
    """Compact model output for the LLM: statistics + EP curve + largest losses."""
    job = job or {}
    ep = job.get("ep_curve") or {}
    treaty = job.get("treaty") or {}
    placeholders = job.get("placeholders") or {}
    curve: list[dict[str, Any]] = []
    for point in ep.get("curve") or []:
        if not isinstance(point, dict):
            continue
        loss = point.get("loss_float")
        if loss is None:
            loss = point.get("loss")
        curve.append(
            {
                "return_period": point.get("return_period"),
                "loss": _float(loss),
                "exceedance_probability": point.get(
                    "exceedance_probability_float", point.get("exceedance_probability")
                ),
            }
        )
    statistics = {
        "event_id": placeholders.get("EVENT_ID") or job.get("event_id"),
        "hazard_region": placeholders.get("HAZARD_REGION") or job.get("hazard_region"),
        "claim_count": job.get("claim_count"),
        "total_gross_claim": _float(
            placeholders.get("GROUND_UP_LOSS", job.get("total_gross_claim"))
        ),
        "reinsurer_payout": _float(
            placeholders.get("REINSURER_PAYOUT", job.get("reinsurer_payout"))
        ),
        "cedant_retained_loss": _float(
            placeholders.get("CEDANT_RETENTION", job.get("cedant_retained_loss"))
        ),
        "reinstatement_premium_due": _float(job.get("reinstatement_premium_due")),
        "layer_loss": _float(job.get("layer_loss")),
        "exhaustion_ratio": _float(job.get("exhaustion_ratio")),
        "modeled_ground_up_loss": _float(
            placeholders.get(
                "MODELED_GROUND_UP_LOSS", job.get("modeled_ground_up_loss")
            )
        ),
        "expected_annual_loss": _float(
            placeholders.get("EXPECTED_ANNUAL_LOSS", ep.get("eal"))
        ),
        "flagged_count": int(_float(job.get("flagged_count"))),
        "tvar_pml": job.get("tvar_pml") or {},
        "treaty": {
            "label": treaty.get("label") or job.get("treaty_label"),
            "attachment_point": treaty.get("attachment_point"),
            "limit": treaty.get("limit"),
            "co_participation": treaty.get("co_participation"),
        },
        "synthetic": job.get("synthetic") or {},
    }
    return {
        "event_id": statistics["event_id"],
        "statistics": statistics,
        "ep_curve": {
            "eal": statistics["expected_annual_loss"],
            "curve": curve,
        },
        "largest_losses": _top_losses(list(job.get("claims") or [])),
    }


def _briefing_prompt(packet: dict[str, Any]) -> str:
    return (
        "Modeled catastrophe book output (JSON):\n"
        + json.dumps(packet, default=str)
        + "\n\n"
        + BRIEFING_QUESTION
        + "\n\nReturn JSON with keys answer, confidence."
    )


def _provider_answer(user_text: str, settings: Settings) -> tuple[str, str] | None:
    gemini_key = (getattr(settings, "gemini_api_key", None) or "").strip()
    if gemini_key:
        for model in _model_chain(settings):
            try:
                parsed = _post_gemini(user_text, gemini_key, model)
            except httpx.HTTPStatusError:
                continue
            except Exception:
                break
            answer = str(parsed.get("answer") or "").strip()
            if answer:
                return answer, f"gemini:{model}"
    openrouter_key = (getattr(settings, "openrouter_api_key", None) or "").strip()
    if openrouter_key:
        base_url = (
            getattr(settings, "openrouter_base_url", None)
            or "https://openrouter.ai/api/v1"
        ).strip() or "https://openrouter.ai/api/v1"
        timeout = float(getattr(settings, "openrouter_timeout_s", 45.0) or 45.0)
        for model in _openrouter_chain(settings):
            try:
                parsed = _post_openrouter(
                    user_text,
                    openrouter_key,
                    model,
                    base_url=base_url,
                    timeout=timeout,
                )
            except httpx.HTTPStatusError:
                continue
            except Exception:
                continue
            answer = str(parsed.get("answer") or "").strip()
            if answer:
                return answer, f"openrouter:{model}"
    return None


def _briefing_fallback(packet: dict[str, Any]) -> str:
    stats = packet.get("statistics") or {}
    curve = (packet.get("ep_curve") or {}).get("curve") or []
    losses = packet.get("largest_losses") or []
    event = stats.get("event_id") or "this event"
    region = stats.get("hazard_region") or "the modeled region"
    count = stats.get("claim_count") or 0
    sentences = [
        f"Event {event} covers {count} assets in {region}.",
        f"The ground-up loss is ${stats.get('total_gross_claim', 0):,.0f}, the reinsurer payout is "
        f"${stats.get('reinsurer_payout', 0):,.0f}, and the cedant retains "
        f"${stats.get('cedant_retained_loss', 0):,.0f}.",
        f"Expected annual loss is ${stats.get('expected_annual_loss', 0):,.0f}.",
    ]
    if curve:
        first = curve[0]
        last = curve[-1]
        sentences.append(
            f"The EP curve runs from ${first.get('loss', 0):,.0f} at the "
            f"{first.get('return_period')}-year return period to ${last.get('loss', 0):,.0f} "
            f"at the {last.get('return_period')}-year return period."
        )
    if losses:
        top = losses[0]
        sentences.append(
            f"The largest loss is asset {top.get('asset_id')} "
            f"({top.get('occupancy')}) at ${top.get('loss', 0):,.0f}."
        )
        names = ", ".join(str(row.get("asset_id")) for row in losses[1:5])
        if names:
            sentences.append(f"Other large losses include {names}.")
    sentences.append(
        "This briefing is generated deterministically from the modeled book output."
    )
    return " ".join(sentences)


def brief_job(job: dict[str, Any], settings: Settings | None = None) -> dict[str, Any]:
    """Natural-language risk briefing from the modeled book output."""
    settings = settings or get_settings()
    packet = build_briefing_context(job)
    got = _provider_answer(_briefing_prompt(packet), settings)
    if got is None:
        return {
            "briefing": _briefing_fallback(packet),
            "source": "local-briefing",
            "packet": packet,
        }
    answer, source = got
    return {"briefing": answer, "source": source, "packet": packet}


def _packed_context(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": context.get("name"),
        "event_id": context.get("event_id"),
        "row_count": context.get("row_count"),
        "columns": context.get("columns"),
        "summary_stats": context.get("summary_stats"),
        "sample_rows": context.get("sample_rows"),
        "rows": (context.get("rows") or [])[:40],
    }


def _user_prompt(query: str, context: dict[str, Any]) -> str:
    return (
        "Dataset context (JSON):\n"
        + json.dumps(_packed_context(context), default=str)
        + "\n\nQuestion:\n"
        + query
        + "\n\nReturn JSON with keys answer, matched_asset_ids, summary_stats, confidence."
    )


def _ask_gemini(
    query: str, context: dict[str, Any], key: str, model: str
) -> dict[str, Any]:
    return _post_gemini(_user_prompt(query, context), key, model)


def _post_gemini(user: str, key: str, model: str) -> dict[str, Any]:
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
        },
    }
    url = GEMINI_ENDPOINT.format(model=model)
    with httpx.Client(timeout=45.0) as client:
        response = client.post(url, params={"key": key}, json=payload)
        response.raise_for_status()
        body = response.json()
    candidates = body.get("candidates") or []
    if not candidates:
        raise ValueError("Gemini returned no candidates")
    texts = []
    for part in (candidates[0].get("content") or {}).get("parts") or []:
        if "text" in part:
            texts.append(part["text"])
    parsed = _parse_json("\n".join(texts) or "{}")
    if not isinstance(parsed, dict):
        raise ValueError("Gemini JSON was not an object")
    return parsed


def _ask_openrouter(
    query: str,
    context: dict[str, Any],
    key: str,
    model: str,
    *,
    base_url: str,
    timeout: float = 45.0,
) -> dict[str, Any]:
    return _post_openrouter(
        _user_prompt(query, context),
        key,
        model,
        base_url=base_url,
        timeout=timeout,
    )


def _post_openrouter(
    user: str,
    key: str,
    model: str,
    *,
    base_url: str,
    timeout: float = 45.0,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        "temperature": 0.1,
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    url = base_url.rstrip("/") + OPENROUTER_CHAT_PATH
    with httpx.Client(timeout=timeout) as client:
        response = client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        try:
            body = response.json()
        except ValueError as exc:
            raise ValueError("OpenRouter returned a non-JSON response") from exc
    choices = body.get("choices") or []
    if not choices:
        raise ValueError("OpenRouter returned no choices")
    content = (choices[0].get("message") or {}).get("content") or ""
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    if not str(content).strip():
        raise ValueError("OpenRouter returned empty content")
    parsed = _parse_json(content)
    if not isinstance(parsed, dict):
        raise ValueError("OpenRouter JSON was not an object")
    return parsed


def _from_model(
    parsed: dict[str, Any], context: dict[str, Any], source: str
) -> dict[str, Any]:
    known = _known_ids(context)
    raw_ids = parsed.get("matched_asset_ids") or []
    if not isinstance(raw_ids, list):
        raw_ids = []
    ids = (
        [str(item) for item in raw_ids if str(item) in known]
        if known
        else [str(item) for item in raw_ids]
    )
    answer = str(parsed.get("answer") or "").strip()
    if not answer:
        return _local_fallback_from_ids(context, ids)
    stats = (
        parsed.get("summary_stats")
        if isinstance(parsed.get("summary_stats"), dict)
        else _summary_for(context, ids)
    )
    try:
        confidence = float(
            parsed.get("confidence") if parsed.get("confidence") is not None else 0.7
        )
    except (TypeError, ValueError):
        confidence = 0.7
    confidence = max(0.0, min(1.0, confidence))
    return _pack(answer, ids, stats, confidence, source)


def _local_fallback(query: str, context: dict[str, Any]) -> dict[str, Any]:
    rows = list(context.get("rows") or [])
    name = str(context.get("name") or "")
    phrase = _occupancy_phrase(query, rows)
    depth = _depth_limit(query)
    tokens = _tokens(query, name, phrase)
    matched = [row for row in rows if _row_matches(row, phrase, tokens, depth, name)]
    if phrase and not matched:
        matched = [row for row in rows if phrase in _blob(row)]
    ids = [str(row.get("asset_id")) for row in matched if row.get("asset_id")]
    stats = _summary(matched if matched else rows)
    if not rows:
        answer = "No portfolio rows are loaded for this question."
    elif _is_summary(query) and not phrase and depth is None:
        ids = [str(row.get("asset_id")) for row in rows if row.get("asset_id")]
        stats = _summary(rows)
        answer = _summary_sentence(name, stats, ids, context.get("columns"))
    elif matched:
        answer = _match_sentence(name, phrase, depth, stats, ids)
    elif _is_greeting(query):
        ids = [str(row.get("asset_id")) for row in rows if row.get("asset_id")]
        stats = _summary(rows)
        answer = (
            _summary_sentence(name, stats, ids, context.get("columns"))
            + " Ask about a housing class, the insured value, or where the assets sit."
        )
    else:
        ids = []
        stats = _summary([])
        answer = f"No rows in {name or 'the dataset'} match that question."
    return _pack(answer, ids, stats, 0.55 if ids else 0.35, "local-keyword")


def _local_fallback_from_ids(context: dict[str, Any], ids: list[str]) -> dict[str, Any]:
    if not ids:
        return _pack(
            "No matching assets were returned for that question.",
            [],
            _summary([]),
            0.3,
            "local-keyword",
        )
    wanted = set(ids)
    rows = [
        row for row in (context.get("rows") or []) if str(row.get("asset_id")) in wanted
    ]
    stats = _summary(rows)
    answer = _match_sentence(str(context.get("name") or ""), "", None, stats, ids)
    return _pack(answer, ids, stats, 0.4, "local-keyword")


def _pack(
    answer: str,
    ids: list[str],
    stats: dict[str, Any],
    confidence: float,
    source: str,
) -> dict[str, Any]:
    return {
        "answer": answer,
        "matched_asset_ids": ids,
        "summary_stats": stats,
        "confidence": confidence,
        "source": source,
    }


def _public_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key not in _PAYOUT_KEYS}


def _columns(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    names: list[str] = []
    for row in rows:
        for key in row:
            if key not in names:
                names.append(key)
    described = []
    for name in names:
        values = [row.get(name) for row in rows if row.get(name) not in (None, "")]
        kind = (
            "number"
            if values and all(_is_number(value) for value in values)
            else "text"
        )
        described.append({"name": name, "type": kind})
    return described


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    tivs = [_num(row.get("tiv")) for row in rows]
    tivs = [value for value in tivs if value is not None]
    losses = [_num(row.get("ground_up_loss")) for row in rows]
    losses = [value for value in losses if value is not None]
    occupancies = Counter(
        str(row.get("occupancy") or row.get("occupancy_raw") or "Unknown")
        for row in rows
    )
    tiv_unit = ""
    for row in rows:
        keys = {str(key).strip().lower() for key in row}
        if "tiv_kes" in keys:
            tiv_unit = "KES"
            break
    return {
        "row_count": len(rows),
        "total_tiv": round(sum(tivs), 2) if tivs else 0.0,
        "tiv_unit": tiv_unit,
        "loss_sum": round(sum(losses), 2) if losses else 0.0,
        "loss_mean": round(sum(losses) / len(losses), 2) if losses else 0.0,
        "occupancy_counts": dict(occupancies),
    }


def _summary_for(context: dict[str, Any], ids: list[str]) -> dict[str, Any]:
    wanted = set(ids)
    rows = [
        row for row in (context.get("rows") or []) if str(row.get("asset_id")) in wanted
    ]
    return _summary(rows if rows else list(context.get("rows") or []))


def _known_ids(context: dict[str, Any]) -> set[str]:
    return {
        str(row.get("asset_id"))
        for row in (context.get("rows") or [])
        if row.get("asset_id")
    }


def _occupancy_phrase(query: str, rows: list[dict[str, Any]]) -> str:
    hay = query.lower()
    phrases = []
    for row in rows:
        for key in ("occupancy", "occupancy_raw"):
            value = str(row.get(key) or "").strip().lower()
            if len(value) >= 4:
                phrases.append(value)
    phrases.sort(key=len, reverse=True)
    for phrase in phrases:
        if phrase in hay:
            return phrase
    return ""


def _tokens(query: str, name: str, phrase: str) -> list[str]:
    name_bits = set(re.findall(r"[a-z0-9]+", name.lower()))
    phrase_bits = set(phrase.split())
    tokens = []
    for token in re.findall(r"[a-z0-9]+", query.lower()):
        if (
            token in _STOP
            or token in name_bits
            or token in phrase_bits
            or token.isdigit()
            or len(token) < 3
        ):
            continue
        tokens.append(token)
    return tokens


def _row_matches(
    row: dict[str, Any], phrase: str, tokens: list[str], depth: float | None, name: str
) -> bool:
    blob = _blob(row)
    if phrase and phrase not in blob:
        return False
    if depth is not None:
        value = _num(row.get("flood_depth_m"))
        if value is None or value <= depth:
            return False
    name_blob = name.lower()
    for token in tokens:
        if token not in blob and token not in name_blob:
            return False
    return True


def _blob(row: dict[str, Any]) -> str:
    return " ".join(str(value).lower() for value in row.values())


def _depth_limit(query: str) -> float | None:
    match = _DEPTH_RE.search(query or "")
    if not match:
        return None
    return float(match.group(1))


def _is_greeting(query: str) -> bool:
    words = re.findall(r"[a-z0-9]+", (query or "").lower())
    return bool(words) and all(word in _GREET for word in words)


def _is_summary(query: str) -> bool:
    text = query.lower()
    return any(word in text for word in ("summar", "total tiv", "how many", "count"))


def _summary_sentence(
    name: str,
    stats: dict[str, Any],
    ids: list[str],
    columns: list[dict[str, str]] | None = None,
) -> str:
    label = name or "This portfolio"
    count = int(stats.get("row_count") or 0)
    noun = "row" if count == 1 else "rows"
    fields = [
        str(column.get("name")) for column in (columns or []) if column.get("name")
    ]
    field_text = ", ".join(fields[:12]) or "no named columns"
    occ_counts = stats.get("occupancy_counts") or {}
    known_occ = {
        key: value for key, value in occ_counts.items() if key and key != "Unknown"
    }
    occ = ", ".join(f"{value} {key}" for key, value in known_occ.items())
    shown = ", ".join(ids[:12])
    sentences = [f"{label} contains {count} {noun}."]
    tiv = float(stats.get("total_tiv") or 0)
    if tiv > 0:
        unit = " Kenyan shillings" if stats.get("tiv_unit") == "KES" else ""
        sentences.append(
            f"The total insured value recorded on these rows is {tiv:,.2f}{unit}."
        )
    else:
        sentences.append(
            f"Insured value is not recorded in a tiv column, so there is no insured-value total to report. "
            f"The columns present are {field_text}."
        )
    if occ:
        sentences.append(f"The occupancy mix is {occ}.")
    else:
        sentences.append("Occupancy is not recorded on these rows.")
    if shown:
        extra = "" if len(ids) <= 12 else f", and {len(ids) - 12} more"
        sentences.append(f"The asset identifiers include {shown}{extra}.")
    else:
        sentences.append("The file does not include an asset_id column.")
    return " ".join(sentences)


def _match_sentence(
    name: str, phrase: str, depth: float | None, stats: dict[str, Any], ids: list[str]
) -> str:
    label = name or "the dataset"
    focus = phrase or (
        f"flood depth over {depth} metres" if depth is not None else "that description"
    )
    shown = ", ".join(ids[:12])
    extra = "" if len(ids) <= 12 else f", along with {len(ids) - 12} more"
    count = int(stats.get("row_count") or 0)
    noun = "property" if count == 1 else "properties"
    verb = "matches" if count == 1 else "match"
    listed = shown or "no asset identifiers"
    return (
        f"{count} {noun} in {label} {verb} {focus}. "
        f"The matching assets are {listed}{extra}. "
        f"Their combined insured value is {stats.get('total_tiv', 0):,.2f}."
    )


def _coerce_cell(value: Any) -> Any:
    if value is None:
        return ""
    text = str(value).strip()
    if text == "":
        return ""
    return _num(text) if _looks_number(text) else text


def _looks_number(text: str) -> bool:
    return bool(re.fullmatch(r"-?\d+(?:\.\d+)?", text))


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def _parse_json(text: str) -> Any:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start : end + 1])
        raise
