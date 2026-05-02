"""OPSIN round-trip validator: name → SMILES → InChIKey-tier comparison.

OPSIN parses an IUPAC name back to SMILES; we compare the result against the
original via InChIKey. The 27-char InChIKey is `XXXXXXXXXXXXXX-YYYYYYYYYY-Z`:
chars 0..13 (the slice `[:14]`) are block 1 — molecular skeleton (constitution).
Chars 15..24 are block 2 — stereochemistry + isotopes + protonation flags.
Char 26 is a final standardization marker. Matching block 1 means structurally
identical (same atoms, same connectivity); matching the full key means stereo-
identical too. This drives the STOUT_VALIDATED / STOUT_UNVALIDATED /
STOUT_LOW_CONFIDENCE confidence tiering in the pipeline.
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


def parse_iupac_name(name: str) -> str | None:
    """Parse an IUPAC name to canonical SMILES via OPSIN.

    Returns canonical SMILES (RDKit-canonicalized) on success. Returns None if
    OPSIN can't parse the name (most common cause: it's a common name like
    'aspirin', not a systematic IUPAC name — fall back to PubChem name search
    for those). Raises OpsinError if py2opsin isn't installed.
    """
    try:
        from py2opsin import py2opsin  # lazy: keep module importable without [ml] extras
    except ImportError as e:
        raise OpsinError(
    "py2opsin not installed; install with `uv pip install -e '.[ml]'` "
    "(development checkout) or `pip install smiles2iupac[ml]` once published"
) from e

    try:
        back = py2opsin(name, output_format="SMILES")
    except Exception:
        return None
    if not back:
        return None
    mol = Chem.MolFromSmiles(back)
    if mol is None:
        return None
    return Chem.MolToSmiles(mol, canonical=True)


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
        raise OpsinError(
    "py2opsin not installed; install with `uv pip install -e '.[ml]'` "
    "(development checkout) or `pip install smiles2iupac[ml]` once published"
) from e

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
