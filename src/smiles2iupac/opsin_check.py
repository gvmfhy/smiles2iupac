"""OPSIN round-trip validator: name → SMILES → InChIKey-tier comparison.

OPSIN parses an IUPAC name back to SMILES; we compare the result against the
original via InChIKey. Block 1 (chars 0..14) encodes the molecular skeleton —
constitution + protonation. Block 2 (chars 15..25) encodes stereochemistry +
isotopes. Matching block 1 means structurally identical; matching the full key
means stereo-identical too. This drives the STOUT_VALIDATED / STOUT_UNVALIDATED
/ STOUT_LOW_CONFIDENCE confidence tiering in the pipeline.
"""

from pydantic import BaseModel
from rdkit import Chem
from rdkit.Chem import inchi


class OpsinError(Exception):
    """Raised when OPSIN (py2opsin) is unavailable."""


class RoundTripResult(BaseModel):
    """Outcome of a name → SMILES round-trip with InChIKey-based tiering."""

    name: str
    original_smiles: str
    back_smiles: str | None
    parsed_ok: bool
    skeleton_match: bool
    full_match: bool


def _inchikey(smiles: str) -> str | None:
    """Return InChIKey for `smiles`, or None if RDKit can't parse it."""
    try:
        mol = Chem.MolFromSmiles(smiles)
    except Exception:
        return None
    if mol is None:
        return None
    try:
        key = inchi.MolToInchiKey(mol)
    except Exception:
        return None
    return key or None


def round_trip(name: str, original_canonical_smiles: str) -> RoundTripResult:
    """Round-trip an IUPAC `name` through OPSIN and compare to `original_canonical_smiles`.

    Returns a RoundTripResult with two confidence tiers:
        full_match     — InChIKeys identical (skeleton + stereo)
        skeleton_match — block 1 (first 14 chars) match only; stereo lost or differs

    Raises OpsinError if py2opsin isn't installed.
    """
    try:
        from py2opsin import py2opsin  # lazy: keep module importable without [ml] extras
    except ImportError as e:
        raise OpsinError("py2opsin not installed; install smiles2iupac[ml]") from e

    failed = RoundTripResult(
        name=name,
        original_smiles=original_canonical_smiles,
        back_smiles=None,
        parsed_ok=False,
        skeleton_match=False,
        full_match=False,
    )

    try:
        back_smiles = py2opsin(name, output_format="SMILES")
    except Exception:
        return failed
    if not back_smiles:  # OPSIN returns "" on parse failure
        return failed

    original_key = _inchikey(original_canonical_smiles)
    back_key = _inchikey(back_smiles)
    if original_key is None or back_key is None:
        return failed.model_copy(update={"back_smiles": back_smiles})

    return RoundTripResult(
        name=name,
        original_smiles=original_canonical_smiles,
        back_smiles=back_smiles,
        parsed_ok=True,
        skeleton_match=original_key[:14] == back_key[:14],
        full_match=original_key == back_key,
    )
