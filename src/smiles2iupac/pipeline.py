"""Conversion pipeline: validate → cache → PubChem → (STOUT + OPSIN, weekend 2)."""

from .cache import Cache
from .confidence import CONFIDENCE
from .pubchem import PubChemError, smiles_to_iupac, smiles_to_synonyms
from .result import Result, Source
from .validator import SMILESError, canonicalize, is_supported


class Pipeline:
    def __init__(
        self,
        cache: Cache | None = None,
        use_pubchem: bool = True,
        use_stout: bool = False,
        fetch_synonyms: bool = False,
    ):
        self.cache = cache if cache is not None else Cache()
        self.use_pubchem = use_pubchem
        self.use_stout = use_stout
        self.fetch_synonyms = fetch_synonyms

    def convert(self, smiles: str) -> Result:
        result = Result(smiles=smiles)

        try:
            canonical = canonicalize(smiles)
        except SMILESError as e:
            result.error = str(e)
            return result
        result.canonical_smiles = canonical

        supported, reason = is_supported(canonical)
        if not supported:
            result.error = reason
            return result

        cached = self.cache.lookup(canonical)
        if cached is not None:
            name, source, confidence = cached
            result.name = name
            result.source = Source(source)
            result.confidence = confidence
            return result

        if self.use_pubchem:
            try:
                name = smiles_to_iupac(canonical)
            except PubChemError as e:
                result.error = f"pubchem unavailable: {e}"
                name = None
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
                return result

        if self.use_stout:
            return self._stout_layer(canonical, result)

        if not result.error:
            result.error = "no name found (pubchem miss; STOUT not enabled)"
        return result

    def _stout_layer(self, canonical: str, result: Result) -> Result:
        """Weekend 2: STOUT inference + OPSIN round-trip validation."""
        result.error = "STOUT layer not yet implemented"
        return result


def convert(smiles: str) -> Result:
    """Convenience function using a default Pipeline."""
    return Pipeline().convert(smiles)
