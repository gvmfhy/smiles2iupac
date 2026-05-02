"""Offline accuracy test using cached PubChem responses.

Runs the full pipeline against the stratified subset of the verified accuracy
dataset that has cassettes. PubChem is mocked so this test is fast (<5s) and
deterministic. Asserts pipeline correctness doesn't regress from baseline.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from smiles2iupac.cache import Cache
from smiles2iupac.pipeline import Pipeline

from tests._accuracy import TierScore, score, summarize

REPO_ROOT = Path(__file__).resolve().parent.parent
DATASET_CSV = REPO_ROOT / "tests" / "fixtures" / "accuracy_dataset.csv"
CASSETTE_JSON = REPO_ROOT / "tests" / "fixtures" / "pubchem_cassettes.json"
BASELINE_JSON = REPO_ROOT / "tests" / "fixtures" / "accuracy_baseline.json"

# How far below baseline we tolerate before failing CI.
REGRESSION_TOLERANCE_PP = 0.01  # 1 percentage point
# Floor for the very first run when no baseline exists yet.
FIRST_RUN_TIER_2_FLOOR = 0.90


def _load_artifacts():
    """Returns (rows, cassettes_dict, baseline_dict). Skips test if any are missing."""
    if not DATASET_CSV.exists():
        pytest.skip(
            f"{DATASET_CSV.name} missing — run `python scripts/build_accuracy_dataset.py` first"
        )
    if not CASSETTE_JSON.exists():
        pytest.skip(
            f"{CASSETTE_JSON.name} missing — run `python scripts/record_pubchem_cassettes.py` first"
        )

    with open(DATASET_CSV) as f:
        all_rows = list(csv.DictReader(f))
    with open(CASSETTE_JSON) as f:
        payload = json.load(f)
        cassettes = payload["cassettes"]

    rows = [r for r in all_rows if r["inchikey"] in cassettes]
    baseline = {}
    if BASELINE_JSON.exists():
        with open(BASELINE_JSON) as f:
            baseline = json.load(f)
    return rows, cassettes, baseline


def _print_summary(summary: dict) -> None:
    overall = summary["overall"]
    print(f"\n{'=' * 70}")
    print(f"ACCURACY — n={overall['n']}")
    for tier in ("tier_0", "tier_1", "tier_2", "tier_3"):
        rate = overall[tier]
        if rate is None:
            print(f"  {tier}: N/A")
        else:
            print(f"  {tier}: {rate * 100:.2f}%")
    print(f"{'=' * 70}")
    print(f"{'Category':<25} {'n':>4} {'T0':>7} {'T1':>7} {'T2':>7} {'T3':>7}")

    def _fmt(v):
        return f"{v * 100:5.1f}%" if v is not None else "  N/A"

    for cat, st in sorted(summary["per_category"].items()):
        print(
            f"  {cat:<25} {st['n']:>3}  {_fmt(st['tier_0']):>7}"
            f"  {_fmt(st['tier_1']):>7}  {_fmt(st['tier_2']):>7}  {_fmt(st['tier_3']):>7}"
        )
    print()


def test_accuracy_against_reference(tmp_cache: Cache, capsys):
    rows, cassettes, baseline = _load_artifacts()
    if len(rows) < 50:
        pytest.skip(f"only {len(rows)} cassetted rows; need at least 50 for stable rates")

    def mock_iupac_via_inchikey(key: str) -> str | None:
        c = cassettes.get(key)
        return c["iupac_name"] if c else None

    def mock_smiles_to_iupac(smi: str) -> str | None:
        # Fallback path; reachable only if the InChIKey lookup somehow misses.
        for c in cassettes.values():
            if c["canonical_smiles"] == smi:
                return c["iupac_name"]
        return None

    def synonyms_for_score(canonical: str) -> list[str]:
        for c in cassettes.values():
            if c["canonical_smiles"] == canonical:
                return c.get("synonyms", [])
        return []

    pipeline = Pipeline(cache=tmp_cache, use_pubchem=True, use_stout=False)
    scored: list[tuple[str, TierScore]] = []

    with patch(
        "smiles2iupac.pipeline.iupac_via_inchikey", side_effect=mock_iupac_via_inchikey
    ), patch(
        "smiles2iupac.pipeline.smiles_to_iupac", side_effect=mock_smiles_to_iupac
    ):
        for row in rows:
            result = pipeline.convert(row["canonical_smiles"])
            s = score(
                predicted_name=result.name,
                reference_name=row["iupac_name"],
                original_canonical_smiles=row["canonical_smiles"],
                synonyms_lookup=synonyms_for_score,
            )
            scored.append((row["category"], s))

    summary = summarize(scored)

    # Always print summary so it shows in pytest -v output.
    with capsys.disabled():
        _print_summary(summary)

    overall = summary["overall"]
    actual_t2 = overall["tier_2"]
    actual_t1 = overall["tier_1"]

    # If no baseline yet, this is the first-run accuracy bake. Assert a
    # reasonable floor so a totally-broken pipeline still fails the test.
    if not baseline:
        assert actual_t2 is not None and actual_t2 >= FIRST_RUN_TIER_2_FLOOR, (
            f"First-run Tier 2 floor: {actual_t2} < {FIRST_RUN_TIER_2_FLOOR}. "
            f"Either the pipeline is broken or update FIRST_RUN_TIER_2_FLOOR."
        )
        return

    baseline_t2 = baseline.get("overall", {}).get("tier_2")
    if baseline_t2 is not None and actual_t2 is not None:
        assert actual_t2 >= baseline_t2 - REGRESSION_TOLERANCE_PP, (
            f"Tier 2 regression: actual {actual_t2:.4f} < baseline {baseline_t2:.4f} "
            f"- {REGRESSION_TOLERANCE_PP} (tolerance). Pipeline correctness has degraded."
        )

    baseline_t1 = baseline.get("overall", {}).get("tier_1")
    if baseline_t1 is not None and actual_t1 is not None:
        assert actual_t1 >= baseline_t1 - REGRESSION_TOLERANCE_PP, (
            f"Tier 1 regression: actual {actual_t1:.4f} < baseline {baseline_t1:.4f}"
        )


def test_dataset_version_consistency():
    """Every row must carry the same dataset_version hash."""
    if not DATASET_CSV.exists():
        pytest.skip("dataset not built yet")
    with open(DATASET_CSV) as f:
        rows = list(csv.DictReader(f))
    versions = {r["dataset_version"] for r in rows}
    assert len(versions) == 1, f"Mixed dataset versions: {versions}"


def test_dataset_smiles_canonicalize():
    """Every row's smiles_input must canonicalize to the row's canonical_smiles."""
    from smiles2iupac.validator import canonicalize

    if not DATASET_CSV.exists():
        pytest.skip("dataset not built yet")
    with open(DATASET_CSV) as f:
        rows = list(csv.DictReader(f))
    mismatches = []
    for r in rows[:50]:  # spot-check first 50 to keep test fast
        try:
            actual = canonicalize(r["smiles_input"])
            if actual != r["canonical_smiles"]:
                mismatches.append((r["id"], r["smiles_input"], r["canonical_smiles"], actual))
        except Exception as e:
            mismatches.append((r["id"], r["smiles_input"], r["canonical_smiles"], str(e)))
    assert not mismatches, f"Canonicalization mismatches in dataset: {mismatches[:5]}"
