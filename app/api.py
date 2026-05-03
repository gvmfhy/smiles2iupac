"""FastAPI surface for smiles2iupac.

Endpoints:
- GET /health           -> liveness probe
- GET /convert?smiles=  -> single conversion, returns the Result as JSON
- POST /batch           -> CSV upload; streams NDJSON, one Result per row

A single module-level Pipeline is shared across requests so the SQLite
cache stays warm for the life of the process.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Iterator

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from smiles2iupac import __version__
from smiles2iupac.pipeline import Pipeline

# One pipeline per process — shared across requests so the cache warms up.
pipeline = Pipeline(use_pubchem=True)

app = FastAPI(
    title="smiles2iupac",
    description="Reliable SMILES -> IUPAC name conversion",
    version=__version__,
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.get("/convert")
def convert(
    smiles: str | None = Query(None, description="SMILES string"),
    include_svg: bool = Query(False),
    fetch_synonyms: bool = Query(False),
) -> JSONResponse:
    if not smiles:
        raise HTTPException(status_code=400, detail="missing required query parameter: smiles")

    # Per-call kwargs — never mutate shared pipeline state under concurrent requests.
    result = pipeline.convert(
        smiles,
        include_svg=include_svg,
        fetch_synonyms=fetch_synonyms,
    )
    return JSONResponse(content=result.model_dump(mode="json"))


# Soft cap: 10 MB / ~250k SMILES is plenty for a free public endpoint and
# prevents trivial DoS via multi-GB upload. Hosts that need bigger batches
# should run their own instance with this raised.
MAX_BATCH_BYTES = 10 * 1024 * 1024


@app.post("/batch")
def batch(
    file: UploadFile = File(...),
    column: str = Form("smiles"),
) -> StreamingResponse:
    # Read with a hard size cap rather than file.read() (which would slurp
    # the whole upload into memory regardless of how large it is).
    raw = file.file.read(MAX_BATCH_BYTES + 1)
    if len(raw) > MAX_BATCH_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"upload exceeds {MAX_BATCH_BYTES} bytes; run your own instance for larger batches",
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise HTTPException(status_code=400, detail=f"file is not valid UTF-8: {e}") from e

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or column not in reader.fieldnames:
        raise HTTPException(
            status_code=400,
            detail=f"column '{column}' not found; available: {reader.fieldnames}",
        )

    # Materialize iterator into a list so the StreamingResponse generator can
    # outlive the request handler (FastAPI closes UploadFile on return).
    # Bounded by MAX_BATCH_BYTES above, so memory is safely capped.
    rows = list(reader)

    def lines() -> Iterator[str]:
        for row in rows:
            smiles_in = (row.get(column) or "").strip()
            if not smiles_in:
                continue
            result = pipeline.convert(smiles_in)
            yield json.dumps(result.model_dump(mode="json")) + "\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson")
