"""Tests for the conversion pipeline (offline / mocked PubChem)."""

from unittest.mock import patch

from smiles2iupac.cache import Cache
from smiles2iupac.pipeline import Pipeline
from smiles2iupac.result import Source


def test_invalid_smiles_returns_error(tmp_cache: Cache):
    pipeline = Pipeline(cache=tmp_cache, use_pubchem=False)
    r = pipeline.convert("garbage")
    assert r.ok is False
    assert r.error is not None


def test_cache_hit_short_circuits(tmp_cache: Cache):
    tmp_cache.store("CCO", "ethanol", "pubchem", 1.0)
    pipeline = Pipeline(cache=tmp_cache, use_pubchem=False)
    r = pipeline.convert("CCO")
    assert r.ok is True
    assert r.name == "ethanol"
    assert r.source == Source.PUBCHEM
    assert r.confidence == 1.0


def test_canonicalization_before_cache_hit(tmp_cache: Cache):
    """Cache stores canonical form; lookup with non-canonical input still hits."""
    tmp_cache.store("c1ccccc1", "benzene", "pubchem", 1.0)
    pipeline = Pipeline(cache=tmp_cache, use_pubchem=False)
    r = pipeline.convert("C1=CC=CC=C1")
    assert r.ok is True
    assert r.name == "benzene"


def test_pubchem_disabled_misses_cleanly(tmp_cache: Cache):
    pipeline = Pipeline(cache=tmp_cache, use_pubchem=False)
    r = pipeline.convert("CCO")
    assert r.ok is False
    assert "pubchem" in r.error.lower() or "not enabled" in r.error.lower()


def test_pubchem_hit_caches(tmp_cache: Cache):
    pipeline = Pipeline(cache=tmp_cache, use_pubchem=True)
    with patch("smiles2iupac.pipeline.smiles_to_iupac", return_value="ethanol"):
        r = pipeline.convert("CCO")
    assert r.ok is True
    assert r.name == "ethanol"
    assert r.source == Source.PUBCHEM
    assert tmp_cache.lookup("CCO") == ("ethanol", "pubchem", 1.0)


def test_pubchem_miss_no_stout(tmp_cache: Cache):
    pipeline = Pipeline(cache=tmp_cache, use_pubchem=True, use_stout=False)
    with patch("smiles2iupac.pipeline.smiles_to_iupac", return_value=None):
        r = pipeline.convert("CCC(C)(C)C(=O)O")
    assert r.ok is False


def test_pubchem_error_does_not_crash(tmp_cache: Cache):
    from smiles2iupac.pubchem import PubChemError

    pipeline = Pipeline(cache=tmp_cache, use_pubchem=True)
    with patch(
        "smiles2iupac.pipeline.smiles_to_iupac", side_effect=PubChemError("network down")
    ):
        r = pipeline.convert("CCO")
    assert r.ok is False
    assert "pubchem unavailable" in r.error
