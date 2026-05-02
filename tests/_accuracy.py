"""Tier scorer for accuracy tests (not auto-collected by pytest — leading underscore).

Tier definitions:
    T0 — normalized exact: lowercase, collapsed whitespace, ASCII-hyphenated
    T1 — strict exact: byte-for-byte match
    T2 — structural: predicted name → OPSIN-parses → same InChIKey as input
    T3 — synonym: predicted name appears in PubChem synonyms (when a lookup is wired)

T2 is the chemically meaningful "correct." Per the plan, CI gates on T2.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from smiles2iupac.opsin_check import OpsinError, round_trip

_DASH_RE = re.compile(r"[‐‑‒–—―]")
_WS_RE = re.compile(r"\s+")


@dataclass
class TierScore:
    """Per-row pass/fail across 4 tiers. None = not scored (e.g. OPSIN unavailable)."""

    tier_0_normalized: bool | None = None
    tier_1_strict: bool | None = None
    tier_2_structural: bool | None = None
    tier_3_synonym: bool | None = None
    error: str | None = None


def _normalize(name: str) -> str:
    """Lowercase, collapse whitespace, normalize unicode dashes → ASCII hyphen."""
    s = _DASH_RE.sub("-", name.strip().lower())
    return _WS_RE.sub(" ", s)


def score(
    predicted_name: str | None,
    reference_name: str,
    original_canonical_smiles: str,
    synonyms_lookup: Callable[[str], list[str]] | None = None,
) -> TierScore:
    """Score a single prediction across the 4 tiers.

    `synonyms_lookup`, if provided, is a callable that takes a canonical SMILES
    and returns the PubChem synonyms list — used for Tier 3. The cassette-replay
    test wires this to a cassette reader; the live test wires it to PubChem.
    """
    out = TierScore()

    if predicted_name is None or not predicted_name.strip():
        out.error = "no prediction"
        out.tier_0_normalized = False
        out.tier_1_strict = False
        out.tier_2_structural = False
        if synonyms_lookup is not None:
            out.tier_3_synonym = False
        return out

    out.tier_1_strict = predicted_name == reference_name
    out.tier_0_normalized = _normalize(predicted_name) == _normalize(reference_name)

    try:
        rt = round_trip(predicted_name, original_canonical_smiles)
        out.tier_2_structural = rt.full_match
    except OpsinError:
        out.tier_2_structural = None  # OPSIN unavailable: skip rather than fail

    if synonyms_lookup is not None:
        try:
            syns = synonyms_lookup(original_canonical_smiles)
            out.tier_3_synonym = predicted_name in syns
        except Exception:
            out.tier_3_synonym = None

    return out


def _rate(scores: list[TierScore], attr: str) -> float | None:
    """Pass-rate for an attribute across scores, ignoring None (not-scored) entries."""
    vals = [getattr(s, attr) for s in scores if getattr(s, attr) is not None]
    if not vals:
        return None
    return sum(1 for v in vals if v) / len(vals)


def summarize(scored: list[tuple[str, TierScore]]) -> dict:
    """Group scores by category, return per-category + overall pass rates per tier.

    Input: list of (category, TierScore) tuples.
    Output: {"per_category": {cat: {n, tier_0, tier_1, tier_2, tier_3}, ...},
             "overall": {n, tier_0, tier_1, tier_2, tier_3}}
    """
    by_cat: dict[str, list[TierScore]] = {}
    for cat, s in scored:
        by_cat.setdefault(cat, []).append(s)

    per_cat = {
        cat: {
            "n": len(ss),
            "tier_0": _rate(ss, "tier_0_normalized"),
            "tier_1": _rate(ss, "tier_1_strict"),
            "tier_2": _rate(ss, "tier_2_structural"),
            "tier_3": _rate(ss, "tier_3_synonym"),
        }
        for cat, ss in by_cat.items()
    }

    all_scores = [s for _, s in scored]
    overall = {
        "n": len(all_scores),
        "tier_0": _rate(all_scores, "tier_0_normalized"),
        "tier_1": _rate(all_scores, "tier_1_strict"),
        "tier_2": _rate(all_scores, "tier_2_structural"),
        "tier_3": _rate(all_scores, "tier_3_synonym"),
    }
    return {"per_category": per_cat, "overall": overall}
