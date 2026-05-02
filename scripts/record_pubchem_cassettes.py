"""Record PubChem responses for the offline accuracy test.

Picks a stratified 300-row subset of the accuracy dataset (proportional across
categories) and saves one merged JSON cassette file with everything the offline
test needs to replay PubChem calls without hitting the network.

Cassette format is intentionally simple — a dict of InChIKey → {iupac_name,
canonical_smiles, synonyms} — so the test can mock `iupac_via_inchikey` and
`smiles_to_synonyms` directly. This is simpler than VCR-style verbatim HTTP
replay and avoids hidden coupling to PubChem's response shape.

Usage:
    python scripts/record_pubchem_cassettes.py
    python scripts/record_pubchem_cassettes.py --subset 100   # smaller subset
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from smiles2iupac.pubchem import (  # noqa: E402
    PubChemError,
    iupac_via_inchikey,
    smiles_to_synonyms,
)

DATASET_CSV = REPO / "tests" / "fixtures" / "accuracy_dataset.csv"
CASSETTE_JSON = REPO / "tests" / "fixtures" / "pubchem_cassettes.json"


def stratified_sample(rows: list[dict], n: int, seed: int = 42) -> list[dict]:
    """Pick `n` rows proportional to per-category counts."""
    rng = random.Random(seed)
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_cat[r["category"]].append(r)
    total = len(rows)
    picked: list[dict] = []
    for cat, group in by_cat.items():
        # Proportional, with at least 1 if the category exists in the dataset
        share = max(1, math.ceil(len(group) / total * n))
        rng.shuffle(group)
        picked.extend(group[:share])
    rng.shuffle(picked)
    return picked[:n]


def record(rows: list[dict]) -> dict[str, dict]:
    """Hit PubChem for each row; return cassette dict keyed by InChIKey."""
    cassettes: dict[str, dict] = {}
    n = len(rows)
    for i, r in enumerate(rows, 1):
        key = r["inchikey"]
        canonical = r["canonical_smiles"]
        if key in cassettes:
            continue
        try:
            iupac = iupac_via_inchikey(key)
        except PubChemError as e:
            print(f"  [{i}/{n}] {key} — IUPAC fetch failed: {e}")
            continue
        try:
            syns = smiles_to_synonyms(canonical, limit=10)
        except PubChemError as e:
            print(f"  [{i}/{n}] {key} — synonyms fetch failed: {e}")
            syns = []
        cassettes[key] = {
            "inchikey": key,
            "canonical_smiles": canonical,
            "iupac_name": iupac,
            "synonyms": syns,
        }
        if i % 25 == 0:
            print(f"  [{i}/{n}] recorded {len(cassettes)} unique cassettes")
    return cassettes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--subset", type=int, default=300,
                    help="how many rows to record (default 300)")
    ap.add_argument("--dataset", type=Path, default=DATASET_CSV)
    ap.add_argument("--output", type=Path, default=CASSETTE_JSON)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    if not args.dataset.exists():
        print(f"ERROR: dataset not found at {args.dataset}", file=sys.stderr)
        print("Run scripts/build_accuracy_dataset.py first.", file=sys.stderr)
        return 1

    with open(args.dataset) as f:
        rows = list(csv.DictReader(f))
    print(f"Loaded {len(rows)} rows from {args.dataset}")

    sample = stratified_sample(rows, args.subset, args.seed)
    print(f"Stratified sample: {len(sample)} rows")

    cassettes = record(sample)
    print(f"\nRecorded {len(cassettes)} unique cassettes")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump({
            "version": 1,
            "n_rows": len(cassettes),
            "cassettes": cassettes,
        }, f, indent=2, sort_keys=True)
    print(f"Wrote cassettes to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
