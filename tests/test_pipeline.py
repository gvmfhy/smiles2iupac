"""Tests for the conversion pipeline (offline / mocked PubChem)."""

from unittest.mock import patch

from smiles2iupac.cache import Cache
from smiles2iupac.pipeline import Pipeline
from smiles2iupac.result import Source


def _patch_pubchem(inchikey_returns=None, smiles_returns=None, side_effect=None):
    """Helper: patch BOTH InChIKey and SMILES lookup paths together."""
    return (
        patch("smiles2iupac.pipeline.iupac_via_inchikey",
              return_value=inchikey_returns, side_effect=side_effect),
        patch("smiles2iupac.pipeline.smiles_to_iupac",
              return_value=smiles_returns, side_effect=side_effect),
    )


def test_invalid_smiles_returns_error(tmp_cache: Cache):
    pipeline = Pipeline(cache=tmp_cache, use_pubchem=False)
    r = pipeline.convert("garbage")
    assert r.ok is False
    assert r.error is not None
    assert r.kind == "empty"


def test_cache_hit_short_circuits(tmp_cache: Cache):
    tmp_cache.store("CCO", "ethanol", "pubchem", 1.0)
    pipeline = Pipeline(cache=tmp_cache, use_pubchem=False)
    r = pipeline.convert("CCO")
    assert r.ok is True
    assert r.name == "ethanol"
    assert r.source == Source.PUBCHEM
    assert r.confidence == 1.0
    # Cache hits still get cheap enrichment
    assert r.inchikey is not None
    assert r.formula == "C2H6O"


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
    with patch("smiles2iupac.pipeline.iupac_via_inchikey", return_value="ethanol"), \
         patch("smiles2iupac.pipeline.smiles_to_iupac", return_value=None):
        r = pipeline.convert("CCO")
    assert r.ok is True
    assert r.name == "ethanol"
    assert r.source == Source.PUBCHEM
    assert tmp_cache.lookup("CCO") == ("ethanol", "pubchem", 1.0)


def test_pubchem_inchikey_misses_falls_back_to_smiles(tmp_cache: Cache):
    """If InChIKey lookup misses, SMILES lookup is tried."""
    pipeline = Pipeline(cache=tmp_cache, use_pubchem=True)
    with patch("smiles2iupac.pipeline.iupac_via_inchikey", return_value=None), \
         patch("smiles2iupac.pipeline.smiles_to_iupac", return_value="ethanol") as smiles_mock:
        r = pipeline.convert("CCO")
    assert r.ok is True
    assert r.name == "ethanol"
    assert smiles_mock.called


def test_pubchem_miss_no_stout(tmp_cache: Cache):
    pipeline = Pipeline(cache=tmp_cache, use_pubchem=True, use_stout=False)
    with patch("smiles2iupac.pipeline.iupac_via_inchikey", return_value=None), \
         patch("smiles2iupac.pipeline.smiles_to_iupac", return_value=None):
        r = pipeline.convert("CCC(C)(C)C(=O)O")
    assert r.ok is False
    assert "no name found" in r.error.lower()


def test_pubchem_error_does_not_crash(tmp_cache: Cache):
    from smiles2iupac.pubchem import PubChemError

    pipeline = Pipeline(cache=tmp_cache, use_pubchem=True)
    with patch("smiles2iupac.pipeline.iupac_via_inchikey",
               side_effect=PubChemError("network down")), \
         patch("smiles2iupac.pipeline.smiles_to_iupac",
               side_effect=PubChemError("network down")):
        r = pipeline.convert("CCO")
    assert r.ok is False
    assert "pubchem unavailable" in r.error


def test_reaction_smiles_rejected(tmp_cache: Cache):
    pipeline = Pipeline(cache=tmp_cache, use_pubchem=False)
    r = pipeline.convert("CCO>>CC=O")
    assert r.ok is False
    assert r.kind == "reaction"
    assert "reaction" in r.error.lower()


def test_polymer_smiles_rejected(tmp_cache: Cache):
    pipeline = Pipeline(cache=tmp_cache, use_pubchem=False)
    r = pipeline.convert("[*]CCC[*]")
    assert r.ok is False
    assert r.kind == "polymer"


