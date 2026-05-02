# Contributing

Thanks for thinking about contributing! This is an alpha-stage project — feedback on real chemistry use cases, bug reports, and PRs are all welcome.

## Quick start

```bash
git clone https://github.com/gvmfhy/smiles2iupac.git
cd smiles2iupac
uv venv && uv pip install -e '.[all]'        # full dev environment
.venv/bin/pytest -q                          # 140 tests should pass
.venv/bin/python -m ruff check src tests app scripts
```

The `[all]` extras pull in everything: OPSIN (Java required — `brew install openjdk`), Gradio + FastAPI for the web app, MCP server, and dev tools (pytest, pytest-asyncio, ruff). STOUT v2 only installs on Python 3.10/3.11 (TF version pin); the pipeline degrades gracefully without it.

## What kind of contribution helps most

**Bug reports for wrong/missing names.** If you give the tool a SMILES and it returns a name that's wrong, missing, or confusing — please open an issue. There's a "Naming issue" template that prompts for the SMILES + expected name + what you got. These are the most actionable reports because the verify URL in every result lets us reproduce instantly.

**Edge case test fixtures.** The `tests/fixtures/known_molecules.csv` and `tests/fixtures/accuracy_dataset.csv` files are the canonical test corpus. PRs that add molecules from a category we under-cover (carbohydrates, organometallics, peptides) help measurable accuracy.

**STOUT-path improvements.** The `_stout_layer` in `pipeline.py` and the OPSIN round-trip tier mapping in `opsin_check.py` are where novel-structure naming happens. Right now they're behind a flag and validated mostly via mocks. Real-world coverage data here is gold.

**Documentation.** If you read something in the README and thought "wait, that's not what happened when I tried it" — please open an issue or PR. The previous round of doc cleanup found ~24 places where claims didn't match reality; we expect there are more.

## Pull request flow

1. Fork → branch → make changes → push to your fork
2. Run `pytest -q` — must pass
3. Run `ruff check src tests app scripts` — must be clean
4. If you touched the pipeline, also run `pytest tests/test_accuracy_offline.py -v -s` and confirm Tier 2 didn't regress (CI will fail-fast on >1pp drop)
5. Open the PR — describe what changed and what test category it strengthens

## What's the bar for merge

- All tests pass (140+)
- Ruff clean
- New behavior has a test pinning it
- Public-facing changes (CLI flags, `Result` fields, MCP tool signatures) are documented in README
- Commit messages explain the *why*, not just the *what*

## Code style

- `ruff` enforces style; line length 100, target Python 3.10
- Type hints required on public functions (`Pipeline.convert`, `lookup`, etc.)
- `Result` is a Pydantic v2 model — extend it via `Field(...)` or `@computed_field`, not by attaching attrs
- New PubChem calls go through `pubchem._get` so they pick up the rate limiter + retry
- New tools that need py2opsin must use the `lazy import + OpsinError` pattern in `opsin_check.py`

## Reporting bugs

Use the issue templates — they prompt for the inputs that make a bug actionable. The most useful single piece of info is the SMILES that misbehaved + what the verify URL on PubChem actually shows.

## Questions

Open a Discussion or an issue — there are no dumb questions about chemistry, even if you're sure you should know the answer.
