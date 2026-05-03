"""Result type for conversion calls.

Carries the IUPAC name plus enrichment fields a chemist actually needs:
canonical SMILES, InChI, InChIKey, formula, molecular weight, optional
structure SVG, optional CAS number, plus provenance, warnings, a
human-readable reasoning trace, and a PubChem verify URL so the user can
independently confirm what the pipeline returned.
"""

from enum import Enum

from pydantic import BaseModel, Field, computed_field


class Source(str, Enum):
    """Where the IUPAC name came from."""

    CACHE = "cache"
    PUBCHEM = "pubchem"
    NONE = "none"


class Result(BaseModel):
    """Conversion result with provenance, confidence, and enrichment."""

    smiles: str = Field(..., description="Original input SMILES")
    canonical_smiles: str = Field("", description="RDKit-canonicalized SMILES of the named component")
    name: str | None = Field(None, description="IUPAC name, if found")
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="Confidence in 0..1")
    source: Source = Field(Source.NONE, description="Provenance of the name")
    alternatives: list[str] = Field(default_factory=list, description="Other candidate names (synonyms)")

    # Enrichment — populated for any successful conversion.
    inchi: str | None = Field(None, description="Standard InChI")
    inchikey: str | None = Field(None, description="Standard 27-char InChIKey")
    formula: str | None = Field(None, description="Molecular formula in Hill notation")
    mol_weight: float | None = Field(None, description="Average molecular weight, g/mol")
    structure_svg: str | None = Field(None, description="SVG render (only if include_svg=True)")
    cas: str | None = Field(None, description="CAS Registry Number (only if include_cas=True)")

    # Classification side-channel.
    kind: str = Field("molecule", description="One of: molecule, salt, mixture, reaction, polymer, empty")
    warnings: list[str] = Field(default_factory=list, description="Non-fatal classification warnings")

    # Transparency — what the pipeline actually did, in plain language. Each
    # entry is a discrete step; the user can read the chain end-to-end and see
    # WHY a given name came back. Especially load-bearing for salts/mixtures
    # where the pipeline names the parent fragment, not the literal input.
    trace: list[str] = Field(default_factory=list, description="Step-by-step reasoning")

    error: str | None = Field(None, description="Error message if conversion failed")

    @property
    def ok(self) -> bool:
        return self.name is not None and self.error is None

    @computed_field  # included in model_dump / JSON output
    @property
    def pubchem_url(self) -> str | None:
        """Auto-generated link to PubChem's record for this molecule.

        Lets a user click through and independently verify the structure +
        canonical IUPAC + synonyms PubChem has on file — closing the loop on
        "trust me, this is right" with "here, see for yourself."
        """
        if not self.inchikey:
            return None
        return f"https://pubchem.ncbi.nlm.nih.gov/#query={self.inchikey}"

    def __str__(self) -> str:
        if self.error:
            return f"<error: {self.error}>"
        if not self.name:
            return "<no name found>"
        head = f"{self.name}  (confidence: {self.confidence:.2f}, source: {self.source.value})"
        if self.warnings:
            head += "\n  warnings: " + "; ".join(self.warnings)
        return head
