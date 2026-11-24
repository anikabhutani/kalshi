"""Tracked copy of the Q1-Q6 notes, so the user's answers survive a fresh clone.

The SQLite database is git-ignored. Every note save also rewrites ``notes/answers.json`` at the
repo root (not ignored), and on startup any empty note is filled from that file.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.analysis.export import find_leaks
from app.analysis.timestamps import stored_utc_iso
from app.db import Database
from app.models import Note
from app.questions import QUESTION_IDS


def all_notes(db: Database) -> dict[str, dict[str, str | None]]:
    """Every question's note (empty text where nothing was written), keyed by question id."""
    with db.session() as session:
        rows = {n.question_id: n for n in session.scalars(select(Note))}
    return {
        qid: {
            "text": rows[qid].text if qid in rows else "",
            "updated_at": stored_utc_iso(rows[qid].updated_at) if qid in rows else None,
        }
        for qid in sorted(QUESTION_IDS)
    }


def write_notes_file(path: Path, notes: dict[str, dict[str, str | None]], secrets: Iterable[str]) -> bool:
    """Write the notes as JSON; refuse (return False) if any text contains a secret."""
    text = json.dumps(notes, indent=2, ensure_ascii=False) + "\n"
    if find_leaks({path.name: text}, secrets):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    partial.write_text(text, encoding="utf-8")
    partial.replace(path)
    return True


def _parse_time(value: Any) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            pass
    return datetime.now(UTC)


def restore_empty_notes(db: Database, path: Path) -> list[str]:
    """Fill notes that are missing or blank from the file; never overwrite existing text.

    Returns the question ids that were restored. A missing or unreadable file restores nothing.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    restored: list[str] = []
    with db.session() as session:
        for qid, entry in data.items():
            if qid not in QUESTION_IDS or not isinstance(entry, dict):
                continue
            text = entry.get("text")
            if not isinstance(text, str) or not text.strip():
                continue
            note = session.get(Note, qid)
            if note is not None and note.text.strip():
                continue
            when = _parse_time(entry.get("updated_at"))
            if note is None:
                session.add(Note(question_id=qid, text=text, updated_at=when))
            else:
                note.text, note.updated_at = text, when
            restored.append(qid)
    return restored
