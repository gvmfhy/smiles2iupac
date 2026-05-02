"""Confidence scoring per source. See plan §Build Sequence Weekend 2 for tier rationale."""

from .result import Source

CONFIDENCE: dict[Source, float] = {
    Source.PUBCHEM: 1.00,
    Source.STOUT_VALIDATED: 0.95,
    Source.STOUT_UNVALIDATED: 0.50,
    Source.STOUT_LOW_CONFIDENCE: 0.20,
    Source.CACHE: 1.00,  # cache stores per-source confidence; this is a placeholder
    Source.NONE: 0.00,
}
