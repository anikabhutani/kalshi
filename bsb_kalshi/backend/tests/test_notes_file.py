"""The tracked notes file: written on every save, secret-checked, and restored into empty notes."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

from app.db import Database
from app.models import Note
from app.notes_file import all_notes, restore_empty_notes, write_notes_file
from tests.conftest import TEST_KEY_ID, MakeApp


def _no_network(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"unexpected request {request.url}")


async def test_saving_a_note_writes_all_questions_to_the_tracked_file(make_app: MakeApp) -> None:
    stack = make_app(_no_network)
    response = await stack.http.put("/api/notes/Q2", json={"text": "Candles end at period end."})
    assert response.status_code == 200
    assert response.json()["file_saved"] is True
    data = json.loads(stack.services.config.notes_file.read_text(encoding="utf-8"))
    assert sorted(data) == ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6"]
    assert data["Q2"]["text"] == "Candles end at period end."
    assert data["Q2"]["updated_at"].endswith("+00:00")
    assert data["Q1"] == {"text": "", "updated_at": None}


async def test_note_containing_the_key_id_never_reaches_the_file(make_app: MakeApp) -> None:
    stack = make_app(_no_network)
    await stack.http.put("/api/notes/Q1", json={"text": "safe text"})
    response = await stack.http.put("/api/notes/Q1", json={"text": f"pasted {TEST_KEY_ID}"})
    assert response.status_code == 200
    assert response.json()["file_saved"] is False
    text = stack.services.config.notes_file.read_text(encoding="utf-8")
    assert TEST_KEY_ID not in text
    assert json.loads(text)["Q1"]["text"] == "safe text"


def test_write_refuses_pem_markers(tmp_path: Path) -> None:
    path = tmp_path / "answers.json"
    notes = {"Q1": {"text": "-----BEGIN PRIVATE KEY-----", "updated_at": None}}
    assert write_notes_file(path, notes, []) is False
    assert not path.exists()


def test_restore_fills_only_missing_or_blank_notes(tmp_path: Path) -> None:
    db = Database(tmp_path / "fresh.db")
    with db.session() as session:
        session.add(Note(question_id="Q1", text="kept", updated_at=datetime.now(UTC)))
        session.add(Note(question_id="Q3", text="   ", updated_at=datetime.now(UTC)))
    path = tmp_path / "answers.json"
    path.write_text(
        json.dumps(
            {
                "Q1": {"text": "from file", "updated_at": "2026-10-01T12:00:00+00:00"},
                "Q2": {"text": "restored", "updated_at": "2026-10-01T12:00:00+00:00"},
                "Q3": {"text": "filled blank", "updated_at": None},
                "Q4": {"text": "", "updated_at": None},
                "Q9": {"text": "unknown id", "updated_at": None},
            }
        ),
        encoding="utf-8",
    )
    assert restore_empty_notes(db, path) == ["Q2", "Q3"]
    notes = all_notes(db)
    assert notes["Q1"]["text"] == "kept"
    assert notes["Q2"] == {"text": "restored", "updated_at": "2026-10-01T12:00:00+00:00"}
    assert notes["Q3"]["text"] == "filled blank"
    assert notes["Q4"]["text"] == ""


def test_restore_ignores_missing_or_malformed_file(tmp_path: Path) -> None:
    db = Database(tmp_path / "fresh.db")
    assert restore_empty_notes(db, tmp_path / "absent.json") == []
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert restore_empty_notes(db, bad) == []
    bad.write_text("[1, 2]", encoding="utf-8")
    assert restore_empty_notes(db, bad) == []