def test_salt_stripping_names_parent(tmp_cache: Cache):
    """Salt input should name the parent and record the strip in warnings."""
    tmp_cache.store("CC(=O)[O-]", "acetate", "pubchem", 1.0)
    pipeline = Pipeline(cache=tmp_cache, use_pubchem=False)
    r = pipeline.convert("CC(=O)[O-].[Na+]")
    assert r.ok is True
    assert r.name == "acetate"
    assert r.kind == "salt"
    assert any("counter-ion" in w for w in r.warnings)


def test_enrichment_fields_populated_on_success(tmp_cache: Cache):
    tmp_cache.store("CCO", "ethanol", "pubchem", 1.0)
    pipeline = Pipeline(cache=tmp_cache, use_pubchem=False)
    r = pipeline.convert("CCO")
    assert r.ok is True
    assert r.inchi is not None and r.inchi.startswith("InChI=")
    assert r.inchikey is not None and len(r.inchikey) == 27
    assert r.formula == "C2H6O"
    assert r.mol_weight == 46.069
    # Opt-in fields not set by default
    assert r.structure_svg is None
    assert r.cas is None


def test_include_svg_flag_populates_svg(tmp_cache: Cache):
    tmp_cache.store("CCO", "ethanol", "pubchem", 1.0)
    pipeline = Pipeline(cache=tmp_cache, use_pubchem=False, include_svg=True)
    r = pipeline.convert("CCO")
    assert r.structure_svg is not None
    assert "<svg" in r.structure_svg


def test_stout_validated_path(tmp_cache: Cache):
    """STOUT generates a name; OPSIN round-trip confirms full match → STOUT_VALIDATED."""
    pipeline = Pipeline(cache=tmp_cache, use_pubchem=False, use_stout=True)
    fake_rt = type("RT", (), {
        "full_match": True, "skeleton_match": True, "parsed_ok": True,
    })()
    with patch("smiles2iupac.pipeline.stout_iupac", return_value="ethanol"), \
         patch("smiles2iupac.pipeline.round_trip", return_value=fake_rt):
        r = pipeline.convert("CCO")
    assert r.ok is True
    assert r.source == Source.STOUT_VALIDATED
    assert r.confidence == 0.95


def test_stout_skeleton_only_match_warns(tmp_cache: Cache):
    """OPSIN round-trip skeleton match (stereo lost) → STOUT_UNVALIDATED with warning."""
    pipeline = Pipeline(cache=tmp_cache, use_pubchem=False, use_stout=True)
    fake_rt = type("RT", (), {
        "full_match": False, "skeleton_match": True, "parsed_ok": True,
    })()
    with patch("smiles2iupac.pipeline.stout_iupac", return_value="some-name"), \
         patch("smiles2iupac.pipeline.round_trip", return_value=fake_rt):
        r = pipeline.convert("C[C@H](O)CC")
    assert r.source == Source.STOUT_UNVALIDATED
    assert any("stereo" in w.lower() for w in r.warnings)


def test_stout_no_match_low_confidence(tmp_cache: Cache):
    """OPSIN round-trip → different structure → STOUT_LOW_CONFIDENCE."""
    pipeline = Pipeline(cache=tmp_cache, use_pubchem=False, use_stout=True)
    fake_rt = type("RT", (), {
        "full_match": False, "skeleton_match": False, "parsed_ok": True,
    })()
    with patch("smiles2iupac.pipeline.stout_iupac", return_value="wrong-name"), \
         patch("smiles2iupac.pipeline.round_trip", return_value=fake_rt):
        r = pipeline.convert("CCO")
    assert r.source == Source.STOUT_LOW_CONFIDENCE
    assert r.confidence == 0.20


def test_stout_unavailable_when_opsin_missing(tmp_cache: Cache):
    """If OPSIN can't be imported, STOUT result is unvalidated."""
    from smiles2iupac.opsin_check import OpsinError

    pipeline = Pipeline(cache=tmp_cache, use_pubchem=False, use_stout=True)
    with patch("smiles2iupac.pipeline.stout_iupac", return_value="ethanol"), \
         patch("smiles2iupac.pipeline.round_trip", side_effect=OpsinError("no opsin")):
        r = pipeline.convert("CCO")
    assert r.ok is True
    assert r.source == Source.STOUT_UNVALIDATED
    assert any("opsin" in w.lower() for w in r.warnings)
