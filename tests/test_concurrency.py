"""Concurrency safety tests for the cache, rate limiter, and shared Pipeline.

These pin three race conditions surfaced in code review:
1. Pipeline flag flipping under concurrent FastAPI/Gradio requests
2. SQLite cache concurrent writes/reads
3. Rate limiter concurrent token decrements
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from smiles2iupac.cache import Cache
from smiles2iupac.pipeline import Pipeline
from smiles2iupac.pubchem import _RateLimiter
from smiles2iupac.result import Result, Source


def test_cache_concurrent_writes_and_reads(tmp_path: Path):
    """100 concurrent store/lookup pairs from 8 threads must not crash or corrupt."""
    cache = Cache(tmp_path / "concurrent.db")
    n = 100

    def store_then_lookup(i: int) -> tuple[str, str]:
        key = f"smiles_{i}"
        cache.store(key, f"name_{i}", "pubchem", 1.0)
        result = cache.lookup(key)
        return (key, result[0] if result else "MISSING")

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(store_then_lookup, range(n)))

    # Every store must be readable; no entry should be lost
    for key, name in results:
        assert name == key.replace("smiles_", "name_"), f"Lost or corrupted: {key} → {name}"
    assert cache.size() == n


def test_rate_limiter_concurrent_acquires_dont_overshoot():
    """The token bucket must not let multiple threads pass when only 1 token is available."""
    limiter = _RateLimiter(rate=10.0)
    # Drain all tokens
    for _ in range(int(limiter.rate)):
        limiter.acquire()
    # Now try to acquire 5 more from 5 threads simultaneously — they should
    # serialize (each waits ~0.1s), not all fire at once.
    import time
    start = time.monotonic()
    barrier = threading.Barrier(5)

    def go():
        barrier.wait()  # Release all 5 simultaneously
        limiter.acquire()

    with ThreadPoolExecutor(max_workers=5) as ex:
        list(ex.map(lambda _: go(), range(5)))
    elapsed = time.monotonic() - start
    # 5 acquires at 10/s = 0.5s minimum if properly serialized.
    # If the lock is missing, all 5 race past the token check and elapsed ≈ 0.
    assert elapsed >= 0.4, f"Rate limiter raced: 5 acquires took only {elapsed:.3f}s"


def test_pipeline_concurrent_calls_dont_pollute_flags(tmp_path: Path):
    """Per-call flags must NEVER bleed across concurrent convert() calls.

    Half the threads ask for SVG, half don't. Without per-call kwargs
    (mutating instance state instead), the result would be that some
    no-SVG callers receive an SVG anyway, or vice versa.
    """
    cache = Cache(tmp_path / "concurrent_pipeline.db")
    cache.store("CCO", "ethanol", "pubchem", 1.0)
    pipeline = Pipeline(
        cache=cache, use_pubchem=False,
        include_svg=False,  # instance default: OFF
    )

    def convert(i: int) -> tuple[int, bool]:
        # Half want SVG; half don't
        want_svg = (i % 2 == 0)
        r = pipeline.convert("CCO", include_svg=want_svg)
        got_svg = r.structure_svg is not None
        return (want_svg, got_svg)

    with ThreadPoolExecutor(max_workers=16) as ex:
        results = list(ex.map(convert, range(200)))

    # Every caller must get exactly what they asked for
    mismatches = [(w, g) for (w, g) in results if w != g]
    assert not mismatches, (
        f"{len(mismatches)} of 200 concurrent calls received the wrong "
        f"include_svg result — instance state is bleeding across requests"
    )


def test_api_concurrent_requests_dont_race(tmp_path: Path):
    """Hit the live FastAPI app with 50 mixed-flag requests on a threadpool.

    Mocks pipeline.convert so we don't hit PubChem; the goal is to validate
    that the API layer passes flags through correctly under concurrency,
    not to test PubChem behavior.
    """
    from fastapi.testclient import TestClient

    from app.api import app

    def fake_convert(smiles: str, *, include_svg: bool = False, **_) -> Result:
        # Echo back what we got — the test asserts these match the request flags
        return Result(
            smiles=smiles,
            canonical_smiles=smiles,
            name="ethanol",
            confidence=1.0,
            source=Source.PUBCHEM,
            structure_svg="<svg/>" if include_svg else None,
            inchikey="LFQSCWFLJHTTHZ-UHFFFAOYSA-N",
            formula="C2H6O",
            mol_weight=46.069,
        )

    client = TestClient(app)

    with patch("app.api.pipeline.convert", side_effect=fake_convert):
        def hit(i: int) -> tuple[bool, bool]:
            want = (i % 2 == 0)
            r = client.get("/convert", params={"smiles": "CCO", "include_svg": str(want).lower()})
            assert r.status_code == 200
            got = r.json()["structure_svg"] is not None
            return (want, got)

        with ThreadPoolExecutor(max_workers=10) as ex:
            results = list(ex.map(hit, range(50)))

    mismatches = [r for r in results if r[0] != r[1]]
    assert not mismatches, (
        f"{len(mismatches)} of 50 concurrent API requests got the wrong SVG "
        f"flag — pipeline state is racing across requests"
    )
