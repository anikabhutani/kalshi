"""M8 export: placeholders for unwritten notes, no secrets, no generated conclusions."""

from __future__ import annotations

import base64
import re
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from app.analysis.export import (
    NO_DATA,
    NOT_CONFIRMED,
    NOTE_PLACEHOLDER,
    PNG_MAGIC,
    ExportData,
    ExportError,
    build_appendix,
    build_tables,
    decode_charts,
    find_leaks,
    md_cell,
    pem_fragments,
)
from app.questions import QUESTIONS
from tests.conftest import TEST_KEY_ID, MakeApp

TINY_PNG = base64.b64encode(PNG_MAGIC + b"\x00" * 16).decode()
INTERPRETIVE = re.compile(r"\b(recommend\w*|suggest\w*|conclu\w*|therefore|likely|should)\b", re.IGNORECASE)


def empty_data(**overrides: object) -> ExportData:
    base: dict[str, object] = {
        "generated_at": datetime(2026, 10, 1, tzinfo=UTC),
        "openapi_title": "Kalshi Trade API",
        "openapi_version": "3.0.0",
        "asyncapi_version": "1.0.0",
        "settings": {"base_url": "https://example.invalid/trade-api/v2", "rate_limit_rps": 2, "rate_limit_burst": 2},
        "questions": QUESTIONS,
        "notes": {},
        "requests": [],
        "jobs": [],
        "ratings": [],
        "spec_auth": {},
        "rate_doc": {"tiers": []},
    }
    base.update(overrides)
    return ExportData(**base)  # type: ignore[arg-type]


def test_appendix_has_placeholder_per_unwritten_question_and_no_interpretation() -> None:
    data = empty_data(notes={"Q2": "Typed by me: candles end at period end."})
    tables = build_tables(data)
    text = build_appendix(data, tables, ["appendix.md"])
    assert text.count(NOTE_PLACEHOLDER) == 5
    assert "Typed by me: candles end at period end." in text
    for q in QUESTIONS:
        assert f"### {q['id']}. {q['title']}" in text
    assert text.count(NOT_CONFIRMED) == 2
    assert NO_DATA in text
    assert not INTERPRETIVE.search(text.replace("Typed by me: candles end at period end.", ""))


def test_m6_tables_from_stored_recorder_result() -> None:
    result = {
        "params": {"market_ticker": "MKT-1", "channels": ["ticker"], "poll_interval_s": 5},
        "recorded_s": 60.0,
        "connections": [{"status": 101}],
        "reconnects": 0,
        "ws": {"messages": 12, "latency": {"ticker": {"recv_minus_ts_ms": {"median": 40}, "recv_minus_sending_ts_ms": {}}}},
        "rest": {"polls": 12},
        "comparison": {"rest_missed_changes": 3, "per_interval": [{"start_ms": 1, "end_ms": 2, "ws_changes": 4, "rest_changed": True, "missed": 3}]},
        "trades": {"matched": 2},
    }
    spec_rows = [{"aspect": "Authentication", "rest": "a", "rest_source": "openapi.yaml", "websocket": "b", "ws_source": "asyncapi.yaml"}]
    data = empty_data(latest={"m6_recorder": {"id": "J", "finished_at": "t", "result": result}}, ws_spec_rows=spec_rows)
    tables = {t.name: t for t in build_tables(data)}
    metrics = dict((r[0], r[1]) for r in tables["m6_recorder_metrics"].rows)
    assert metrics["ws_messages"] == 12 and metrics["rest_missed_changes"] == 3 and metrics["trades_matched"] == 2
    assert metrics["latency_ticker_recv_minus_ts_ms"] == {"median": 40}
    assert tables["m6_poll_intervals"].rows == [[1, 2, 4, True, 3]]
    assert tables["m6_spec_comparison"].rows[0][0] == "Authentication"
    text = build_appendix(data, list(tables.values()), [])
    assert "## REST vs WebSocket (M6)" in text and "rest_missed_changes" in text


def test_md_cell_escapes_table_breaking_characters() -> None:
    assert md_cell("a|b\nc") == "a\\|b c"
    assert md_cell(None) == ""
    assert md_cell(True) == "yes"
    assert md_cell(1.5) == "1.5"
    assert md_cell({"k": [1]}) == '{"k":[1]}'


