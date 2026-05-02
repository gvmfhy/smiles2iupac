"""PubChem PUG-REST client with token-bucket rate limiting and retry."""

import threading
import time
from urllib.parse import quote

import requests

BASE_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
DEFAULT_TIMEOUT = 10.0
PUBCHEM_RATE = 5.0  # requests per second; PubChem's documented limit


class PubChemError(Exception):
    """Raised on unrecoverable PubChem errors."""


class _RateLimiter:
    """Strict 1/rate spacing rate limiter, thread-safe.

    Each `acquire()` reserves the next available timestamp slot under the lock,
    then sleeps until its reserved moment OUTSIDE the lock. This ensures N
    concurrent acquirers serialize: each waits for all the slots ahead of it,
    enforcing the rate limit even under heavy threadpool concurrency.

    A token-bucket would allow brief bursts; we use spacing instead because
    PubChem's limit is per-second and we'd rather under-burst than risk
    IP-level throttling.
    """

    def __init__(self, rate: float):
        self.rate = rate
        self.interval = 1.0 / rate
        self._next_available = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait_until = max(now, self._next_available)
            # Reserve our slot; subsequent acquirers see a later _next_available.
            self._next_available = wait_until + self.interval
        wait_for = wait_until - time.monotonic()
        if wait_for > 0:
            time.sleep(wait_for)


_limiter = _RateLimiter(PUBCHEM_RATE)


def _get(url: str, retries: int = 3) -> dict | None:
    """GET with rate limiting and exponential backoff. Returns None on 404.

    Raises PubChemError on:
        - non-recoverable HTTP errors (4xx other than 404, 5xx other than 503)
        - network errors after `retries` attempts
        - 429/503 still throttled after `retries` attempts (signals upstream throttling,
          NOT "compound not found" — silently returning None there would mask outages)
    """
    last_throttle_status: int | None = None
    last_exc: Exception | None = None
    for attempt in range(retries):
        _limiter.acquire()
        try:
            r = requests.get(url, timeout=DEFAULT_TIMEOUT)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 404:
                return None
            if r.status_code in (429, 503):
                last_throttle_status = r.status_code
                time.sleep(2**attempt)
                continue
            raise PubChemError(f"HTTP {r.status_code}: {r.text[:200]}")
        except requests.RequestException as e:
            last_exc = e
            if attempt == retries - 1:
                raise PubChemError(f"network error: {e}") from e
            time.sleep(2**attempt)
    # Loop exhausted. Either we hit 429/503 every attempt, or we ran out of
    # network retries. The latter is impossible here (the last RequestException
    # raises above), so the only path here is throttle exhaustion.
    if last_throttle_status is not None:
        raise PubChemError(
            f"PubChem throttled after {retries} retries (last status {last_throttle_status})"
        )
    if last_exc:
        raise PubChemError(f"exhausted retries: {last_exc}") from last_exc
    return None


def smiles_to_iupac(canonical_smiles: str) -> str | None:
    """Look up the IUPAC name for `canonical_smiles` via PubChem.

    Returns None if the structure is not in PubChem.
    """
    encoded = quote(canonical_smiles, safe="")
    cid_data = _get(f"{BASE_URL}/compound/smiles/{encoded}/cids/JSON")
    if not cid_data:
        return None
    cids = cid_data.get("IdentifierList", {}).get("CID", [])
    if not cids or cids == [0]:
        return None
    cid = cids[0]

    name_data = _get(f"{BASE_URL}/compound/cid/{cid}/property/IUPACName/JSON")
    if not name_data:
        return None
    props = name_data.get("PropertyTable", {}).get("Properties", [])
    if not props:
        return None
    return props[0].get("IUPACName")


def iupac_via_inchikey(inchikey: str) -> str | None:
    """Look up the IUPAC name via PubChem keyed by InChIKey.

    PubChem and RDKit canonicalize SMILES differently, so a SMILES-keyed
    lookup occasionally misses molecules that PubChem actually has.
    InChIKey is IUPAC-standardized — both sides agree. Prefer this when an
    InChIKey is available; fall back to `smiles_to_iupac` otherwise.
    """
    if not inchikey or len(inchikey) != 27:
        return None
    cid_data = _get(f"{BASE_URL}/compound/inchikey/{inchikey}/cids/JSON")
    if not cid_data:
        return None
    cids = cid_data.get("IdentifierList", {}).get("CID", [])
    if not cids or cids == [0]:
        return None
    cid = cids[0]

    name_data = _get(f"{BASE_URL}/compound/cid/{cid}/property/IUPACName/JSON")
    if not name_data:
        return None
    props = name_data.get("PropertyTable", {}).get("Properties", [])
    if not props:
        return None
    return props[0].get("IUPACName")


def name_to_smiles(name: str) -> str | None:
    """Resolve a chemical name (common or IUPAC) to canonical SMILES via PubChem.

    Catches both common names ("aspirin", "ibuprofen") and most IUPAC names —
    PubChem's compound/name endpoint is name-format-agnostic. Returns None when
    the name isn't found. Raises PubChemError on network failure.
    """
    if not name or not name.strip():
        return None
    encoded = quote(name.strip(), safe="")
    cid_data = _get(f"{BASE_URL}/compound/name/{encoded}/cids/JSON")
    if not cid_data:
        return None
    cids = cid_data.get("IdentifierList", {}).get("CID", [])
    if not cids or cids == [0]:
        return None
    cid = cids[0]

    # PubChem deprecated the `CanonicalSMILES` property name; the current field is
    # `SMILES` (which includes stereo) or `ConnectivitySMILES` (without). We want
    # `SMILES` since RDKit will recanonicalize anyway and stereo is worth keeping.
    smi_data = _get(f"{BASE_URL}/compound/cid/{cid}/property/SMILES/JSON")
    if not smi_data:
        return None
    props = smi_data.get("PropertyTable", {}).get("Properties", [])
    if not props:
        return None
    return props[0].get("SMILES")


def smiles_to_synonyms(canonical_smiles: str, limit: int = 5) -> list[str]:
    """Fetch up to `limit` common-name synonyms for a SMILES (used as alternatives)."""
    encoded = quote(canonical_smiles, safe="")
    cid_data = _get(f"{BASE_URL}/compound/smiles/{encoded}/cids/JSON")
    if not cid_data:
        return []
    cids = cid_data.get("IdentifierList", {}).get("CID", [])
    if not cids or cids == [0]:
        return []
    cid = cids[0]

    syn_data = _get(f"{BASE_URL}/compound/cid/{cid}/synonyms/JSON")
    if not syn_data:
        return []
    info = syn_data.get("InformationList", {}).get("Information", [])
    if not info:
        return []
    return info[0].get("Synonym", [])[:limit]
