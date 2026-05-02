# smiles2iupac

> The reliable, free, open-source SMILES → IUPAC name converter that should have existed years ago.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

## What

A library, CLI, and web app that converts SMILES strings to IUPAC nomenclature using a layered pipeline:

```
SMILES → classify → cheap-enrich → SQLite cache → PubChem (InChIKey-keyed)
                                                       ↓ miss
                                                  STOUT v2 generation
                                                       ↓
                                                  OPSIN round-trip validation
                                                       ↓
                                              { name, confidence, source, ... }
```

Every result is tagged with **provenance** and a **confidence score**. PubChem hits are 1.0; STOUT outputs are scored by InChIKey-tier round-trip — full match (0.95), skeleton-only (0.50, stereo lost), or no match (0.20, likely wrong).

## Quick start

```bash
pip install smiles2iupac
s2i 'CCO'
```
```
ethanol  (confidence: 1.00, source: pubchem)
  formula: C2H6O    MW: 46.069
  InChIKey: LFQSCWFLJHTTHZ-UHFFFAOYSA-N
```

Real-world cases work without ceremony:

```bash
s2i 'CC(=O)Oc1ccccc1C(=O)O'                    # aspirin
# 2-acetyloxybenzoic acid  (confidence: 1.00, source: pubchem)
#   formula: C9H8O4    MW: 180.159
#   InChIKey: BSYNRYMUTXBXSQ-UHFFFAOYSA-N

s2i 'CC(=O)[O-].[Na+]'                          # sodium acetate (salt)
# acetate  (confidence: 1.00, source: pubchem)
#   warnings: stripped 1 counter-ion

s2i 'CCO>>CC=O'                                 # rejected: reactions out of scope
# <error: reaction SMILES not supported for naming>

s2i --batch input.csv -o named.csv              # batch with progress bar
s2i CCO --json                                  # full JSON: InChI, InChIKey, formula, MW, alts, etc.
```

```python
from smiles2iupac import convert

result = convert("CC(=O)Oc1ccccc1C(=O)O")  # aspirin
print(result.name)         # '2-acetyloxybenzoic acid'
print(result.confidence)   # 1.0
print(result.formula)      # 'C9H8O4'
print(result.mol_weight)   # 180.159
print(result.inchikey)     # 'BSYNRYMUTXBXSQ-UHFFFAOYSA-N'
```

## Install

```bash
pip install smiles2iupac                  # core: PubChem + cache + CLI
pip install 'smiles2iupac[ml]'            # adds STOUT v2 + OPSIN (requires Java JRE for OPSIN)
pip install 'smiles2iupac[web]'           # adds Gradio + FastAPI for the local web app
pip install 'smiles2iupac[all]'           # everything
```

The `[ml]` extras pull in TensorFlow via STOUT-pypi (~2GB) and require a Java 17+ runtime for OPSIN. Skip them if you only need PubChem coverage.

## Why this exists

As of 2026, no reliable, free, open-source SMILES → IUPAC tool exists online. The capability does — STOUT v2 from the Steinbeck group hits 97.49% exact match — but the deployment was buried inside the DECIMER OCR platform with no public API, no validation layer, no batch mode, and unreliable uptime. This repo wraps the world-class open-source components (STOUT + OPSIN + PubChem + RDKit) into the tool that should already exist.

## What you get back

Every successful conversion yields a fully-populated `Result`:

| Field | Always set? | Notes |
|---|---|---|
| `name` | ✓ on success | The IUPAC name |
| `confidence` | ✓ | 0.0–1.0; tier based on source + validation |
| `source` | ✓ | `pubchem` / `stout_validated` / `stout_unvalidated` / `stout_low_confidence` / `cache` |
| `canonical_smiles` | ✓ | RDKit-canonicalized |
| `inchi` / `inchikey` | ✓ | Standard InChI + 27-char InChIKey |
| `formula` | ✓ | Hill notation |
| `mol_weight` | ✓ | Average MW, g/mol |
| `kind` | ✓ | `molecule` / `salt` / `mixture` / `reaction` / `polymer` / `empty` |
| `warnings` | ✓ | Human-readable notes (e.g. "stripped 1 counter-ion") |
| `alternatives` | opt-in | Common-name synonyms (`--synonyms`) |
| `structure_svg` | opt-in | Square SVG render (`--include-svg`) |
| `cas` | opt-in | CAS Registry Number (`--include-cas`) |
| `error` | only on failure | What went wrong |

## How it handles edge cases

- **Salts** — split on `.`; name the largest organic fragment as parent; record the strip in `warnings`
- **Mixtures** — name the largest component; flag the rest in `warnings`
- **Reactions (`A>>B`)** — rejected with `kind="reaction"` and a clear error
- **Polymers / wildcards (`*`, `[*]`)** — rejected with `kind="polymer"`
- **Stereochemistry** — preserved through OPSIN round-trip; if STOUT loses it, you'll see `STOUT_UNVALIDATED` and a warning rather than a silently-wrong name
- **Heavy-atom limit** — molecules above 999 atoms are out of scope (configurable per-call)
- **InChIKey-keyed PubChem** — RDKit and PubChem canonicalize SMILES differently; the InChIKey lookup catches molecules that SMILES-keyed lookups miss

