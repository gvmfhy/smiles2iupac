"""Tests for the public reverse-lookup function (name → SMILES)."""

import sys
import types
from collections.abc import Callable

import pytest

from smiles2iupac.pipeline import lookup


def _install_fake_py2opsin(
    monkeypatch: pytest.MonkeyPatch, fn: Callable[[str, str], str]
) -> None:
    fake = types.ModuleType("py2opsin")
    fake.py2opsin = fn  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "py2opsin", fake)


def test_lookup_empty_returns_none():
    assert lookup("") is None
    assert lookup("   ") is None


def test_lookup_via_opsin_first(monkeypatch: pytest.MonkeyPatch):
    """OPSIN handles the IUPAC name; PubChem is never consulted."""
    _install_fake_py2opsin(monkeypatch, lambda name, output_format="SMILES": "CCO")

    pubchem_called = False

    def fake_pubchem(name: str) -> str | None:
        nonlocal pubchem_called
        pubchem_called = True
        return "CCO"

    monkeypatch.setattr("smiles2iupac.pipeline._pubchem_name_to_smiles", fake_pubchem)

    assert lookup("ethanol") == "CCO"
    assert pubchem_called is False, "OPSIN succeeded; PubChem should not be called"


def test_lookup_falls_back_to_pubchem(monkeypatch: pytest.MonkeyPatch):
    """OPSIN can't parse common name → PubChem is tried."""
    _install_fake_py2opsin(monkeypatch, lambda name, output_format="SMILES": "")

    monkeypatch.setattr(
        "smiles2iupac.pipeline._pubchem_name_to_smiles",
        lambda n: "OCC",  # non-canonical PubChem SMILES
    )

    # Result should be RDKit-canonical (CCO), not PubChem's literal output (OCC)
    assert lookup("aspirin") == "CCO"


def test_lookup_pubchem_disabled(monkeypatch: pytest.MonkeyPatch):
    """When use_pubchem=False, OPSIN-failure means None (no fallback)."""
    _install_fake_py2opsin(monkeypatch, lambda name, output_format="SMILES": "")

    pubchem_called = False

    def fake_pubchem(name: str) -> str | None:
        nonlocal pubchem_called
        pubchem_called = True
        return "CCO"

    monkeypatch.setattr("smiles2iupac.pipeline._pubchem_name_to_smiles", fake_pubchem)

    assert lookup("aspirin", use_pubchem=False) is None
    assert pubchem_called is False


def test_lookup_no_opsin_falls_through(monkeypatch: pytest.MonkeyPatch):
    """OPSIN not installed → silently fall through to PubChem (don't crash)."""
    monkeypatch.setitem(sys.modules, "py2opsin", None)
    monkeypatch.setattr(
        "smiles2iupac.pipeline._pubchem_name_to_smiles",
        lambda n: "CCO",
    )

    assert lookup("ethanol") == "CCO"


def test_lookup_pubchem_error_returns_none(monkeypatch: pytest.MonkeyPatch):
    """Network error at PubChem → None (don't bubble up to caller)."""
    from smiles2iupac.pubchem import PubChemError

    _install_fake_py2opsin(monkeypatch, lambda name, output_format="SMILES": "")

    def boom(name: str) -> str | None:
        raise PubChemError("network down")

    monkeypatch.setattr("smiles2iupac.pipeline._pubchem_name_to_smiles", boom)

    assert lookup("aspirin") is None


def test_lookup_pubchem_returns_invalid_smiles(monkeypatch: pytest.MonkeyPatch):
    """PubChem returns garbage that RDKit can't parse → None."""
    _install_fake_py2opsin(monkeypatch, lambda name, output_format="SMILES": "")
    monkeypatch.setattr(
        "smiles2iupac.pipeline._pubchem_name_to_smiles",
        lambda n: "not_a_real_smiles",
    )

    assert lookup("foo") is None
