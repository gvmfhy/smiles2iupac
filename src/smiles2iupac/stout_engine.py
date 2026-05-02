"""Thin wrapper around STOUT v2 (lazy-loaded) for SMILES → IUPAC inference."""

from functools import lru_cache
from typing import Callable


class StoutError(Exception):
    """Raised when STOUT cannot be imported or the model fails to load."""


@lru_cache(maxsize=1)
def _get_translator() -> Callable[[str], str]:
    """Import and cache STOUT's `translate_forward`. Loads the model on first call.

    Cached so the heavy TensorFlow model is loaded at most once per process.
    Raises StoutError if STOUT-pypi is not installed or the model cannot load.
    """
    try:
        from STOUT import translate_forward
    except ImportError as e:
        raise StoutError(
            "STOUT-pypi is not installed; install with "
            "`uv pip install -e '.[ml]'` (development checkout) "
            "or `pip install smiles2iupac[ml]` once published to PyPI"
        ) from e
    except Exception as e:  # model-load failures surface as arbitrary exception types
        raise StoutError(f"could not load STOUT model: {e}") from e
    return translate_forward


def stout_iupac(canonical_smiles: str) -> str | None:
    """Generate an IUPAC name via STOUT v2.

    Returns the predicted name on success, or None on a STOUT-internal failure
    (empty output, parse error, runtime exception inside the model). Raises
    StoutError if the STOUT package is not installed or the model can't load.
    """
    translator = _get_translator()
    try:
        name = translator(canonical_smiles)
    except Exception:
        return None
    if not name:
        return None
    return name