### Known gaps (from real benchmarking)

- **Complex cyclic peptides** (e.g. cyclosporine) — PubChem's standardizer rejects with `BadRequest`; STOUT helps if `[ml]` extras are installed
- **Occasional PubChem index gaps** (e.g. doxycycline at the canonical SMILES seen) — falls through to STOUT when enabled

## Benchmark

From `notebooks/benchmarking.ipynb`, run against 262 diverse SMILES (drugs, metabolites, heterocycles, materials, salts, stereo, edge cases):

| Metric | Value |
|---|---|
| PubChem exact-match rate | **99.2%** (260/262) |
| Median latency (PubChem path) | 620 ms |
| p95 latency (PubChem path) | 1.15 s |
| Median latency (cache hit) | **0.32 ms** (≈1900× speedup) |
| Misses | 2 (cyclosporine standardizer error, doxycycline index gap) |

Re-run any time:

```bash
jupyter nbconvert --to notebook --execute notebooks/benchmarking.ipynb
```

## How it compares

| Feature | This tool | stout.decimer.ai | ChemAxon Naming |
|---|---|---|---|
| Free + open source | ✅ MIT | ✅ MIT | ❌ commercial |
| Standalone URL & branding | ✅ | ❌ buried in DECIMER | N/A |
| Public REST API | ✅ FastAPI | ❌ | ✅ |
| Python library | ✅ `from smiles2iupac import convert` | ❌ | ✅ |
| CLI | ✅ `s2i 'CCO'` | ❌ | ❌ |
| Batch (CSV) | ✅ streaming | ❌ | ✅ |
| Round-trip validation | ✅ OPSIN, 3-tier confidence | ❌ | partial |
| Confidence scores | ✅ provenance-based | ❌ | ❌ |
| InChI + InChIKey output | ✅ | ❌ | partial |
| Salt stripping with explanation | ✅ | ❌ | ✅ |
| Reliability monitoring | ✅ cron healthcheck | ❌ (down during research) | N/A |

## Architecture

`src/smiles2iupac/`

| Module | Purpose |
|---|---|
| `pipeline.py` | Orchestrator — chains classify → cache → PubChem → STOUT+OPSIN → enrich |
| `validator.py` | RDKit canonicalization + heavy-atom support check |
| `validator_strict.py` | Reaction/polymer rejection, salt stripping, classification |
| `cache.py` | SQLite cache at `~/.smiles2iupac/cache.db` |
| `pubchem.py` | PUG-REST client (token-bucket 5 req/s, exp backoff, InChIKey-first) |
| `stout_engine.py` | STOUT v2 wrapper (lazy-loaded) |
| `opsin_check.py` | py2opsin round-trip with 14/27-char InChIKey tiering |
| `enrich.py` | InChI / InChIKey / formula / MW / SVG / CAS helpers |
| `result.py` | Pydantic Result + Source enum |
| `confidence.py` | Source → confidence tier mapping |
| `cli.py` | `s2i` Click CLI |

`app/` — Gradio UI + FastAPI mounted at `:7860`. Endpoints: `GET /health`, `GET /convert?smiles=...`, `POST /batch` (NDJSON streaming).

`deploy/` — Dockerfile (OpenJDK 17 + Python 3.12 + STOUT model bake-in), HF Spaces config.

`.github/workflows/` — `ci.yml` (pytest), `deploy-hf.yml` (push to HF Space), `healthcheck.yml` (cron uptime ping).

## Run the web app locally

```bash
pip install 'smiles2iupac[web]'
python -m app.gradio_app
# open http://localhost:7860
```

```bash
curl 'http://localhost:7860/convert?smiles=CCO' | jq .name
# "ethanol"
```

## Development

```bash
git clone https://github.com/gvmfhy/smiles2iupac
cd smiles2iupac
uv venv && uv pip install -e '.[all]'
pytest                                           # 99+ tests
```

The cache lives at `~/.smiles2iupac/cache.db` and warms automatically. Wipe it any time — it'll repopulate on demand.

## License

MIT. See [LICENSE](LICENSE).

## Credits

Built on:
- [STOUT v2](https://github.com/Kohulan/Smiles-TO-iUpac-Translator) (Steinbeck group, MIT)
- [OPSIN](https://opsin.ch.cam.ac.uk/) via [py2opsin](https://pypi.org/project/py2opsin/) (Cambridge, MIT)
- [RDKit](https://www.rdkit.org/) (BSD)
- [PubChem PUG-REST](https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest) (NIH, public-domain)
