"""Result type for conversion calls."""

from enum import Enum

from pydantic import BaseModel, Field


class Source(str, Enum):
    """Where the IUPAC name came from."""

    CACHE = "cache"
    PUBCHEM = "pubchem"
    STOUT_VALIDATED = "stout_validated"
    STOUT_UNVALIDATED = "stout_unvalidated"
    STOUT_LOW_CONFIDENCE = "stout_low_confidence"
    NONE = "none"


class Result(BaseModel):
    """Conversion result with provenance and confidence."""

    smiles: str = Field(..., description="Original input SMILES")
    canonical_smiles: str = Field("", description="RDKit-canonicalized SMILES")
    name: str | None = Field(None, description="IUPAC name, if found")
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="Confidence in 0..1")
    source: Source = Field(Source.NONE, description="Provenance of the name")
    alternatives: list[str] = Field(default_factory=list, description="Other candidate names")
    error: str | None = Field(None, description="Error message if conversion failed")

    @property
    def ok(self) -> bool:
        return self.name is not None and self.error is None

    def __str__(self) -> str:
        if self.error:
            return f"<error: {self.error}>"
        if not self.name:
            return "<no name found>"
        return f"{self.name}  (confidence: {self.confidence:.2f}, source: {self.source.value})"
