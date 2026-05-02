"""Tests for the strict SMILES validator (reaction/polymer/salt classification)."""

import pytest
from rdkit import Chem

from smiles2iupac.validator_strict import (
    Classification,
    classify,
    has_wildcards,
    is_reaction,
    strip_salts,
)


def _canon(smi: str) -> str:
    """Canonical-form helper so tests assert structural — not textual — equality."""
    return Chem.MolToSmiles(Chem.MolFromSmiles(smi), canonical=True)


# ---------------------------------------------------------------------------
# is_reaction / has_wildcards
# ---------------------------------------------------------------------------

def test_is_reaction_detects_arrow():
    assert is_reaction("CCO>>CC=O") is True


def test_is_reaction_normal_smiles_false():
    assert is_reaction("CCO") is False


def test_is_reaction_with_reagents_above_arrow():
    # Full reaction SMILES with reagents: reactants>reagents>products
    assert is_reaction("CCO.O>[Pt]>CC=O") is False  # single > only — not a reaction arrow yet
    assert is_reaction("CCO>>CC=O") is True
    assert is_reaction("CCO.[H]O[H]>>CC(=O)O") is True


def test_has_wildcards_detects_repeat_unit():
    assert has_wildcards("[*]CC[*]") is True


def test_has_wildcards_normal_smiles_false():
    assert has_wildcards("CCO") is False


def test_has_wildcards_bare_star():
    assert has_wildcards("*c1ccccc1*") is True


# ---------------------------------------------------------------------------
# strip_salts
# ---------------------------------------------------------------------------

def test_strip_salts_acetate_sodium():
    parent, counterions = strip_salts("CC(=O)[O-].[Na+]")
    assert parent == _canon("CC(=O)[O-]")
    assert counterions == [_canon("[Na+]")]


def test_strip_salts_no_salt_returns_canonical_alone():
    parent, counterions = strip_salts("CCO")
    assert parent == "CCO"
    assert counterions == []


def test_strip_salts_canonicalizes_input():
    # Non-canonical input: parent should still come back canonicalized.
    parent, counterions = strip_salts("OCC.[Cl-]")
    assert parent == _canon("CCO")
    assert counterions == [_canon("[Cl-]")]


def test_strip_salts_picks_largest_as_parent():
    # CCO (3 heavy) is larger than [K+] (1) — must be returned as parent.
    parent, counterions = strip_salts("[K+].CCO")
    assert parent == _canon("CCO")
    assert counterions == [_canon("[K+]")]


def test_strip_salts_empty_raises():
    with pytest.raises(ValueError, match="empty"):
        strip_salts("")


def test_strip_salts_unparseable_raises():
    with pytest.raises(ValueError, match="parse"):
        strip_salts("not_a_smiles")


# ---------------------------------------------------------------------------
# classify — the ten spec cases
# ---------------------------------------------------------------------------

def test_classify_empty():
    c = classify("")
    assert isinstance(c, Classification)
    assert c.kind == "empty"
    assert c.parent_smiles is None
    assert c.counterions == []
    assert c.components == []
    assert c.warnings == ["empty SMILES"]


def test_classify_whitespace_only_is_empty():
    assert classify("   ").kind == "empty"


def test_classify_reaction():
    c = classify("CCO>>CC=O")
    assert c.kind == "reaction"
    assert c.parent_smiles is None
    assert c.counterions == []
    assert c.warnings  # non-empty


def test_classify_polymer():
    c = classify("[*]CCC[*]")
    assert c.kind == "polymer"
    assert c.parent_smiles is None
    assert c.warnings


def test_classify_salt_acetate_sodium():
    c = classify("CC(=O)[O-].[Na+]")
    assert c.kind == "salt"
    assert c.parent_smiles == _canon("CC(=O)[O-]")
    assert c.counterions == [_canon("[Na+]")]
    assert c.warnings  # non-empty


def test_classify_mixture_two_organics():
    # No monoatomic counterion → mixture, not salt.
    c = classify("CCO.c1ccccc1")
    assert c.kind == "mixture"
    # Largest component is benzene (6 heavy atoms) vs ethanol (3).
    assert c.parent_smiles == _canon("c1ccccc1")
    assert c.counterions == []  # mixtures don't populate counterions
    assert c.warnings  # non-empty
    assert sorted(c.components) == sorted([_canon("CCO"), _canon("c1ccccc1")])


def test_classify_molecule():
    c = classify("CCO")
    assert c.kind == "molecule"
    assert c.parent_smiles == "CCO"
    assert c.counterions == []
    assert c.warnings == []
    assert c.components == ["CCO"]


# ---------------------------------------------------------------------------
# extra coverage — invariants worth pinning
# ---------------------------------------------------------------------------

def test_classify_unparseable_garbage_is_empty():
    # Spec: classify never raises; bad input gets kind="empty" with a warning.
    c = classify("not_a_smiles")
    assert c.kind == "empty"
    assert c.parent_smiles is None
    assert c.warnings


def test_classify_salt_components_includes_parent_and_counterions():
    c = classify("CC(=O)[O-].[Na+]")
    assert c.components == [c.parent_smiles] + c.counterions


def test_classify_salt_with_multiple_counterions():
    # Calcium diacetate: Ca2+ with 2 acetates. Largest fragment = an acetate;
    # smallest other = either another acetate (4 heavy) or Ca2+ (1, monoatomic ion).
    # Smallest is [Ca++] → classify as salt.
    c = classify("CC(=O)[O-].[Ca++].CC(=O)[O-]")
    assert c.kind == "salt"
    assert c.parent_smiles == _canon("CC(=O)[O-]")
    # 2 counterions stripped (the other acetate + the calcium)
    assert len(c.counterions) == 2
    assert _canon("[Ca++]") in c.counterions
