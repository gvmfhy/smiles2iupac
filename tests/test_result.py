"""Tests for the Result type."""

from smiles2iupac.result import Result, Source


def test_default_result_is_failed():
    r = Result(smiles="CCO")
    assert r.ok is False
    assert r.confidence == 0.0
    assert r.source == Source.NONE


def test_successful_result():
    r = Result(
        smiles="CCO",
        canonical_smiles="CCO",
        name="ethanol",
        confidence=1.0,
        source=Source.PUBCHEM,
    )
    assert r.ok is True
    assert "ethanol" in str(r)
    assert "pubchem" in str(r)


def test_error_result():
    r = Result(smiles="bad", error="could not parse")
    assert r.ok is False
    assert "could not parse" in str(r)


def test_confidence_clamping():
    """Pydantic should reject out-of-range confidence."""
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Result(smiles="CCO", confidence=1.5)
    with pytest.raises(ValidationError):
        Result(smiles="CCO", confidence=-0.1)
