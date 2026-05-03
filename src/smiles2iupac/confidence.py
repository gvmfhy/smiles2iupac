"""Confidence scoring per source."""

from .result import Source

CONFIDENCE: dict[Source, float] = {
    Source.PUBCHEM: 1.00,
    Source.CACHE: 1.00,  # cache stores per-source confidence; this is a placeholder
    Source.NONE: 0.00,
}
