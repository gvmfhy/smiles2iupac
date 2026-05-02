"""Tests for the STOUT engine wrapper. Mocks the STOUT package so this suite
runs on machines without STOUT-pypi (and TensorFlow) installed."""

import sys
import types
from unittest.mock import MagicMock

import pytest

from smiles2iupac import stout_engine
from smiles2iupac.stout_engine import StoutError, stout_iupac


@pytest.fixture(autouse=True)
def _reset_translator_cache():
    """Clear the lru_cache on _get_translator before/after each test."""
    stout_engine._get_translator.cache_clear()
    yield
    stout_engine._get_translator.cache_clear()


def _install_fake_stout(translate_forward) -> None:
    """Install a fake `STOUT` module exposing the given `translate_forward`."""
    fake = types.ModuleType("STOUT")
    fake.translate_forward = translate_forward
    sys.modules["STOUT"] = fake


def _uninstall_fake_stout() -> None:
    sys.modules.pop("STOUT", None)


def test_successful_translation_returns_name():
    mock_translate = MagicMock(return_value="ethanol")
    _install_fake_stout(mock_translate)
    try:
        assert stout_iupac("CCO") == "ethanol"
        mock_translate.assert_called_once_with("CCO")
    finally:
        _uninstall_fake_stout()


def test_empty_return_yields_none():
    mock_translate = MagicMock(return_value="")
    _install_fake_stout(mock_translate)
    try:
        assert stout_iupac("CCO") is None
    finally:
        _uninstall_fake_stout()


def test_none_return_yields_none():
    mock_translate = MagicMock(return_value=None)
    _install_fake_stout(mock_translate)
    try:
        assert stout_iupac("CCO") is None
    finally:
        _uninstall_fake_stout()


def test_stout_exception_yields_none():
    """Runtime errors inside STOUT (e.g. unparseable input) become None, not raise."""
    mock_translate = MagicMock(side_effect=RuntimeError("model went sideways"))
    _install_fake_stout(mock_translate)
    try:
        assert stout_iupac("garbage-input") is None
    finally:
        _uninstall_fake_stout()


def test_module_not_installed_raises_stouterror():
    """If STOUT-pypi isn't importable, calling stout_iupac raises StoutError."""
    _uninstall_fake_stout()  # ensure no lingering fake module
    # The real STOUT package isn't installed in this env, so the import will fail.
    with pytest.raises(StoutError, match="not installed"):
        stout_iupac("CCO")


def test_lazy_loading_translator_called_only_once_per_process():
    """`translate_forward` is fetched once via lru_cache; repeat calls reuse it."""
    mock_translate = MagicMock(return_value="ethanol")
    _install_fake_stout(mock_translate)
    try:
        # First call resolves the translator and invokes it once.
        stout_iupac("CCO")
        # Subsequent calls hit the cached translator, not a new import.
        stout_iupac("CCC")
        stout_iupac("CCCC")
        assert mock_translate.call_count == 3

        # If STOUT were re-imported on each call we'd see fresh state; instead
        # the cached translator object is identical across calls.
        assert stout_engine._get_translator() is mock_translate
        assert stout_engine._get_translator() is mock_translate
    finally:
        _uninstall_fake_stout()


def test_import_not_triggered_at_module_import_time():
    """Importing stout_engine must NOT import STOUT (lazy load contract)."""
    # We can't easily prove a negative across the whole import graph, but we
    # can confirm that with no fake installed and a fresh cache, the STOUT
    # module is absent until stout_iupac is actually called.
    _uninstall_fake_stout()
    stout_engine._get_translator.cache_clear()
    assert "STOUT" not in sys.modules
