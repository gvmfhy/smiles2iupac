"""Tests for the OPSIN round-trip validator.

We mock py2opsin via a fake module installed in sys.modules so the lazy import
inside `round_trip` resolves to our stub. RDKit + InChIKey comparison runs for
real — that's the part we want honest coverage of.
"""

import sys
import types
from collections.abc import Callable

import pytest

from smiles2iupac.opsin_check import OpsinError, RoundTripResult, round_trip


def _install_fake_py2opsin(
    monkeypatch: pytest.MonkeyPatch, fn: Callable[[str, str], str]
) -> None:
    """Install a fake `py2opsin` package so the lazy import inside round_trip works."""
    fake = types.ModuleType("py2opsin")
    fake.py2opsin = fn  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "py2opsin", fake)


def test_full_match_round_trip(monkeypatch: pytest.MonkeyPatch):
    """OPSIN returns the same molecule — full_match and skeleton_match both True."""
    _install_fake_py2opsin(monkeypatch, lambda name, output_format="SMILES": "CCO")

    r = round_trip("ethanol", "CCO")

    assert r.parsed_ok is True
    assert r.full_match is True
    assert r.skeleton_match is True
    assert r.back_smiles == "CCO"
    assert r.name == "ethanol"
    assert r.original_smiles == "CCO"


def test_skeleton_only_match_loses_stereo(monkeypatch: pytest.MonkeyPatch):
    """Original is (S)-2-butanol; OPSIN returns it without stereo. Block 1 matches, full does not."""
    # Original carries stereo; OPSIN returns the same skeleton without stereo.
    original = "C[C@H](O)CC"
    back = "CC(O)CC"
    _install_fake_py2opsin(monkeypatch, lambda name, output_format="SMILES": back)

    r = round_trip("butan-2-ol", original)

    assert r.parsed_ok is True
    assert r.skeleton_match is True
    assert r.full_match is False
    assert r.back_smiles == back


def test_no_match_different_molecule(monkeypatch: pytest.MonkeyPatch):
    """OPSIN returns a structurally different molecule — both matches False."""
    _install_fake_py2opsin(monkeypatch, lambda name, output_format="SMILES": "CCC")

    r = round_trip("ethanol", "CCO")

    assert r.parsed_ok is True
    assert r.skeleton_match is False
    assert r.full_match is False
    assert r.back_smiles == "CCC"


def test_parse_failure_returns_none(monkeypatch: pytest.MonkeyPatch):
    """py2opsin returns '' on parse failure → parsed_ok=False, back_smiles=None."""
    _install_fake_py2opsin(monkeypatch, lambda name, output_format="SMILES": "")

    r = round_trip("not a real name", "CCO")

    assert r.parsed_ok is False
    assert r.skeleton_match is False
    assert r.full_match is False
    assert r.back_smiles is None


def test_opsin_not_installed_raises(monkeypatch: pytest.MonkeyPatch):
    """If py2opsin isn't importable, round_trip raises OpsinError."""
    # Hide any real py2opsin and force ImportError on lazy import.
    monkeypatch.setitem(sys.modules, "py2opsin", None)

    with pytest.raises(OpsinError, match="py2opsin not installed"):
        round_trip("ethanol", "CCO")


def test_result_is_pydantic_model(monkeypatch: pytest.MonkeyPatch):
    """Smoke check: RoundTripResult round-trips through Pydantic dump/load."""
    _install_fake_py2opsin(monkeypatch, lambda name, output_format="SMILES": "CCO")

    r = round_trip("ethanol", "CCO")
    assert isinstance(r, RoundTripResult)
    dumped = r.model_dump()
    assert dumped["full_match"] is True
    assert RoundTripResult.model_validate(dumped) == r


def test_module_imports_without_py2opsin():
    """The module must import cleanly even when py2opsin isn't installed (lazy import).

    Already imported at top of file; this re-confirms the public bindings.
    """
    from smiles2iupac import opsin_check

    assert hasattr(opsin_check, "round_trip")
    assert hasattr(opsin_check, "RoundTripResult")
    assert hasattr(opsin_check, "OpsinError")
    assert hasattr(opsin_check, "parse_iupac_name")


def test_parse_iupac_name_returns_canonical(monkeypatch: pytest.MonkeyPatch):
    """parse_iupac_name returns RDKit-canonicalized SMILES from OPSIN output."""
    from smiles2iupac.opsin_check import parse_iupac_name

    # Non-canonical SMILES from OPSIN should be re-canonicalized
    _install_fake_py2opsin(monkeypatch, lambda name, output_format="SMILES": "OCC")
    assert parse_iupac_name("ethanol") == "CCO"


def test_parse_iupac_name_failure_returns_none(monkeypatch: pytest.MonkeyPatch):
    """OPSIN can't parse → returns None (not error)."""
    from smiles2iupac.opsin_check import parse_iupac_name

    _install_fake_py2opsin(monkeypatch, lambda name, output_format="SMILES": "")
    assert parse_iupac_name("gibberish") is None


def test_parse_iupac_name_unparseable_smiles_returns_none(monkeypatch: pytest.MonkeyPatch):
    """OPSIN somehow returns an invalid SMILES → returns None instead of crashing."""
    from smiles2iupac.opsin_check import parse_iupac_name

    _install_fake_py2opsin(monkeypatch, lambda name, output_format="SMILES": "not_a_smiles")
    assert parse_iupac_name("anything") is None


def test_parse_iupac_name_no_py2opsin_raises(monkeypatch: pytest.MonkeyPatch):
    """No py2opsin → OpsinError."""
    from smiles2iupac.opsin_check import parse_iupac_name

    monkeypatch.setitem(sys.modules, "py2opsin", None)
    with pytest.raises(OpsinError, match="py2opsin not installed"):
        parse_iupac_name("ethanol")
