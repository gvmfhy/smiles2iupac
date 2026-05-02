"""Strict SMILES checks: reaction/polymer rejection, salt stripping, classification.

Layered on top of `validator.py` — never modifies it. Use `classify()` to route a
SMILES through the naming pipeline; reaction and polymer SMILES are out of scope,
salts are split into parent + counterions, mixtures keep the largest fragment.
"""

from typing import Literal

from pydantic import BaseModel
from rdkit import Chem
from rdkit import RDLogger

RDLogger.DisableLog("rdApp.*")


class ReactionSmilesError(ValueError):
    """Raised when a reaction SMILES (`A>>B`) is passed where a molecule is expected."""


class PolymerSmilesError(ValueError):
    """Raised when polymer/wildcard notation (`*`, `[*]`) is passed where a molecule is expected."""


SmilesKind = Literal["molecule", "reaction", "polymer", "mixture", "salt", "empty"]


class Classification(BaseModel):
    kind: SmilesKind
    parent_smiles: str | None
    counterions: list[str]
    components: list[str]
    warnings: list[str]


def is_reaction(smiles: str) -> bool:
    """True iff SMILES contains a reaction arrow (``>>``)."""
    return ">>" in smiles


def has_wildcards(smiles: str) -> bool:
    """True iff SMILES contains ``*`` or ``[*]`` (polymer/repeat-unit notation)."""
    return "*" in smiles


def _canon(mol: Chem.Mol) -> str:
    return Chem.MolToSmiles(mol, canonical=True)


def _is_monoatomic_ion(mol: Chem.Mol) -> bool:
    """Single heavy atom carrying a non-zero formal charge (e.g. [Na+], [Cl-], [K+])."""
    if mol.GetNumHeavyAtoms() != 1:
        return False
    return any(a.GetFormalCharge() != 0 for a in mol.GetAtoms())


def strip_salts(smiles: str) -> tuple[str, list[str]]:
    """Split a (possibly multi-component) SMILES into ``(parent, [counterions...])``.

    Parent is the fragment with the most heavy atoms (first one wins on ties).
    Each component is returned as canonical SMILES. Single-component input
    yields ``(canonical, [])``. Raises ``ValueError`` for empty/unparseable input.
    """
    if not smiles or not smiles.strip():
        raise ValueError("empty SMILES")
    mol = Chem.MolFromSmiles(smiles.strip())
    if mol is None:
        raise ValueError(f"could not parse SMILES: {smiles!r}")
    frags = list(Chem.GetMolFrags(mol, asMols=True))
    if len(frags) == 1:
        return _canon(frags[0]), []
    # Stable: ties resolved by original input order. max() returns first max on ties.
    parent_mol = max(frags, key=lambda f: f.GetNumHeavyAtoms())
    parent_canon = _canon(parent_mol)
    counterions = [_canon(f) for f in frags if f is not parent_mol]
    return parent_canon, counterions


def classify(smiles: str) -> Classification:
    """Full classification + parent extraction. Never raises.

    Returns a ``Classification`` describing what the SMILES is and what — if anything —
    can be named. ``kind="empty"`` covers both empty input and unparseable garbage.
    """
    def _empty(kind: SmilesKind, warning: str) -> Classification:
        return Classification(
            kind=kind, parent_smiles=None, counterions=[], components=[],
            warnings=[warning],
        )

    if not smiles or not smiles.strip():
        return _empty("empty", "empty SMILES")
    # Order matters: reaction check before parse (RDKit can't parse `>>`).
    if is_reaction(smiles):
        return _empty("reaction", "reaction SMILES not supported for naming")
    if has_wildcards(smiles):
        return _empty("polymer", "polymer/wildcard notation not supported")
    mol = Chem.MolFromSmiles(smiles.strip())
    if mol is None:
        return _empty("empty", f"could not parse SMILES: {smiles!r}")
    frags = list(Chem.GetMolFrags(mol, asMols=True))
    components = [_canon(f) for f in frags]
    if len(frags) == 1:
        return Classification(
            kind="molecule", parent_smiles=components[0], counterions=[],
            components=components, warnings=[],
        )
    parent_mol = max(frags, key=lambda f: f.GetNumHeavyAtoms())
    parent_canon = _canon(parent_mol)
    others = [f for f in frags if f is not parent_mol]
    smallest_other = min(others, key=lambda f: f.GetNumHeavyAtoms())
    if _is_monoatomic_ion(smallest_other):
        counterions = [_canon(f) for f in others]
        n = len(counterions)
        plural = "s" if n != 1 else ""
        return Classification(
            kind="salt", parent_smiles=parent_canon, counterions=counterions,
            components=components,
            warnings=[f"stripped {n} counter-ion{plural}"],
        )
    return Classification(
        kind="mixture", parent_smiles=parent_canon, counterions=[],
        components=components,
        warnings=[f"mixture: kept largest of {len(frags)} components for naming"],
    )
