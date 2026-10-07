"""TypeSafe Jev System-One primitives: Choice, Score, Noul."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from catmod.schemas import ChoiceAnswer, NoulAnswer, ScoreAnswer


class ChoiceQuestion(TypedDict, total=False):
    type: Literal["choice"]
    instructions: str
    criteria: dict[str, str | None]


class ScoreQuestion(TypedDict, total=False):
    type: Literal["score"]
    instructions: str
    criteria: list[str]


class NoulQuestion(TypedDict, total=False):
    type: Literal["noul"]
    instructions: str
    criteria: dict[str, str]


Question = ChoiceQuestion | ScoreQuestion | NoulQuestion


def softmax(logits: list[float]) -> list[float]:
    import math

    peak = max(logits) if logits else 0.0
    exps = [math.exp(x - peak) for x in logits]
    total = sum(exps) or 1.0
    return [e / total for e in exps]


def distribution_confidence(probs: list[float]) -> float:
    """Gap between top-1 and top-2, scaled. Matches Jev's 'use the distribution' idea."""
    if not probs:
        return 0.0
    ordered = sorted(probs, reverse=True)
    top = ordered[0]
    second = ordered[1] if len(ordered) > 1 else 0.0
    return max(0.0, min(1.0, (top - second + top) / 2.0))


def choice_answer(criteria: dict[str, str | None], logits: dict[str, float]) -> ChoiceAnswer:
    keys = list(criteria.keys())
    values = [logits.get(k, 0.0) for k in keys]
    probs = softmax(values)
    mapping = {k: float(p) for k, p in zip(keys, probs)}
    winner = max(mapping, key=mapping.get)
    return ChoiceAnswer(
        choice=winner,
        probabilities=mapping,
        confidence=distribution_confidence(probs),
    )


def score_answer(criteria: list[str], logits: list[float]) -> ScoreAnswer:
    probs = softmax(logits)
    expected = sum(i * p for i, p in enumerate(probs))
    legend = {str(i): label for i, label in enumerate(criteria)}
    return ScoreAnswer(
        score=float(expected),
        probabilities={str(i): float(p) for i, p in enumerate(probs)},
        legend=legend,
        confidence=distribution_confidence(probs),
    )


def noul_answer(probability_yes: float) -> NoulAnswer:
    p = max(0.0, min(1.0, float(probability_yes)))
    return NoulAnswer(noul=p)


def parse_hosted_answer(raw: dict[str, Any]) -> ChoiceAnswer | ScoreAnswer | NoulAnswer:
    kind = raw.get("type")
    if kind == "choice":
        return ChoiceAnswer(
            choice=str(raw["choice"]),
            probabilities={str(k): float(v) for k, v in dict(raw.get("probabilities") or {}).items()},
            confidence=float(raw.get("confidence") or 0.0),
        )
    if kind == "score":
        return ScoreAnswer(
            score=float(raw["score"]),
            probabilities={str(k): float(v) for k, v in dict(raw.get("probabilities") or {}).items()},
            legend={str(k): str(v) for k, v in dict(raw.get("legend") or {}).items()},
            confidence=float(raw.get("confidence") or 0.0),
        )
    return NoulAnswer(noul=float(raw.get("noul") or 0.0))
