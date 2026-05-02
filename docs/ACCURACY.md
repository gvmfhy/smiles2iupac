# Accuracy Testing

This project measures **correctness** — not just hit-rate. The accuracy framework lives in:

```
scripts/build_accuracy_dataset.py    # build the verified reference library
scripts/record_pubchem_cassettes.py  # snapshot PubChem responses for offline replay
tests/_accuracy.py                   # tier scorer (non-test helper)
tests/test_accuracy_offline.py       # per-PR test using cassettes
tests/fixtures/accuracy_dataset.csv  # 1000-row reference library
tests/fixtures/pubchem_cassettes.json # cached PubChem responses
tests/fixtures/accuracy_baseline.json # per-tier rates the CI gates against
```

## How ground truth is established

PubChem's `IUPACName` field is computed by ChemAxon's algorithm. We **cross-validate** every entry by running the name back through OPSIN (a different IUPAC implementation by the Cambridge group). If OPSIN parses the name to a SMILES whose InChIKey matches the input across **both** block-1 (skeleton) and block-2 (stereo + protonation), two independent IUPAC algorithms agree on the molecule. That cross-implementation agreement is what makes the entry "verified."

Names that round-trip via OPSIN are dropped at build time. The dataset CSV contains only entries that have passed both the PubChem and OPSIN tests.

## The four tiers

For each prediction, `tests/_accuracy.score()` returns four pass/fail flags:

| Tier | Definition | What it catches |
|---|---|---|
| **T0** | Normalized-exact (lowercase, collapsed whitespace, ASCII-hyphenated) | Trivial casing/spacing differences |
| **T1** | Strict byte-for-byte match | Most useful for "did our cache or pipeline corrupt the name?" |
| **T2** | OPSIN round-trip — predicted name parses back to a SMILES with the **same InChIKey** | Chemically-meaningful "correct" |
| **T3** | Predicted name appears in PubChem synonyms list | "Recognized name, but maybe not primary" |

**CI gates on T2** because it's the only tier that's chemically meaningful. T1 catches different bugs (cache corruption, ChemAxon updates that change a name's exact spelling) but doesn't reflect correctness; a name can be perfectly correct AND fail T1.

T2 = `opsin_check.round_trip(predicted, canonical_smiles).full_match` — defined in `src/smiles2iupac/opsin_check.py`.

## Per-PR CI test

`tests/test_accuracy_offline.py` runs against the stratified ~300-row subset that has cassettes. PubChem is mocked to return cassette responses, so the test is fast (<5s) and deterministic. The test asserts:

- Tier 2 rate must not drop more than 1 percentage point below baseline
- Tier 1 rate must not drop more than 1 percentage point below baseline

If a PR causes either to fall below those thresholds, CI fails with a clear message naming the actual rate vs the baseline.

## Updating the baseline

When pipeline changes legitimately improve accuracy, update the baseline:

```bash
# Run the test once to see the new rates
.venv/bin/python -m pytest tests/test_accuracy_offline.py -v -s

# The test prints a summary table. Manually copy the new rates into:
tests/fixtures/accuracy_baseline.json

# Commit the baseline change with the PR that introduced the improvement.
git add tests/fixtures/accuracy_baseline.json
git commit -m "test: bump accuracy baseline after <change description>"
```

The baseline is intentionally small (just per-tier overall rates + per-category breakdowns + dataset_version). It lives in-tree so changes are reviewable in PR.

## Rebuilding the dataset

The dataset is sticky — re-run only when:
- PubChem's `IUPACName` algorithm has been updated by ChemAxon
- You want to expand category coverage
- You want a different sample seed

```bash
# Full rebuild — hits PubChem live, takes ~10 minutes for 1000 rows
.venv/bin/python scripts/build_accuracy_dataset.py --limit 1000 --seed 42

# Then re-record cassettes
.venv/bin/python scripts/record_pubchem_cassettes.py --subset 300

# Then run the test, observe new rates, update baseline
.venv/bin/python -m pytest tests/test_accuracy_offline.py -v -s
```

The `dataset_version` (a SHA-256 of sorted contents) changes whenever the CSV changes. Reports include this version so you can tie an accuracy report to a specific dataset snapshot.

## Extending the dataset

The build script seeds candidates from the existing 262-row fixture (`tests/fixtures/known_molecules.csv`) and tops up via random PubChem CID sampling. To add specific molecules:

1. Add their canonical SMILES to `known_molecules.csv` with a category note.
2. Re-run the build script — they'll be picked up first, then random sampling fills the rest.
3. Re-record cassettes.

To extend coverage of a particular category (e.g. carbohydrates):
1. Increase the target in `CATEGORY_TARGETS` in `scripts/build_accuracy_dataset.py`.
2. Add hand-curated SMILES to the seed fixture.
3. Re-run the build.

## Out of scope (deferred to v0.2)

- **STOUT-path accuracy** — STOUT requires Python 3.10/3.11 + ~500MB TF; tests run under Docker
- **NIST WebBook supplement** — independent ~500-row corpus from NIST chemistry standards
- **Live-PubChem nightly run** — full 1000-row dataset against live PubChem, no cassettes
- **Drift alerting** — opens a GitHub issue if Tier 2 drops > 2pp on the nightly run
- **Cross-source agreement** — PubChem vs STOUT vs OPSIN comparison per molecule
