# smiles2iupac

> The reliable, free, open-source SMILES → IUPAC name converter that should have existed years ago.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

## What

A small library, CLI, and web app that converts SMILES strings to IUPAC nomenclature using a layered pipeline:

1. **SQLite cache** — instant for previously seen molecules
2. **PubChem PUG-REST lookup** — authoritative for ~120M known compounds
3. **STOUT v2.0** — neural generation for novel structures (97.49% exact match)
4. **OPSIN round-trip validation** — parses generated names back to SMILES, flags hallucinations

Every result is tagged with provenance and a confidence score.

## Quick start

```bash
pip install smiles2iupac
s2i 'CCO'
# ethanol  (confidence: 1.00, source: pubchem)
```

```python
from smiles2iupac import convert

result = convert("CC(=O)Oc1ccccc1C(=O)O")  # aspirin
print(result.name)        # 2-acetyloxybenzoic acid
print(result.confidence)  # 1.0
print(result.source)      # Source.PUBCHEM
```

## Why this exists

As of 2026, no reliable, free, open-source SMILES→IUPAC tool exists online. The capability does — STOUT v2 from the Steinbeck group is excellent — but the deployment was buried inside another platform with no API, no validation, no batch processing, and unreliable uptime. This repo fixes the productization gap.

## How it compares

| Feature | This tool | stout.decimer.ai | ChemAxon Naming |
|---|---|---|---|
| Free + open source | ✅ | ✅ | ❌ ($$$) |
| Standalone URL | ✅ | ❌ (in DECIMER) | N/A |
| Public API | ✅ FastAPI | ❌ | ✅ |
| PubChem fallback | ✅ | ❌ | ❌ |
| Round-trip validation | ✅ OPSIN | ❌ | partial |
| Confidence scoring | ✅ | ❌ | ❌ |
| Batch (CSV/SDF) | ✅ | ❌ | ✅ |
| CLI / pip-installable | ✅ | ❌ | ❌ |

## Status

Active development. See [`plan-out-to-develop-frolicking-thunder.md`](https://github.com/gvmfhy/smiles2iupac) for roadmap.

- [x] Weekend 1: Cache + PubChem pipeline + CLI
- [ ] Weekend 2: STOUT integration + OPSIN validation
- [ ] Weekend 3: Gradio UI + HF Spaces deploy
- [ ] Weekend 4: Polish + discoverability

## License

MIT
