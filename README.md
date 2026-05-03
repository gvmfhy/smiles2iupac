---
title: smiles2iupac
emoji: 🧪
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
license: mit
short_description: SMILES to IUPAC name conversion (PubChem + OPSIN)
---

<!-- The YAML block above is HF Spaces config; it must be the very first thing
     in the file. GitHub renders it as a thematic-break + paragraph, which is
     ugly but harmless. HF Spaces requires it to discover sdk=docker / port=7860. -->

# smiles2iupac

> Free, open-source SMILES → IUPAC naming where every returned name is cross-validated by two independent IUPAC implementations.

[![CI](https://github.com/gvmfhy/smiles2iupac/actions/workflows/ci.yml/badge.svg)](https://github.com/gvmfhy/smiles2iupac/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/python-3.10--3.12-blue.svg)](https://www.python.org/downloads/)
[![Status](https://img.shields.io/badge/status-alpha-orange.svg)]()
[![HF Space](https://img.shields.io/badge/🤗-Live%20Demo-blue.svg)](https://agwgwa-smiles2iupac.hf.space)

> **Status:** alpha. Live at <https://agwgwa-smiles2iupac.hf.space>. Not yet on PyPI.
>
> Every returned name is structurally verified by **two independent IUPAC implementations** — PubChem's ChemAxon naming, then OPSIN's Cambridge parser round-trip — so coverage is bounded by PubChem (~120M compounds) but correctness is high. Structures PubChem doesn't recognize get an honest "not found" rather than an unverifiable guess.

## What

A library, CLI, and web app that converts SMILES strings to IUPAC nomenclature using a layered pipeline:

```
SMILES → classify → cheap-enrich → SQLite cache → PubChem (InChIKey-keyed)
                                                       ↓ miss
                                                  OPSIN round-trip on PubChem name
                                                       ↓
                                              { name, confidence, source, ... }
```

Every result is tagged with **provenance** and a **confidence score**. PubChem hits are 1.0; cache hits are 1.0; nothing is returned with low confidence today. ML-based generation for structures PubChem doesn't recognize is a documented future tier — see [Roadmap](#roadmap).

## Quick start

```bash
git clone https://github.com/gvmfhy/smiles2iupac.git
cd smiles2iupac
uv venv && uv pip install -e .  # or: python -m venv .venv && pip install -e .
.venv/bin/s2i 'CCO'
```
```
ethanol  (confidence: 1.00, source: pubchem)
  formula: C2H6O    MW: 46.069
  InChIKey: LFQSCWFLJHTTHZ-UHFFFAOYSA-N
  verify: https://pubchem.ncbi.nlm.nih.gov/#query=LFQSCWFLJHTTHZ-UHFFFAOYSA-N
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
#   verify: https://pubchem.ncbi.nlm.nih.gov/#query=QTBSBXVTEAMEQO-UHFFFAOYSA-M

s2i 'CC(=O)[O-].[Na+]' --trace                  # see exactly what the pipeline did
# acetate  (confidence: 1.00, source: pubchem)
#   ...
# Pipeline reasoning:
#   1. Identified as salt — parent: CC(=O)[O-]; stripped 1 counter-ion(s): [Na+]
#   2. Computed InChIKey: QTBSBXVTEAMEQO-UHFFFAOYSA-M
#   3. Cache miss
#   4. PubChem InChIKey lookup → matched: 'acetate'

s2i 'CCO>>CC=O'                                 # rejected: reactions out of scope
# <error: reaction SMILES not supported for naming>

s2i --reverse 'aspirin'                         # reverse: name → SMILES (handles common + IUPAC names)
# CC(=O)Oc1ccccc1C(=O)O

s2i --reverse '(2S)-2-aminopropanoic acid'      # IUPAC names go through OPSIN (no network, stereo-aware)
# C[C@H](N)C(=O)O

s2i --batch input.csv -o named.csv              # batch with progress bar
s2i CCO --json                                  # full JSON: InChI, InChIKey, formula, MW, alts, etc.
```

```python
from smiles2iupac import convert, lookup

result = convert("CC(=O)Oc1ccccc1C(=O)O")  # aspirin
print(result.name)         # '2-acetyloxybenzoic acid'
print(result.confidence)   # 1.0
print(result.formula)      # 'C9H8O4'
print(result.mol_weight)   # 180.159
print(result.inchikey)     # 'BSYNRYMUTXBXSQ-UHFFFAOYSA-N'

# Reverse direction: name (common or IUPAC) → SMILES
print(lookup("caffeine"))  # 'Cn1c(=O)c2c(ncn2C)n(C)c1=O'
```

## Install

The package is **not yet on PyPI**. Install from the GitHub repo:

```bash
git clone https://github.com/gvmfhy/smiles2iupac.git
cd smiles2iupac
uv venv && uv pip install -e .              # core only (PubChem + cache + CLI)
uv pip install -e '.[ml]'                   # add OPSIN validation
uv pip install -e '.[web]'                  # add Gradio + FastAPI
uv pip install -e '.[mcp]'                  # add MCP server (s2i-mcp)
uv pip install -e '.[all]'                  # everything
```

| Extra | What you get | Python | OS deps |
|---|---|---|---|
| (core) | PubChem lookup, cache, CLI, enrichment | 3.10–3.12 | none |
| `[web]` | Gradio UI + FastAPI mounted at `:7860` | 3.10–3.12 | none |
| `[mcp]` | MCP server (`s2i-mcp`) for Claude Desktop / Cursor / Cline | 3.10–3.12 | none |
| `[ml]` | OPSIN round-trip validation (`py2opsin`) | 3.10–3.12 | Java 17+ JRE |

## Why this exists

As of 2026, no free, open-source SMILES → IUPAC tool exists online with an API, validation layer, batch mode, and steady uptime. PubChem's PUG-REST is free and authoritative for ~120M compounds but has no naming UI, no batching, no round-trip validation, and rate limits. ML-based tools (STOUT v2, the Steinbeck group's 97.49% accuracy model) exist as research artifacts but aren't packaged as a service today — STOUT's upstream weights URL returns 404 as of this writing. This repo combines OPSIN (Cambridge's gold-standard IUPAC parser, used in reverse for round-trip validation) with PubChem InChIKey lookup behind a single CLI / library / web app / MCP / FastAPI surface — the cross-validated part of the stack, packaged the way it should already exist.

## What you get back

Every successful conversion yields a fully-populated `Result`:

| Field | Always set? | Notes |
|---|---|---|
| `name` | ✓ on success | The IUPAC name |
| `confidence` | ✓ | 0.0–1.0; tier based on source + validation |
| `source` | ✓ | `pubchem` / `cache` |
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
- **Stereochemistry** — preserved through OPSIN round-trip; the InChIKey-keyed PubChem lookup matches both stereo (full-key) and skeleton (block-1) tiers
- **Heavy-atom limit** — molecules above 999 atoms are out of scope (configurable per-call)
- **InChIKey-keyed PubChem** — RDKit and PubChem canonicalize SMILES differently; the InChIKey lookup catches molecules that SMILES-keyed lookups miss

### Known gaps (from real benchmarking)

- **Complex cyclic peptides** (e.g. cyclosporine) — PubChem's standardizer rejects with `BadRequest`; returns no name today
- **Occasional PubChem index gaps** (e.g. doxycycline at the canonical SMILES seen) — returns no name today
- **Genuinely novel structures** — anything outside PubChem's ~120M-compound index returns "not found" rather than a guess. Closing this gap is the main item on the [Roadmap](#roadmap).

## Benchmark

### Hit rate (did PubChem return *anything*?)

From `notebooks/benchmarking.ipynb`, run against 262 diverse SMILES (drugs, metabolites, heterocycles, materials, salts, stereo, edge cases). This measures *coverage*, not correctness — see the Accuracy section below for verified-correct rates.

| Metric | Value |
|---|---|
| PubChem hit rate | **99.2%** (260/262) |
| Median latency (PubChem path) | 620 ms |
| p95 latency (PubChem path) | 1.15 s |
| Median latency (cache hit) | **0.32 ms** (≈1900× speedup) |
| Misses | 2 (cyclosporine standardizer error, doxycycline index gap) |

### Accuracy (is the returned name actually correct?)

From `tests/test_accuracy_offline.py`, run against a 300-molecule stratified subset of 850 PubChem-OPSIN-cross-validated reference pairs (full library at `tests/fixtures/accuracy_dataset.csv`):

| Metric | Value |
|---|---|
| **Tier 2 — structural correctness** (OPSIN round-trip InChIKey match) | **95.0%** (285/300) |
| Tier 1 — strict exact-string match against ground truth | 95.0% |
| Tier 3 — name appears in PubChem synonyms list | 22.0% |

**Per-category Tier 2 (structural correctness):**

| Category | Rate | Note |
|---|---|---|
| Drugs (n=53) | **100%** | |
| Stereochemistry (n=51) | **100%** | preserved through pipeline |
| Solvents/aliphatics (n=36) | **100%** | |
| Heterocycles (n=35) | **100%** | |
| Pathological/exotic (n=25) | 96% | |
| Large >30 atoms (n=35) | 94% | PubChem standardizer gaps |
| Unusual elements (n=11) | 82% | B/Si/Se compounds tricky |
| Salts/zwitterions (n=18) | 44% | pipeline names parent fragment; PubChem's `IUPACName` joins multi-component names with semicolons — different conventions, both arguably correct |

The CI gate fails if Tier 2 drops more than 1 percentage point below baseline. See [`docs/ACCURACY.md`](docs/ACCURACY.md) for tier definitions, ground-truth methodology, and how to update the baseline when accuracy improves.

Re-run any time:

```bash
# Hit-rate benchmark (live PubChem)
jupyter nbconvert --to notebook --execute notebooks/benchmarking.ipynb

# Accuracy benchmark (cached cassettes; deterministic, <2 min)
.venv/bin/python -m pytest tests/test_accuracy_offline.py -v -s

# Rebuild the reference library from scratch (~10 min, hits PubChem)
.venv/bin/python scripts/build_accuracy_dataset.py --limit 1000 --seed 42
.venv/bin/python scripts/record_pubchem_cassettes.py --subset 300
```

## How it compares

Comparison reflects what's *built* in this repo vs what's currently public-facing in alternatives. Rows marked "(planned)" describe scaffolding that's committed but not yet deployed.

| Feature | This tool | stout.decimer.ai | ChemAxon Naming |
|---|---|---|---|
| Free + open source | ✅ MIT | ✅ MIT | ❌ commercial |
| Python library | ✅ `from smiles2iupac import convert` | ❌ | ✅ |
| CLI | ✅ `s2i 'CCO'` | ❌ | ❌ |
| MCP server (LLM tool) | ✅ 4 tools, stdio | ❌ | ❌ |
| Batch (CSV) | ✅ streaming NDJSON | ❌ | ✅ |
| Round-trip validation | ✅ OPSIN, 4-tier provenance | ❌ | partial |
| Confidence scores | ✅ provenance-based | ❌ | ❌ |
| InChI + InChIKey output | ✅ | ❌ | partial |
| Salt stripping + reasoning trace | ✅ | ❌ | ✅ |
| Self-hosted REST API | ✅ FastAPI at `:7860` | ❌ | ✅ |
| Public hosted URL (planned) | scaffolded for HF Spaces | ✅ (often offline) | commercial |
| Uptime monitoring (planned) | scaffolded healthcheck workflow | ❌ | N/A |

## Roadmap

- **ML-based generation tier for novel structures.** STOUT v2 was the original plan; its upstream weights download (`storage.googleapis.com/decimer_weights/models.zip`) returns 404 as of May 2026, so we shipped the verified-only path first. Options when we revisit: wait for upstream to restore weights, fork and re-host weights, or evaluate alternatives (e.g. fine-tuned LLMs against the same reference dataset).
- **PyPI release** so `pip install smiles2iupac` Just Works without a checkout.
- **Re-enable the cron healthcheck workflow** now that the Space is up.

## Architecture

`src/smiles2iupac/`

| Module | Purpose |
|---|---|
| `pipeline.py` | Orchestrator — chains classify → cache → PubChem → OPSIN round-trip → enrich |
| `validator.py` | RDKit canonicalization + heavy-atom support check |
| `validator_strict.py` | Reaction/polymer rejection, salt stripping, classification |
| `cache.py` | SQLite cache at `~/.smiles2iupac/cache.db` |
| `pubchem.py` | PUG-REST client (token-bucket 5 req/s, exp backoff, InChIKey-first) |
| `opsin_check.py` | py2opsin round-trip with 14/27-char InChIKey tiering |
| `enrich.py` | InChI / InChIKey / formula / MW / SVG / CAS helpers |
| `result.py` | Pydantic Result + Source enum |
| `confidence.py` | Source → confidence tier mapping |
| `cli.py` | `s2i` Click CLI |

`app/` — Gradio UI + FastAPI mounted at `:7860`. Endpoints: `GET /health`, `GET /convert?smiles=...`, `POST /batch` (NDJSON streaming).

`deploy/` — Dockerfile (default-jre-headless + Python 3.10-slim + RDKit X11 libs) and HF Spaces deployment notes. The Space is live at <https://agwgwa-smiles2iupac.hf.space>.

`.github/workflows/` — `ci.yml` (pytest + ruff, runs on every PR). `deploy-hf.yml` and `healthcheck.yml` are committed but `workflow_dispatch`-only (manual) until an `HF_TOKEN` secret is added; they target the Space at `agwgwa/smiles2iupac`.

## Run the web app locally

```bash
uv pip install -e '.[web]'
python -m app.gradio_app
# open http://localhost:7860
```

```bash
curl 'http://localhost:7860/convert?smiles=CCO' | jq .name
# "ethanol"
```

## Use as an MCP server (Claude Desktop, Cursor, Cline)

This tool also exposes itself as a [Model Context Protocol](https://modelcontextprotocol.io) server, so MCP-aware LLM clients can call it directly. Useful when you want grounded chemistry naming inside a chat instead of letting the LLM hallucinate IUPAC names.

```bash
uv pip install -e '.[mcp]'
```

Add to Claude Desktop's `claude_desktop_config.json` (development checkout — the working configuration today):

```json
{
  "mcpServers": {
    "smiles2iupac": {
      "command": "uv",
      "args": [
        "run", "--directory", "/path/to/smiles2iupac",
        "--extra", "mcp",
        "python", "-m", "smiles2iupac.mcp_server"
      ]
    }
  }
}
```

(Restart Claude Desktop. Then ask: "What's the IUPAC name for `CC(=O)Oc1ccccc1C(=O)O`?" — Claude will call our tool and return `2-acetyloxybenzoic acid` with provenance and a verify URL.)

Once published to PyPI, the simpler form `"command": "s2i-mcp"` will work after `pip install 'smiles2iupac[mcp]'`. Not yet.

**Tools exposed:**

| Tool | Purpose |
|---|---|
| `smiles_to_iupac` | Forward conversion. Returns name + confidence + source + InChIKey + reasoning trace + PubChem verify URL |
| `iupac_to_smiles` | Reverse lookup. OPSIN first (offline, stereo-aware) → PubChem fallback (common names) |
| `classify_smiles` | Pre-flight check: is it a salt? mixture? reaction? Returns parent + counter-ions |
| `enrich_smiles` | Pure-RDKit metadata: InChI / InChIKey / formula / MW / SVG. No network. |

## Development

```bash
git clone https://github.com/gvmfhy/smiles2iupac.git
cd smiles2iupac
uv venv && uv pip install -e '.[all]'
pytest                                           # 140 tests
```

The cache lives at `~/.smiles2iupac/cache.db` and warms automatically. Wipe it any time — it'll repopulate on demand.

## License

MIT. See [LICENSE](LICENSE).

## Credits

Built on:
- [OPSIN](https://opsin.ch.cam.ac.uk/) via [py2opsin](https://pypi.org/project/py2opsin/) (Cambridge, MIT)
- [RDKit](https://www.rdkit.org/) (BSD)
- [PubChem PUG-REST](https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest) (NIH, public-domain)
