"""Static definitions of the six research questions and which modules feed each one.

These are the questions as posed by the project brief, not answers.
"""

from __future__ import annotations

from typing import TypedDict


class Question(TypedDict):
    """One research question and the modules/pages that collect evidence for it."""

    id: str
    title: str
    prompt: str
    modules: list[str]
    page: str


QUESTIONS: list[Question] = [
    {
        "id": "Q1",
        "title": "Data organization",
        "prompt": "How is Kalshi sports data organized (series, events, markets, fields)?",
        "modules": ["M2", "M1"],
        "page": "/schema",
    },
    {
        "id": "Q2",
        "title": "Timestamps",
        "prompt": "Where do timestamps come from, and how precise and complete are they?",
        "modules": ["M3"],
        "page": "/timestamps",
    },
    {
        "id": "Q3",
        "title": "Live vs archived",
        "prompt": "What data is live versus archived, and how far back can it be retrieved?",
        "modules": ["M4"],
        "page": "/depth",
    },
    {
        "id": "Q4",
        "title": "Practical limits",
        "prompt": "What are the practical limits: authentication, rate limits, pagination?",
        "modules": ["M1", "M5"],
        "page": "/limits",
    },
    {
        "id": "Q5",
        "title": "Endpoints that matter",
        "prompt": "Which endpoints matter for comparing Kalshi prices with sportsbook odds?",
        "modules": ["M1"],
        "page": "/endpoints",
    },
    {
        "id": "Q6",
        "title": "REST vs WebSocket",
        "prompt": "How do REST polling and the WebSocket feed compare for live price capture?",
        "modules": ["M6"],
        "page": "/rest-vs-ws",
    },
]

QUESTION_IDS = frozenset(q["id"] for q in QUESTIONS)
