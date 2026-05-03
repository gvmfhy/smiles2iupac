"""smiles2iupac — SMILES to IUPAC name conversion via PubChem + OPSIN cross-validation."""

from .pipeline import Pipeline, convert, lookup
from .result import Result, Source

__version__ = "0.1.0"
__all__ = ["Pipeline", "Result", "Source", "convert", "lookup", "__version__"]
