"""Tests for the MCP server (offline / mocked PubChem).

Verifies all 4 tools are registered with the FastMCP instance and that each
routes correctly through the MCP call_tool protocol. PubChem is mocked at
the pipeline level so tests don't hit the network.
"""

from __future__ import annotations

import json

import pytest

# Skip the whole module if mcp isn't installed (it's an optional extra).
pytest.importorskip("mcp")

from smiles2iupac.mcp_server import mcp  # noqa: E402


@pytest.mark.asyncio
async def test_all_four_tools_registered():
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    assert names == {"smiles_to_iupac", "iupac_to_smiles", "classify_smiles", "enrich_smiles"}


@pytest.mark.asyncio
async def test_smiles_to_iupac_returns_full_result():
    """Cache-hit path so no PubChem call is made."""
    # Pre-warm via a direct pipeline.cache write
    from smiles2iupac.mcp_server import _pipeline
    _pipeline.cache.store("CCO", "ethanol", "pubchem", 1.0)

    parts = await mcp.call_tool("smiles_to_iupac", {"smiles": "CCO"})
    # FastMCP returns (content_list, structured_dict). Some versions return
    # just the content list. We only need the content list either way.
    content = parts[0] if isinstance(parts, tuple) else parts

    # Content always includes a TextContent with JSON-encoded result
    assert content
    text = content[0].text if hasattr(content[0], "text") else content[0]
    payload = json.loads(text) if isinstance(text, str) else text

    assert payload["name"] == "ethanol"
    assert payload["confidence"] == 1.0
    assert payload["inchikey"] == "LFQSCWFLJHTTHZ-UHFFFAOYSA-N"
    assert payload["pubchem_url"].startswith("https://pubchem.ncbi.nlm.nih.gov/")
    assert isinstance(payload["trace"], list)
    assert payload["trace"]  # non-empty


@pytest.mark.asyncio
async def test_smiles_to_iupac_handles_salt_with_warning():
    from smiles2iupac.mcp_server import _pipeline
    _pipeline.cache.store("CC(=O)[O-]", "acetate", "pubchem", 1.0)

    parts = await mcp.call_tool("smiles_to_iupac", {"smiles": "CC(=O)[O-].[Na+]"})
    content = parts[0] if isinstance(parts, tuple) else parts
    payload = json.loads(content[0].text)
    assert payload["name"] == "acetate"
    assert payload["kind"] == "salt"
    assert any("counter-ion" in w for w in payload["warnings"])
    # Trace must explain what happened — that's the whole transparency point
    assert any("salt" in s.lower() and "[Na+]" in s for s in payload["trace"])


@pytest.mark.asyncio
async def test_classify_smiles_reaction():
    parts = await mcp.call_tool("classify_smiles", {"smiles": "CCO>>CC=O"})
    content = parts[0] if isinstance(parts, tuple) else parts
    payload = json.loads(content[0].text)
    assert payload["kind"] == "reaction"
    assert payload["parent_smiles"] is None


@pytest.mark.asyncio
async def test_enrich_smiles_pure_rdkit():
    """Enrich path makes no network call — should work without any mocking."""
    parts = await mcp.call_tool("enrich_smiles", {"smiles": "CCO"})
    content = parts[0] if isinstance(parts, tuple) else parts
    payload = json.loads(content[0].text)
    assert payload["formula"] == "C2H6O"
    assert payload["inchikey"] == "LFQSCWFLJHTTHZ-UHFFFAOYSA-N"
    assert payload["mol_weight"] == pytest.approx(46.07, abs=0.01)


@pytest.mark.asyncio
async def test_enrich_smiles_bad_input_returns_error():
    parts = await mcp.call_tool("enrich_smiles", {"smiles": "garbage"})
    content = parts[0] if isinstance(parts, tuple) else parts
    payload = json.loads(content[0].text)
    assert "error" in payload


@pytest.mark.asyncio
async def test_iupac_to_smiles_via_pubchem(monkeypatch):
    """OPSIN fails on common name → PubChem fallback returns SMILES."""
    monkeypatch.setattr("smiles2iupac.pipeline._pubchem_name_to_smiles",
                        lambda n: "CCO")
    parts = await mcp.call_tool("iupac_to_smiles", {"name": "ethyl alcohol"})
    content = parts[0] if isinstance(parts, tuple) else parts
    payload = json.loads(content[0].text)
    # Result should be canonical SMILES (RDKit-canonicalized)
    assert payload["smiles"] == "CCO"
    assert payload["name"] == "ethyl alcohol"


@pytest.mark.asyncio
async def test_iupac_to_smiles_no_resolution(monkeypatch):
    monkeypatch.setattr("smiles2iupac.pipeline._pubchem_name_to_smiles",
                        lambda n: None)
    # Patch OPSIN to also fail
    import sys
    monkeypatch.setitem(sys.modules, "py2opsin", None)
    parts = await mcp.call_tool("iupac_to_smiles", {"name": "definitely-not-a-real-chemical-zzz"})
    content = parts[0] if isinstance(parts, tuple) else parts
    payload = json.loads(content[0].text)
    assert payload["smiles"] is None
    assert "error" in payload
