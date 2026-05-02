"""Build the verified accuracy dataset.

Strategy: seed candidates from the existing 262-row fixture + sample random
PubChem CIDs across breadth-tuned ranges. For each candidate, query PubChem's
IUPACName + canonical SMILES, then filter through OPSIN round-trip. Only rows
where the OPSIN-parsed name yields the same InChIKey (full skeleton + stereo
match) are kept — that's the cross-implementation "two algorithms agree"
verification that breaks circularity.

Output: tests/fixtures/accuracy_dataset.csv with a content-derived
dataset_version SHA-256 so reports can be tied to specific snapshots.

Usage:
    python scripts/build_accuracy_dataset.py             # build full 1000-row dataset
    python scripts/build_accuracy_dataset.py --limit 50  # quick test on 50 rows
    python scripts/build_accuracy_dataset.py --seed 7    # reproducible PubChem sampling
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import random
import sys
from pathlib import Path
from urllib.parse import quote

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from rdkit import Chem, RDLogger  # noqa: E402
from rdkit.Chem import inchi as rdkit_inchi  # noqa: E402

from smiles2iupac.enrich import inchikey  # noqa: E402
from smiles2iupac.pubchem import BASE_URL, PubChemError, _get  # noqa: E402
from smiles2iupac.validator import canonicalize  # noqa: E402

RDLogger.DisableLog("rdApp.*")

OUTPUT_CSV = REPO / "tests" / "fixtures" / "accuracy_dataset.csv"
EXISTING_FIXTURE = REPO / "tests" / "fixtures" / "known_molecules.csv"

# Per-category target counts (sums to 850 — leaves 150 slop for any-bucket fills).
# "negative" cases (reactions/polymers) are NOT in this dataset; the pipeline
# tests already cover rejection. Tautomers and carbohydrates are categorized
# heuristically and may undershoot — fine for v1.
CATEGORY_TARGETS = {
    "solvent_aliphatic": 100,
    "drug": 150,
    "heterocycle": 100,
    "stereo": 150,
    "carbohydrate_steroid": 30,
    "tautomer": 20,
    "salt_zwitterion": 50,
    "isotope_radical_ion": 50,
    "large": 100,
    "unusual_element": 30,
    "pathological": 70,
}
TARGET_TOTAL = 1000

# CID ranges chosen for breadth. Lower CIDs ≈ more common compounds.
PUBCHEM_CID_POOLS = [
    (1, 10_000),         # very common (water, methane, salts)
    (1_000, 100_000),    # common drugs and metabolites
    (100_000, 1_000_000),    # diverse small molecules
]


def fetch_by_cid(cid: int) -> dict | None:
    """Fetch SMILES + IUPACName + InChIKey for a CID in one call."""
    url = f"{BASE_URL}/compound/cid/{cid}/property/SMILES,IUPACName,InChIKey/JSON"
    try:
        data = _get(url)
    except PubChemError:
        return None
    if not data:
        return None
    props = data.get("PropertyTable", {}).get("Properties", [])
    if not props:
        return None
    p = props[0]
    smi = p.get("SMILES") or p.get("ConnectivitySMILES")
    if not smi or not p.get("IUPACName") or not p.get("InChIKey"):
        return None
    return {
        "cid": p.get("CID"),
        "smiles": smi,
        "iupac_name": p["IUPACName"],
        "inchikey": p["InChIKey"],
    }


def fetch_by_inchikey(key: str) -> dict | None:
    """Fetch SMILES + IUPACName for a canonical InChIKey."""
    url = f"{BASE_URL}/compound/inchikey/{quote(key)}/property/SMILES,IUPACName,InChIKey/JSON"
    try:
        data = _get(url)
    except PubChemError:
        return None
    if not data:
        return None
    props = data.get("PropertyTable", {}).get("Properties", [])
    if not props:
        return None
    p = props[0]
    smi = p.get("SMILES") or p.get("ConnectivitySMILES")
    if not smi or not p.get("IUPACName"):
        return None
    return {
        "cid": p.get("CID"),
        "smiles": smi,
        "iupac_name": p["IUPACName"],
        "inchikey": p.get("InChIKey", key),
    }


def categorize(canonical: str, mol: Chem.Mol) -> str:
    """Best-effort categorization. Order matters — most specific first."""
    heavy = mol.GetNumHeavyAtoms()
    has_isotope = any(a.GetIsotope() != 0 for a in mol.GetAtoms())
    is_multi = "." in canonical
    has_charge = any(a.GetFormalCharge() != 0 for a in mol.GetAtoms())
    atoms = {a.GetSymbol() for a in mol.GetAtoms()}
    has_unusual = bool(atoms & {"B", "Si", "Se", "Te", "As", "Ge"})
    has_stereo = (
        any(a.GetChiralTag() != Chem.ChiralType.CHI_UNSPECIFIED for a in mol.GetAtoms())
        or any(b.GetStereo() != Chem.BondStereo.STEREONONE for b in mol.GetBonds())
    )
    rings = mol.GetRingInfo().NumRings()
    has_hetero_ring = rings > 0 and any(
        a.GetSymbol() in {"N", "O", "S"} and a.IsInRing() for a in mol.GetAtoms()
    )
    # Carbohydrate / steroid heuristic: 4+ rings or >=3 OH groups in a fused-ring system
    n_oh = sum(1 for a in mol.GetAtoms() if a.GetSymbol() == "O" and a.GetTotalNumHs() >= 1)
    is_sugar_or_steroid = (rings >= 3 and n_oh >= 3) or rings >= 4

    if has_isotope:
        return "isotope_radical_ion"
    if is_multi:
        return "salt_zwitterion"
    if has_unusual:
        return "unusual_element"
    if has_charge:
        return "isotope_radical_ion"
    if is_sugar_or_steroid:
        return "carbohydrate_steroid"
    if heavy >= 30:
        return "large"
    if has_stereo:
        return "stereo"
    if heavy <= 4:
        return "pathological"
    if has_hetero_ring:
        return "heterocycle"
    if rings == 0 and heavy <= 12:
        return "solvent_aliphatic"
    return "drug"


def candidate_iter(seed: int):
    """Yield candidate inputs as ('smiles', smi) or ('cid', cid_int).

    Existing fixture exhausts first (preserving curated coverage), then random
    PubChem CID sampling for breadth.
    """
    if EXISTING_FIXTURE.exists():
        with open(EXISTING_FIXTURE) as f:
            for row in csv.DictReader(f):
                if row.get("smiles"):
                    yield ("smiles", row["smiles"])

    rng = random.Random(seed)
    seen_cids: set[int] = set()
    while True:
        pool = rng.choice(PUBCHEM_CID_POOLS)
        cid = rng.randint(*pool)
        if cid in seen_cids:
            continue
        seen_cids.add(cid)
        yield ("cid", cid)


def collect_pubchem_candidates(target_total: int, seed: int) -> list[dict]:
    """Phase 1: Walk candidate SMILES + CIDs and collect PubChem-name rows.

    Stops once we have target_total + slack candidates (over-collection covers
    the inevitable OPSIN reject rate downstream). Skips OPSIN entirely here.
    """
    candidates: list[dict] = []
    seen_keys: set[str] = set()
    attempts = 0
    rejected_dup = 0
    rejected_no_data = 0
    target_collect = int(target_total * 1.5)  # over-collect 50%; OPSIN will trim

    print(f"Phase 1 — Collecting up to {target_collect} candidates from PubChem...", flush=True)

    for source_kind, value in candidate_iter(seed):
        if len(candidates) >= target_collect:
            break
        if attempts > target_collect * 4:
            print(f"  Giving up after {attempts} attempts (sample pool sparse)", flush=True)
            break
        attempts += 1

        if source_kind == "smiles":
            try:
                canonical = canonicalize(value)
                key = inchikey(canonical)
            except Exception:
                continue
            data = fetch_by_inchikey(key)
        else:
            data = fetch_by_cid(value)
            if not data:
                rejected_no_data += 1
                continue
            try:
                canonical = canonicalize(data["smiles"])
                key = inchikey(canonical)
            except Exception:
                continue

        if not data or not data.get("iupac_name"):
            rejected_no_data += 1
            continue
        if key in seen_keys:
            rejected_dup += 1
            continue
        seen_keys.add(key)

        candidates.append({
            "smiles_input": value if source_kind == "smiles" else data["smiles"],
            "canonical_smiles": canonical,
            "inchikey": key,
            "iupac_name": data["iupac_name"],
        })

        if len(candidates) % 25 == 0:
            print(
                f"  [{len(candidates)}/{target_collect}] attempts={attempts} "
                f"dups={rejected_dup} no_data={rejected_no_data}",
                flush=True,
            )

    print(
        f"Collected {len(candidates)} PubChem candidates "
        f"(attempts={attempts}, dups={rejected_dup}, no_data={rejected_no_data})",
        flush=True,
    )
    return candidates


def opsin_batch_filter(candidates: list[dict], chunk_size: int = 100) -> list[dict]:
    """Phase 2: Batch through OPSIN; keep only candidates whose name round-trips.

    Each chunk does ONE Java JVM invocation across `chunk_size` names — ~45x
    faster than per-name calls.
    """
    print(
        f"\nPhase 2 — OPSIN batch filter on {len(candidates)} candidates "
        f"(chunks of {chunk_size})...",
        flush=True,
    )
    try:
        from py2opsin import py2opsin
    except ImportError:
        print("ERROR: py2opsin not installed. Run `pip install smiles2iupac[ml]`.")
        return []

    survivors: list[dict] = []
    n = len(candidates)
    for chunk_start in range(0, n, chunk_size):
        chunk = candidates[chunk_start:chunk_start + chunk_size]
        names = [c["iupac_name"] for c in chunk]
        try:
            back_smiles = py2opsin(names, output_format="SMILES")
        except Exception as e:
            print(f"  chunk failure at {chunk_start}: {e}; skipping chunk", flush=True)
            continue
        if not isinstance(back_smiles, list):
            back_smiles = [back_smiles]

        for cand, back in zip(chunk, back_smiles):
            if not back:
                continue
            try:
                back_mol = Chem.MolFromSmiles(back)
                if back_mol is None:
                    continue
                back_key = rdkit_inchi.MolToInchiKey(back_mol)
            except Exception:
                continue
            # Full InChIKey match (skeleton + stereo + protonation)
            if back_key == cand["inchikey"]:
                survivors.append(cand)

        print(
            f"  chunk {chunk_start // chunk_size + 1}/"
            f"{(n + chunk_size - 1) // chunk_size}: "
            f"{len(survivors)} survivors so far",
            flush=True,
        )

    print(
        f"OPSIN survivors: {len(survivors)}/{n} ({100 * len(survivors) / n:.1f}%)",
        flush=True,
    )
    return survivors


def categorize_and_balance(survivors: list[dict], target_total: int) -> list[dict]:
    """Phase 3: Categorize each survivor, respecting per-category targets."""
    rows: list[dict] = []
    counts: dict[str, int] = {cat: 0 for cat in CATEGORY_TARGETS}

    for cand in survivors:
        if sum(counts.values()) >= target_total:
            break
        mol = Chem.MolFromSmiles(cand["canonical_smiles"])
        if mol is None:
            continue
        category = categorize(cand["canonical_smiles"], mol)
        if counts[category] >= CATEGORY_TARGETS.get(category, 0):
            # Reassign to first short bucket so we don't waste verified rows
            short = [c for c, t in CATEGORY_TARGETS.items() if counts[c] < t]
            if not short:
                continue
            category = short[0]

        row_id = hashlib.sha256(cand["canonical_smiles"].encode()).hexdigest()[:16]
        rows.append({
            "id": row_id,
            "smiles_input": cand["smiles_input"],
            "canonical_smiles": cand["canonical_smiles"],
            "inchikey": cand["inchikey"],
            "iupac_name": cand["iupac_name"],
            "category": category,
            "source": "pubchem-verified",
        })
        counts[category] += 1

    print("\n--- Per-category counts ---")
    for cat, target in CATEGORY_TARGETS.items():
        got = counts[cat]
        marker = "OK" if got >= target else "SHORT"
        print(f"  {cat:25} {got:3}/{target:3}  [{marker}]")
    print(f"\nTotal: {len(rows)} rows")
    return rows


def build(target_total: int, seed: int) -> list[dict]:
    candidates = collect_pubchem_candidates(target_total, seed)
    if not candidates:
        return []
    survivors = opsin_batch_filter(candidates)
    return categorize_and_balance(survivors, target_total)


def write_csv(rows: list[dict], path: Path) -> str:
    """Write rows + return dataset_version hash."""
    fieldnames = [
        "id", "smiles_input", "canonical_smiles", "inchikey",
        "iupac_name", "category", "source", "dataset_version",
    ]
    sortable = sorted(rows, key=lambda r: r["id"])
    version_input = "\n".join(
        f"{r['id']}|{r['canonical_smiles']}|{r['iupac_name']}" for r in sortable
    )
    version = "sha256:" + hashlib.sha256(version_input.encode()).hexdigest()[:16]
    for r in rows:
        r["dataset_version"] = version

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda r: (r["category"], r["id"])))

    return version


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=TARGET_TOTAL,
                    help=f"target row count (default {TARGET_TOTAL})")
    ap.add_argument("--seed", type=int, default=42, help="PubChem CID sampling seed")
    ap.add_argument("--output", type=Path, default=OUTPUT_CSV)
    args = ap.parse_args()

    rows = build(args.limit, args.seed)
    if not rows:
        print("No rows produced; aborting.", file=sys.stderr)
        return 1
    version = write_csv(rows, args.output)
    print(f"\nWrote {len(rows)} rows to {args.output}")
    print(f"dataset_version: {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
