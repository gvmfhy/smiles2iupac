"""Conversion pipeline.

Layers, in order:
    1. Classify (validator_strict): reject reactions/polymers, strip salts, pick parent.
    2. Heavy-atom limit (validator.is_supported).
    3. Cheap enrichment (InChI, InChIKey, formula, MW).
    4. Cache lookup (canonical SMILES → name).
    5. PubChem lookup — InChIKey first, SMILES fallback.
    6. STOUT v2 generation + OPSIN round-trip validation (opt-in via use_stout).
    7. Optional enrichment (structure SVG, CAS) gated by flags.
"""

from . import enrich
from .cache import Cache
from .confidence import CONFIDENCE
from .opsin_check import OpsinError, parse_iupac_name, round_trip
from .pubchem import (
    PubChemError,
    iupac_via_inchikey,
    name_to_smiles as _pubchem_name_to_smiles,
    smiles_to_iupac,
    smiles_to_synonyms,
)
from .result import Result, Source
from .stout_engine import StoutError, stout_iupac
from .validator import is_supported
from .validator_strict import classify

REJECTED_KINDS = {"empty", "reaction", "polymer"}


class Pipeline:
    def __init__(
        self,
        cache: Cache | None = None,
        use_pubchem: bool = True,
        use_stout: bool = False,
        fetch_synonyms: bool = False,
        include_svg: bool = False,
        include_cas: bool = False,
    ):
        self.cache = cache if cache is not None else Cache()
        self.use_pubchem = use_pubchem
        self.use_stout = use_stout
        self.fetch_synonyms = fetch_synonyms
        self.include_svg = include_svg
        self.include_cas = include_cas

    def convert(self, smiles: str) -> Result:
        result = Result(smiles=smiles)

        classification = classify(smiles)
        result.kind = classification.kind
        result.warnings = list(classification.warnings)

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
            result.error = reason
            return result

        try:
            result.inchi = enrich.inchi(canonical)
            result.inchikey = enrich.inchikey(canonical)
            result.formula = enrich.formula(canonical)
            result.mol_weight = enrich.mol_weight(canonical)
        except ValueError as e:
            result.error = f"enrichment failed: {e}"
            return result

        cached = self.cache.lookup(canonical)
        if cached is not None:
            name, source, confidence = cached
            result.name = name
            result.source = Source(source)
            result.confidence = confidence
            return self._opt_enrich(result, canonical)

        if self.use_pubchem:
            name = self._pubchem_lookup(result.inchikey, canonical, result)
            if name:
                conf = CONFIDENCE[Source.PUBCHEM]
                self.cache.store(canonical, name, Source.PUBCHEM.value, conf)
                result.name = name
                result.source = Source.PUBCHEM
                result.confidence = conf
                if self.fetch_synonyms:
                    try:
                        result.alternatives = smiles_to_synonyms(canonical)
                    except PubChemError:
                        pass
                return self._opt_enrich(result, canonical)

        if self.use_stout:
            return self._stout_layer(canonical, result)

        if not result.error:
            result.error = "no name found (pubchem miss; STOUT not enabled)"
        return result

    def _pubchem_lookup(self, inchikey: str | None, canonical: str, result: Result) -> str | None:
        """Try InChIKey lookup first, fall back to canonical SMILES. Records errors on result."""
        try:
            if inchikey:
                name = iupac_via_inchikey(inchikey)
                if name:
                    return name
            return smiles_to_iupac(canonical)
        except PubChemError as e:
            result.error = f"pubchem unavailable: {e}"
            return None

    def _stout_layer(self, canonical: str, result: Result) -> Result:
        try:
            stout_name = stout_iupac(canonical)
        except StoutError as e:
            result.error = f"stout unavailable: {e}"
            return result
        if not stout_name:
            result.error = "STOUT could not generate a name"
            return result

        try:
            rt = round_trip(stout_name, canonical)
        except OpsinError:
            source = Source.STOUT_UNVALIDATED
            result.warnings.append("OPSIN unavailable; name not round-trip-validated")
        else:
            if rt.full_match:
                source = Source.STOUT_VALIDATED
            elif rt.skeleton_match:
                source = Source.STOUT_UNVALIDATED
                result.warnings.append("OPSIN round-trip: skeleton matches but stereo differs")
            elif rt.parsed_ok:
                source = Source.STOUT_LOW_CONFIDENCE
                result.warnings.append("OPSIN round-trip: name parses to a different structure")
            else:
                source = Source.STOUT_UNVALIDATED
                result.warnings.append("OPSIN could not parse generated name")

        conf = CONFIDENCE[source]
        self.cache.store(canonical, stout_name, source.value, conf)
        result.name = stout_name
        result.source = source
        result.confidence = conf
        return self._opt_enrich(result, canonical)

    def _opt_enrich(self, result: Result, canonical: str) -> Result:
        if self.include_svg:
            try:
                result.structure_svg = enrich.structure_svg(canonical)
            except ValueError:
                pass
        if self.include_cas:
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
