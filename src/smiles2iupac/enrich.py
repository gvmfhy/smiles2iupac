"""Cheap enrichment helpers: InChI, InChIKey, formula, MW, SVG, and PubChem CAS."""

import re
from urllib.parse import quote

from rdkit import Chem
from rdkit.Chem import Descriptors, rdMolDescriptors
from rdkit.Chem.Draw import rdMolDraw2D

from .pubchem import BASE_URL, PubChemError, _get

_CAS_RE = re.compile(r"^\d{2,7}-\d{2}-\d$")


def _mol(canonical_smiles: str) -> Chem.Mol:
    mol = Chem.MolFromSmiles(canonical_smiles)
    if mol is None:
        raise ValueError(f"could not parse SMILES: {canonical_smiles!r}")
    return mol


def inchi(canonical_smiles: str) -> str:
    """Return the standard InChI string."""
    return Chem.MolToInchi(_mol(canonical_smiles))


def inchikey(canonical_smiles: str) -> str:
    """Return the 27-character standard InChIKey."""
    return Chem.MolToInchiKey(_mol(canonical_smiles))


def formula(canonical_smiles: str) -> str:
    """Return the molecular formula in Hill notation (e.g. 'C2H6O')."""
    return rdMolDescriptors.CalcMolFormula(_mol(canonical_smiles))


def mol_weight(canonical_smiles: str) -> float:
    """Return the average molecular weight in g/mol, rounded to 4 decimals."""
    return round(Descriptors.MolWt(_mol(canonical_smiles)), 4)


def structure_svg(canonical_smiles: str, size: int = 300) -> str:
    """Render the molecule as a square SVG of dimensions size x size."""
    drawer = rdMolDraw2D.MolDraw2DSVG(size, size)
    drawer.DrawMolecule(_mol(canonical_smiles))
    drawer.FinishDrawing()
    return drawer.GetDrawingText()


def pubchem_cas(canonical_smiles: str) -> str | None:
    """Return the CAS Registry Number from PubChem if available, else None.

    Best-effort enrichment — silently returns None on any failure (network,
    missing data, or parse error). The first numeric CAS-shaped string in
    the RegistryID list is returned.
    """
    try:
        encoded = quote(canonical_smiles, safe="")
        data = _get(f"{BASE_URL}/compound/smiles/{encoded}/xrefs/RegistryID/JSON")
        if not data:
            return None
        info = data.get("InformationList", {}).get("Information", [])
        if not info:
            return None
        for rid in info[0].get("RegistryID", []):
            if isinstance(rid, str) and _CAS_RE.match(rid):
                return rid
        return None
    except (PubChemError, KeyError, IndexError, TypeError, ValueError):
        return None
