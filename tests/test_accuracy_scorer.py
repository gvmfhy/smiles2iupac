"""Unit tests for the accuracy scorer in tests/_accuracy.py.

These don't hit OPSIN (no py2opsin needed). The OPSIN-dependent Tier 2
behavior is exercised in test_accuracy_offline.py against the real dataset.
"""

from __future__ import annotations

from tests._accuracy import TierScore, _normalize, score, summarize


def test_normalize_lowercases():
    assert _normalize("Ethanol") == "ethanol"
    assert _normalize("ETHANOL") == "ethanol"


def test_normalize_collapses_whitespace():
    assert _normalize("  foo   bar  \tbaz") == "foo bar baz"


def test_normalize_unifies_unicode_dashes():
    # en-dash, em-dash, hyphen-minus should all become ASCII hyphen
    assert _normalize("foo–bar") == "foo-bar"
    assert _normalize("foo—bar") == "foo-bar"
    assert _normalize("foo-bar") == "foo-bar"
    assert _normalize("(R)-2-aminopropan—oic acid") == "(r)-2-aminopropan-oic acid"


def test_score_strict_match_passes_t0_and_t1():
    s = score("ethanol", "ethanol", "CCO")
    assert s.tier_0_normalized is True
    assert s.tier_1_strict is True


def test_score_case_difference_passes_t0_only():
    s = score("ETHANOL", "ethanol", "CCO")
    assert s.tier_0_normalized is True
    assert s.tier_1_strict is False


def test_score_none_prediction_fails_all_tiers():
    s = score(None, "ethanol", "CCO")
    assert s.tier_0_normalized is False
    assert s.tier_1_strict is False
    assert s.tier_2_structural is False
    assert s.error == "no prediction"


def test_score_empty_string_prediction_fails_all_tiers():
    s = score("", "ethanol", "CCO")
    assert s.tier_0_normalized is False
    assert s.tier_1_strict is False
    assert s.tier_2_structural is False


def test_score_synonyms_lookup_t3_pass():
    def syns(_smi: str) -> list[str]:
        return ["ethanol", "ethyl alcohol", "alcohol"]

    s = score("ethyl alcohol", "ethanol", "CCO", synonyms_lookup=syns)
    # Strict and normalized fail (different name); synonym match passes
    assert s.tier_1_strict is False
    assert s.tier_3_synonym is True


def test_score_synonyms_lookup_t3_miss():
    def syns(_smi: str) -> list[str]:
        return ["ethanol", "ethyl alcohol"]

    s = score("methanol", "ethanol", "CCO", synonyms_lookup=syns)
    assert s.tier_3_synonym is False


def test_score_synonyms_lookup_none_when_not_provided():
    s = score("ethanol", "ethanol", "CCO")  # no lookup callable
    assert s.tier_3_synonym is None  # not scored


def test_summarize_per_category():
    scored = [
        ("drug", TierScore(tier_0_normalized=True, tier_1_strict=True, tier_2_structural=True)),
        ("drug", TierScore(tier_0_normalized=True, tier_1_strict=False, tier_2_structural=True)),
        ("drug", TierScore(tier_0_normalized=False, tier_1_strict=False, tier_2_structural=False)),
        ("solvent", TierScore(tier_0_normalized=True, tier_1_strict=True, tier_2_structural=True)),
    ]
    out = summarize(scored)
    assert out["per_category"]["drug"]["n"] == 3
    assert out["per_category"]["drug"]["tier_2"] == 2 / 3
    assert out["per_category"]["drug"]["tier_1"] == 1 / 3
    assert out["per_category"]["solvent"]["tier_2"] == 1.0
    assert out["overall"]["n"] == 4
    assert out["overall"]["tier_2"] == 3 / 4


def test_summarize_skips_none_in_rate():
    """A tier with all None values returns None (not zero)."""
    scored = [
        ("drug", TierScore(tier_0_normalized=True, tier_2_structural=None)),
        ("drug", TierScore(tier_0_normalized=False, tier_2_structural=None)),
    ]
    out = summarize(scored)
    assert out["overall"]["tier_0"] == 0.5
    assert out["overall"]["tier_2"] is None
