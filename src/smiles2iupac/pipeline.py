"""Conversion pipeline.

Layers, in order:
    1. Classify (validator_strict): reject reactions/polymers, strip salts, pick parent.
    2. Heavy-atom limit (validator.is_supported).
    3. Cheap enrichment (InChI, InChIKey, formula, MW).
    4. Cache lookup (canonical SMILES → name).
    5. PubChem lookup — InChIKey first, SMILES fallback.
    6. Optional enrichment (structure SVG, CAS) gated by flags.
"""

from . import enrich
from .cache import Cache
from .confidence import CONFIDENCE
from .opsin_check import OpsinError, parse_iupac_name
from .pubchem import (
    PubChemError,
    iupac_via_inchikey,
    name_to_smiles as _pubchem_name_to_smiles,
    smiles_to_iupac,
    smiles_to_synonyms,
)
from .result import Result, Source
from .validator import is_supported
from .validator_strict import classify

REJECTED_KINDS = {"empty", "reaction", "polymer"}


class Pipeline:
    def __init__(
        self,
        cache: Cache | None = None,
        use_pubchem: bool = True,
        fetch_synonyms: bool = False,
        include_svg: bool = False,
        include_cas: bool = False,
    ):
        self.cache = cache if cache is not None else Cache()
        self.use_pubchem = use_pubchem
        self.fetch_synonyms = fetch_synonyms
        self.include_svg = include_svg
        self.include_cas = include_cas

    def convert(
        self,
        smiles: str,
        *,
        include_svg: bool | None = None,
        include_cas: bool | None = None,
        fetch_synonyms: bool | None = None,
    ) -> Result:
        """Convert a SMILES to an IUPAC Result.

        Per-call overrides for `include_svg`, `include_cas`, and `fetch_synonyms`
        take precedence over instance defaults. They're passed as arguments rather
        than mutated on the instance so that concurrent callers (e.g. multiple
        FastAPI requests sharing one Pipeline) never race on shared mutable state.
        """
        # Resolve effective flags (per-call > instance default)
        eff_svg = self.include_svg if include_svg is None else include_svg
        eff_cas = self.include_cas if include_cas is None else include_cas
        eff_syn = self.fetch_synonyms if fetch_synonyms is None else fetch_synonyms

        result = Result(smiles=smiles)

        classification = classify(smiles)
        result.kind = classification.kind
        result.warnings = list(classification.warnings)

        # Step 1: classification reasoning, recorded for any non-trivial outcome.
        if classification.kind == "salt":
            ions = ", ".join(classification.counterions) or "none"
            result.trace.append(
                f"Identified as salt — parent: {classification.parent_smiles}; "
                f"stripped {len(classification.counterions)} counter-ion(s): {ions}"
            )
        elif classification.kind == "mixture":
            result.trace.append(
                f"Identified as mixture — named largest of {len(classification.components)} "
                f"components: {classification.parent_smiles}"
            )
        elif classification.kind in REJECTED_KINDS:
            result.trace.append(f"Rejected: {classification.kind} — see warnings")

        if classification.kind in REJECTED_KINDS or classification.parent_smiles is None:
            result.error = (
                classification.warnings[0]
                if classification.warnings
                else f"unsupported SMILES kind: {classification.kind}"
            )
            return result

        canonical = classification.parent_smiles
        result.canonical_smiles = canonical

        supported, reason = is_supported(canonical)
        if not supported:
            result.trace.append(f"Rejected by support check: {reason}")
            result.error = reason
            return result

        try:
            result.inchi = enrich.inchi(canonical)
            result.inchikey = enrich.inchikey(canonical)
            result.formula = enrich.formula(canonical)
            result.mol_weight = enrich.mol_weight(canonical)
            result.trace.append(f"Computed InChIKey: {result.inchikey}")
        except ValueError as e:
            result.error = f"enrichment failed: {e}"
            return result

        cached = self.cache.lookup(canonical)
        if cached is not None:
            name, source, confidence = cached
            result.name = name
            result.source = Source(source)
            result.confidence = confidence
            result.trace.append(f"Cache hit (originally from {source})")
            return self._opt_enrich(result, canonical, eff_svg, eff_cas)
        result.trace.append("Cache miss")

        if self.use_pubchem:
            name = self._pubchem_lookup_with_trace(result.inchikey, canonical, result)
            if name:
                conf = CONFIDENCE[Source.PUBCHEM]
                self.cache.store(canonical, name, Source.PUBCHEM.value, conf)
                result.name = name
                result.source = Source.PUBCHEM
                result.confidence = conf
                if eff_syn:
                    try:
                        result.alternatives = smiles_to_synonyms(canonical)
                        if result.alternatives:
                            result.trace.append(
                                f"Fetched {len(result.alternatives)} synonyms from PubChem"
                            )
                    except PubChemError:
                        pass
                return self._opt_enrich(result, canonical, eff_svg, eff_cas)

        if not result.error:
            result.error = "no name found (pubchem returned no match)"
            result.trace.append("No name found — PubChem returned no match")
        return result

    def _pubchem_lookup_with_trace(self, inchikey: str | None, canonical: str, result: Result) -> str | None:
        """Try InChIKey lookup first, fall back to canonical SMILES. Records trace + errors."""
        try:
            if inchikey:
                name = iupac_via_inchikey(inchikey)
                if name:
                    result.trace.append(f"PubChem InChIKey lookup → matched: {name!r}")
                    return name
                result.trace.append("PubChem InChIKey lookup → no match")
            name = smiles_to_iupac(canonical)
            if name:
                result.trace.append(f"PubChem SMILES fallback → matched: {name!r}")
            else:
                result.trace.append("PubChem SMILES fallback → no match")
            return name
        except PubChemError as e:
            result.trace.append(f"PubChem unavailable: {e}")
            result.error = f"pubchem unavailable: {e}"
            return None

    def _opt_enrich(
        self, result: Result, canonical: str, eff_svg: bool, eff_cas: bool
    ) -> Result:
        """Apply opt-in enrichment based on per-call effective flags (no instance reads)."""
        if eff_svg:
            try:
                result.structure_svg = enrich.structure_svg(canonical)
            except ValueError:
                pass
        if eff_cas:
            try:
                result.cas = enrich.pubchem_cas(canonical)
            except PubChemError:
                pass
        return result


def convert(smiles: str) -> Result:
    """Convenience function using a default Pipeline."""
    return Pipeline().convert(smiles)


def lookup(name: str, use_pubchem: bool = True) -> str | None:
    """Reverse lookup: chemical name → canonical SMILES.

    Tries OPSIN first (handles IUPAC names rigorously, no network call) and
    falls back to PubChem name search (handles common names like 'aspirin'
    or 'caffeine'). Returns RDKit-canonical SMILES so the result matches
    what `convert()` would canonicalize the same molecule to. Returns None
    if neither resolver finds a match.
    """
    if not name or not name.strip():
        return None

    try:
        s = parse_iupac_name(name)
        if s:
            return s
    except OpsinError:
        pass  # OPSIN not installed; fall through to PubChem

    if use_pubchem:
        try:
            raw = _pubchem_name_to_smiles(name)
        except PubChemError:
            return None
        if raw:
            from rdkit import Chem
            mol = Chem.MolFromSmiles(raw)
            if mol is not None:
                return Chem.MolToSmiles(mol, canonical=True)
    return None
