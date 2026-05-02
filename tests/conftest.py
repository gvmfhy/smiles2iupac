"""Shared pytest fixtures."""

from pathlib import Path

import pytest

from smiles2iupac.cache import Cache


@pytest.fixture
def tmp_cache(tmp_path: Path) -> Cache:
    return Cache(tmp_path / "test.db")


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"
