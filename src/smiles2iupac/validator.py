"""SMILES validation and canonicalization via RDKit."""

from rdkit import Chem
from rdkit import RDLogger

RDLogger.DisableLog("rdApp.*")


class SMILESError(ValueError):
    """Raised when a SMILES string cannot be parsed."""


def canonicalize(smiles: str) -> str:
    """Return the canonical SMILES for `smiles`, or raise SMILESError."""
    if not smiles or not smiles.strip():
        raise SMILESError("empty SMILES")
    mol = Chem.MolFromSmiles(smiles.strip())
    if mol is None:
        raise SMILESError(f"could not parse SMILES: {smiles!r}")
    return Chem.MolToSmiles(mol, canonical=True)


def heavy_atom_count(smiles: str) -> int:
    """Return the heavy-atom count, or 0 if SMILES is invalid."""
    mol = Chem.MolFromSmiles(smiles)
    return mol.GetNumHeavyAtoms() if mol is not None else 0


def is_supported(smiles: str, max_heavy_atoms: int = 999) -> tuple[bool, str | None]:
    """Check whether the molecule is in scope for naming.

    Returns (supported, reason_if_not).
    """
    count = heavy_atom_count(smiles)
    if count == 0:
        return False, "could not parse SMILES"
    if count > max_heavy_atoms:
        return False, f"polymer/biologic: {count} heavy atoms exceeds limit {max_heavy_atoms}"
    return True, None
