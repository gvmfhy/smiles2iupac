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
# Defaults match what the web/UI typically wants: PubChem on, STOUT off.
pipeline = Pipeline(use_pubchem=True, use_stout=False)

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

    # Per-request flag overrides without rebuilding the pipeline.
    prev_svg, prev_syn = pipeline.include_svg, pipeline.fetch_synonyms
    pipeline.include_svg = include_svg
    pipeline.fetch_synonyms = fetch_synonyms
    try:
        result = pipeline.convert(smiles)
    finally:
        pipeline.include_svg, pipeline.fetch_synonyms = prev_svg, prev_syn

    return JSONResponse(content=result.model_dump(mode="json"))


@app.post("/batch")
def batch(
    file: UploadFile = File(...),
    column: str = Form("smiles"),
) -> StreamingResponse:
    raw = file.file.read()
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

    rows = list(reader)  # Materialize so the closed UploadFile is fine downstream.

    def lines() -> Iterator[str]:
        for row in rows:
            smiles = (row.get(column) or "").strip()
            if not smiles:
                continue
            result = pipeline.convert(smiles)
            yield json.dumps(result.model_dump(mode="json")) + "\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson")
