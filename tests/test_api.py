"""Tests for the FastAPI surface (offline / mocked Pipeline)."""

from __future__ import annotations

import io
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api import app
from smiles2iupac.result import Result, Source


def _fake_result(smiles: str = "CCO", name: str = "ethanol") -> Result:
    return Result(
        smiles=smiles,
        canonical_smiles=smiles,
        name=name,
        confidence=1.0,
        source=Source.PUBCHEM,
        inchi=f"InChI=1S/{name}",
        inchikey="LFQSCWFLJHTTHZ-UHFFFAOYSA-N",
        formula="C2H6O",
        mol_weight=46.069,
    )


@pytest.fixture
def client():
    return TestClient(app)


def test_health(client: TestClient):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body


def test_convert_returns_result_json(client: TestClient):
    with patch("app.api.pipeline.convert", return_value=_fake_result("CCO", "ethanol")):
        r = client.get("/convert", params={"smiles": "CCO"})
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "ethanol"
    assert body["smiles"] == "CCO"
    assert body["source"] == "pubchem"
    assert body["confidence"] == 1.0


def test_convert_missing_smiles_400(client: TestClient):
    r = client.get("/convert")
    assert r.status_code == 400


def test_batch_streams_ndjson(client: TestClient):
    csv_text = "smiles\nCCO\nCC(=O)Oc1ccccc1C(=O)O\n"
    fakes = [
        _fake_result("CCO", "ethanol"),
        _fake_result("CC(=O)Oc1ccccc1C(=O)O", "2-acetyloxybenzoic acid"),
    ]
    with patch("app.api.pipeline.convert", side_effect=fakes):
        r = client.post(
            "/batch",
            files={"file": ("in.csv", io.BytesIO(csv_text.encode()), "text/csv")},
        )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/x-ndjson")
    lines = [ln for ln in r.text.splitlines() if ln.strip()]
    assert len(lines) == 2
    parsed = [json.loads(ln) for ln in lines]
    assert parsed[0]["name"] == "ethanol"
    assert parsed[1]["name"] == "2-acetyloxybenzoic acid"


def test_batch_missing_column_400(client: TestClient):
    csv_text = "compound\nCCO\n"
    r = client.post(
        "/batch",
        files={"file": ("in.csv", io.BytesIO(csv_text.encode()), "text/csv")},
    )
    assert r.status_code == 400
