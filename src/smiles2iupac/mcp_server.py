"""MCP (Model Context Protocol) server exposing smiles2iupac as tools.

Lets MCP-aware LLM clients (Claude Desktop, Cursor, Cline, Continue, etc.)
call our pipeline as a tool. The LLM gets grounded chemistry naming on demand
instead of hallucinating IUPAC names.

Tools exposed:
    smiles_to_iupac    forward conversion (the main one) — returns name +
                       provenance + reasoning trace + verify URL
    iupac_to_smiles    reverse lookup — common or systematic name → SMILES
    classify_smiles    pre-flight check — is this a salt? a reaction?
                       a polymer? what's the parent?
    enrich_smiles      structural metadata only — InChI/InChIKey/formula/MW
                       (no naming, no network if you skip CAS)

Run as a stdio server (the standard MCP transport for local servers):

    python -m smiles2iupac.mcp_server
    # or after `uv pip install -e '.[mcp]'`:
    s2i-mcp

The package is not yet on PyPI. The working Claude Desktop config today uses
the development checkout via uv:

    {
      "mcpServers": {
        "smiles2iupac": {
          "command": "uv",
          "args": [
            "run", "--directory", "/path/to/smiles2iupac",
            "--extra", "mcp",
            "python", "-m", "smiles2iupac.mcp_server"
          ]
        }
      }
    }
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from smiles2iupac import __version__
from smiles2iupac import enrich as _enrich
from smiles2iupac import lookup as _lookup
from smiles2iupac.pipeline import Pipeline
from smiles2iupac.validator import canonicalize
from smiles2iupac.validator_strict import classify as _classify

mcp = FastMCP("smiles2iupac")
# Set the underlying Server's version so the initialize handshake reports
# OUR package version, not the MCP SDK version (which is what gets returned
# when this attribute is None — e.g. "1.27.0" from `importlib.metadata` on
# the `mcp` distribution itself, which would mislead clients).
mcp._mcp_server.version = __version__

# Shared pipeline so the SQLite cache warms up across calls within a session.
# Per-call kwargs (include_svg, fetch_synonyms) are passed at convert time, not
# mutated on the instance — same race-condition-safe pattern as the FastAPI app.
_pipeline = Pipeline(use_pubchem=True, use_stout=False)


@mcp.tool()
def smiles_to_iupac(
    smiles: str,
    include_svg: bool = False,
    fetch_synonyms: bool = False,
) -> dict:
    """Convert a SMILES chemical structure to its IUPAC name.

    Args:
        smiles: SMILES string (e.g. "CCO", "CC(=O)Oc1ccccc1C(=O)O").
            Handles salts (strips counter-ions, names the parent), mixtures
            (names the largest component), and stereochemistry. Reactions
            (>>) and polymer/wildcard SMILES are rejected with a clear error.
        include_svg: If True, include a structure SVG render in the result.
            Off by default (~2KB per call).
        fetch_synonyms: If True, include common-name synonyms from PubChem.
            Off by default (extra request per call).

    Returns:
        Result dict with: name, confidence (0-1), source (pubchem|cache|stout
        variants), canonical_smiles, inchi, inchikey, formula, mol_weight,
        kind (molecule|salt|mixture|...), warnings, trace (step-by-step
        pipeline reasoning), pubchem_url (one-click verify link), error.

    Examples:
        smiles_to_iupac("CCO") → {"name": "ethanol", "confidence": 1.0, ...}
        smiles_to_iupac("CC(=O)[O-].[Na+]") → {"name": "acetate", "kind": "salt",
            "warnings": ["stripped 1 counter-ion"], "trace": [...]}
    """
    result = _pipeline.convert(
        smiles, include_svg=include_svg, fetch_synonyms=fetch_synonyms
    )
    return result.model_dump(mode="json")


@mcp.tool()
def iupac_to_smiles(name: str, use_pubchem: bool = True) -> dict:
    """Reverse lookup — chemical name to canonical SMILES.

    Tries OPSIN first (rigorous IUPAC parser, no network call, stereo-aware).
    Falls back to PubChem's name index for common names like "aspirin" or
    "caffeine" that aren't formal IUPAC.

    Args:
        name: Chemical name. IUPAC ("(2S)-2-aminopropanoic acid"), common
            ("aspirin"), or trivial — both paths are tried.
        use_pubchem: If False, only OPSIN is used (offline mode).

    Returns:
        Dict with: name (echo), smiles (RDKit-canonical) or None, source
        (opsin|pubchem|none).
    """
    smi = _lookup(name, use_pubchem=use_pubchem)
    if smi is None:
        return {"name": name, "smiles": None, "source": "none",
                "error": "could not resolve name via OPSIN or PubChem"}
    return {"name": name, "smiles": smi, "source": "resolved"}


@mcp.tool()
def classify_smiles(smiles: str) -> dict:
    """Classify a SMILES without naming it — pre-flight inspection.

    Useful for routing: tells you whether the input is a single molecule, a
    salt (and which component is the parent), a mixture, a reaction (which
    we reject), or polymer notation (also rejected). Pure RDKit, no network.

    Args:
        smiles: SMILES string to inspect.

    Returns:
        Dict with: kind (molecule|salt|mixture|reaction|polymer|empty),
        parent_smiles, counterions list, components list, warnings list.
    """
    return _classify(smiles).model_dump(mode="json")


@mcp.tool()
def enrich_smiles(smiles: str, include_svg: bool = False) -> dict:
    """Structural metadata for a SMILES without IUPAC naming.

    Pure RDKit — no PubChem, no OPSIN, no network calls. Returns InChI,
    InChIKey (the universal cross-database identifier), Hill-notation
    molecular formula, average molecular weight, and optionally an SVG.

    Args:
        smiles: SMILES string. Salts/mixtures pass through unchanged
            (this tool doesn't strip counter-ions — use classify_smiles or
            smiles_to_iupac for that).
        include_svg: If True, include a 300x300 structure SVG.

    Returns:
        Dict with: smiles (input), canonical_smiles, inchi, inchikey,
        formula, mol_weight, structure_svg (only if requested).

    Raises:
        Returns an error dict if SMILES is unparseable.
    """
    try:
        canonical = canonicalize(smiles)
    except Exception as e:
        return {"smiles": smiles, "error": f"could not parse SMILES: {e}"}
    out = {
        "smiles": smiles,
        "canonical_smiles": canonical,
        "inchi": _enrich.inchi(canonical),
        "inchikey": _enrich.inchikey(canonical),
        "formula": _enrich.formula(canonical),
        "mol_weight": _enrich.mol_weight(canonical),
    }
    if include_svg:
        out["structure_svg"] = _enrich.structure_svg(canonical)
    return out


def main() -> None:
    """Entry point for the stdio MCP server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
