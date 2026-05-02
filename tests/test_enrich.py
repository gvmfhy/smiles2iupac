"""Tests for the enrichment helpers (RDKit-only locally; PubChem mocked)."""

import re
from unittest.mock import patch

import pytest

from smiles2iupac.enrich import (
    formula,
    inchi,
    inchikey,
    mol_weight,
    pubchem_cas,
    structure_svg,
)

INCHIKEY_RE = re.compile(r"^[A-Z]{14}-[A-Z]{10}-[A-Z]$")


def test_inchi_ethanol_starts_with_standard_prefix():
    """InChI canonical string for ethanol — RDKit-version-tolerant."""
    s = inchi("CCO")
    assert s.startswith("InChI=1S/")
    assert "C2H6O" in s


def test_inchikey_ethanol_format_and_known_value():
    key = inchikey("CCO")
    assert len(key) == 27
    assert INCHIKEY_RE.match(key) is not None
    # InChIKey is structurally derived and stable across RDKit versions.
    assert key == "LFQSCWFLJHTTHZ-UHFFFAOYSA-N"


def test_formula_acetic_acid_hill_notation():
    assert formula("CC(=O)O") == "C2H4O2"


def test_formula_ethanol():
    assert formula("CCO") == "C2H6O"


def test_mol_weight_ethanol():
    assert mol_weight("CCO") == pytest.approx(46.07, abs=0.01)


def test_structure_svg_returns_valid_svg():
    svg = structure_svg("CCO")
    assert "<svg" in svg
    assert "</svg>" in svg
    assert len(svg) > 100


def test_structure_svg_respects_size():
    svg = structure_svg("CCO", size=150)
    assert "<svg" in svg
    assert "</svg>" in svg


def test_inchi_bad_smiles_raises():
    with pytest.raises(ValueError, match="could not parse"):
        inchi("garbage")


def test_inchikey_bad_smiles_raises():
    with pytest.raises(ValueError, match="could not parse"):
        inchikey("garbage")


def test_formula_bad_smiles_raises():
    with pytest.raises(ValueError, match="could not parse"):
        formula("garbage")


def test_mol_weight_bad_smiles_raises():
    with pytest.raises(ValueError, match="could not parse"):
        mol_weight("garbage")


def test_structure_svg_bad_smiles_raises():
    with pytest.raises(ValueError, match="could not parse"):
        structure_svg("garbage")


def test_pubchem_cas_extracts_first_cas_shaped_string():
    """Mocked PubChem response containing a CAS-shaped RegistryID."""
    sample = {
        "InformationList": {
            "Information": [
                {
                    "CID": 702,
                    "RegistryID": [
                        "EINECS 200-578-6",
                        "64-17-5",
                        "MFCD00003568",
                    ],
                }
            ]
        }
    }
    with patch("smiles2iupac.enrich._get", return_value=sample):
        assert pubchem_cas("CCO") == "64-17-5"


def test_pubchem_cas_returns_none_when_no_cas_present():
    sample = {
        "InformationList": {
            "Information": [
                {"CID": 1, "RegistryID": ["EINECS 200-578-6", "MFCD00003568"]}
            ]
        }
    }
    with patch("smiles2iupac.enrich._get", return_value=sample):
        assert pubchem_cas("CCO") is None


def test_pubchem_cas_returns_none_on_404():
    with patch("smiles2iupac.enrich._get", return_value=None):
        assert pubchem_cas("CCO") is None


def test_pubchem_cas_returns_none_on_network_error():
    from smiles2iupac.pubchem import PubChemError

    with patch("smiles2iupac.enrich._get", side_effect=PubChemError("network down")):
        assert pubchem_cas("CCO") is None


def test_pubchem_cas_returns_none_on_malformed_payload():
    """Missing keys / unexpected shape — must not crash."""
    with patch("smiles2iupac.enrich._get", return_value={"weird": "shape"}):
        assert pubchem_cas("CCO") is None
