"""Tests for the SMILES validator."""

import csv

import pytest

from smiles2iupac.validator import (
    SMILESError,
    canonicalize,
    heavy_atom_count,
    is_supported,
)


def test_canonicalize_simple():
    assert canonicalize("CCO") == "CCO"


def test_canonicalize_strips_whitespace():
    assert canonicalize("  CCO  ") == "CCO"


def test_canonicalize_idempotent():
    once = canonicalize("c1ccccc1")
    twice = canonicalize(once)
    assert once == twice


def test_canonicalize_aromatic_form_normalized():
    kekulized = "C1=CC=CC=C1"
    aromatic = "c1ccccc1"
    assert canonicalize(kekulized) == canonicalize(aromatic)


def test_canonicalize_empty_raises():
    with pytest.raises(SMILESError, match="empty"):
        canonicalize("")


def test_canonicalize_whitespace_only_raises():
    with pytest.raises(SMILESError, match="empty"):
        canonicalize("   ")


def test_canonicalize_garbage_raises():
    with pytest.raises(SMILESError, match="could not parse"):
        canonicalize("not a smiles")


def test_canonicalize_unbalanced_raises():
    with pytest.raises(SMILESError):
        canonicalize("C(C")


def test_heavy_atom_count_basic():
    assert heavy_atom_count("CCO") == 3
    assert heavy_atom_count("c1ccccc1") == 6


def test_heavy_atom_count_invalid_returns_zero():
    assert heavy_atom_count("garbage") == 0


def test_is_supported_normal():
    ok, reason = is_supported("CCO")
    assert ok is True
    assert reason is None


def test_is_supported_too_large():
    ok, reason = is_supported("CCO", max_heavy_atoms=2)
    assert ok is False
    assert "exceeds" in reason


def test_is_supported_invalid():
    ok, reason = is_supported("garbage")
    assert ok is False
    assert "parse" in reason


def test_known_molecules_canonicalize(fixtures_dir):
    """Every fixture row canonicalizes without error and is idempotent.

    We don't pin canonical strings — RDKit's canonicalizer evolves across versions.
    Idempotence + structural equivalence (via InChIKey) is the durable invariant.
    """
    from rdkit import Chem

    with open(fixtures_dir / "known_molecules.csv") as f:
        rows = list(csv.DictReader(f))

    assert len(rows) >= 15

    for row in rows:
        once = canonicalize(row["smiles"])
        twice = canonicalize(once)
        assert once == twice, f"{row['name']}: not idempotent — {once!r} → {twice!r}"

        original_key = Chem.MolToInchiKey(Chem.MolFromSmiles(row["smiles"]))
        canon_key = Chem.MolToInchiKey(Chem.MolFromSmiles(once))
        assert original_key == canon_key, (
            f"{row['name']}: InChIKey changed during canonicalization"
        )
