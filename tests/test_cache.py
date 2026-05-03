"""Tests for the SQLite cache."""

from smiles2iupac.cache import Cache


def test_lookup_miss_returns_none(tmp_cache: Cache):
    assert tmp_cache.lookup("CCO") is None


def test_store_and_lookup(tmp_cache: Cache):
    tmp_cache.store("CCO", "ethanol", "pubchem", 1.0)
    assert tmp_cache.lookup("CCO") == ("ethanol", "pubchem", 1.0)


def test_overwrite_replaces_existing(tmp_cache: Cache):
    tmp_cache.store("CCO", "ethanol", "pubchem", 1.0)
    tmp_cache.store("CCO", "ethyl alcohol", "cache", 0.95)
    assert tmp_cache.lookup("CCO") == ("ethyl alcohol", "cache", 0.95)


def test_size_counter(tmp_cache: Cache):
    assert tmp_cache.size() == 0
    tmp_cache.store("CCO", "ethanol", "pubchem", 1.0)
    tmp_cache.store("CC", "ethane", "pubchem", 1.0)
    assert tmp_cache.size() == 2


def test_persistence_across_instances(tmp_path):
    db = tmp_path / "persist.db"
    c1 = Cache(db)
    c1.store("CCO", "ethanol", "pubchem", 1.0)
    c1.close()

    c2 = Cache(db)
    assert c2.lookup("CCO") == ("ethanol", "pubchem", 1.0)
    c2.close()


def test_context_manager(tmp_path):
    db = tmp_path / "ctx.db"
    with Cache(db) as cache:
        cache.store("CCO", "ethanol", "pubchem", 1.0)
        assert cache.size() == 1