def test_decode_charts_validates_name_and_png() -> None:
    assert decode_charts([{"name": "m4-depth", "png_base64": TINY_PNG}])[0].png.startswith(PNG_MAGIC)
    with pytest.raises(ExportError):
        decode_charts([{"name": "../evil", "png_base64": TINY_PNG}])
    with pytest.raises(ExportError):
        decode_charts([{"name": "x", "png_base64": base64.b64encode(b"GIF89a").decode()}])
    with pytest.raises(ExportError):
        decode_charts([{"name": "x", "png_base64": "not base64!"}])
    with pytest.raises(ExportError):
        decode_charts([{"name": "x", "png_base64": TINY_PNG}, {"name": "x", "png_base64": TINY_PNG}])


def test_leak_check_names_files_not_secrets() -> None:
    pem = "-----BEGIN PRIVATE KEY-----\n" + "A" * 64 + "\n-----END PRIVATE KEY-----\n"
    fragments = pem_fragments(pem)
    assert fragments == ["A" * 64]
    files = {"ok.csv": "fine", "bad.md": f"id {TEST_KEY_ID}", "pem.csv": "x" + "A" * 64, "marker.md": "-----BEGIN"}
    assert sorted(find_leaks(files, [TEST_KEY_ID, *fragments])) == ["bad.md", "marker.md", "pem.csv"]


def _public_ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"exchange_active": True, "trading_active": True})


async def test_export_end_to_end_contains_no_secrets(make_app: MakeApp) -> None:
    stack = make_app(_public_ok)
    await stack.services.client.call("GET", "/exchange/status", module="M0")
    assert (await stack.http.put("/api/notes/Q4", json={"text": "My own words."})).status_code == 200
    stored = (await stack.http.get("/api/notes")).json()["Q4"]
    assert stored["text"] == "My own words." and stored["updated_at"].endswith("+00:00")

    res = await stack.http.post("/api/m8/export", json={"charts": [{"name": "m5-ramp-latency", "png_base64": TINY_PNG}]})
    assert res.status_code == 200, res.text
    export = res.json()
    paths = {f["path"] for f in export["files"]}
    assert {"appendix.md", "csv/requests.csv", "csv/auth_matrix.csv", "csv/notes.csv", "charts/m5-ramp-latency.png"} <= paths

    folder = Path(export["path"])
    key_text = stack.services.config.private_key_text()
    assert key_text is not None
    fragments = pem_fragments(key_text)
    for file in folder.rglob("*"):
        if file.suffix in (".md", ".csv"):
            text = file.read_text(encoding="utf-8")
            assert TEST_KEY_ID not in text
            assert "-----BEGIN" not in text
            assert not any(f in text for f in fragments)
    appendix = (folder / "appendix.md").read_text(encoding="utf-8")
    assert "My own words." in appendix
    assert appendix.count(NOTE_PLACEHOLDER) == 5
    assert "/exchange/status" in appendix

    listed = (await stack.http.get("/api/m8/exports")).json()
    assert listed[0]["name"] == export["name"]
    ok = await stack.http.get(f"/api/m8/exports/{export['name']}/files/appendix.md")
    assert ok.status_code == 200 and "evidence appendix" in ok.text
    for bad in ("..%2F..%2Fkalshi_recon.db", "%2E%2E/kalshi_recon.db"):
        assert (await stack.http.get(f"/api/m8/exports/{export['name']}/files/{bad}")).status_code == 404
    assert (await stack.http.get("/api/m8/exports/not-an-export/files/appendix.md")).status_code == 404


async def test_export_aborts_when_a_note_contains_the_key_id(make_app: MakeApp) -> None:
    stack = make_app(_public_ok)
    await stack.http.put("/api/notes/Q1", json={"text": f"oops pasted {TEST_KEY_ID}"})
    res = await stack.http.post("/api/m8/export", json={"charts": []})
    assert res.status_code == 422
    assert TEST_KEY_ID not in res.text
    assert "appendix.md" in res.json()["detail"]
    assert list(stack.services.config.exports_dir.iterdir()) == []
