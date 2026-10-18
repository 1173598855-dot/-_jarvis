"""Deterministic lexical memory search contract.

Phase F shared rules for every memory search surface: the fixed read-only
role tool and the HTTP ``GET /api/memory/search`` endpoint must rank and
cite identically for the same entry set. Functions operate on duck-typed
entry-like objects exposing ``id``, ``title``, ``content``, ``tags``,
``parent_id`` and ``metadata``; the Markdown store stays authoritative and
callers own redaction before snippet alignment.
"""

from __future__ import annotations

import re
from typing import Any

MAX_MEMORY_QUERY_CHARS = 256
MAX_MEMORY_SNIPPET_CHARS = 512
MAX_MEMORY_SOURCE_IDS = 8
MAX_MEMORY_SOURCE_ID_CHARS = 128
FULLTEXT_MIN_TERM_CHARS = 3

_MEMORY_QUERY_TERM_RE = re.compile(r"[0-9A-Za-z_]+|[一-鿿]")
_MEMORY_FULLTEXT_TERM_RE = re.compile(r"[0-9A-Za-z_]{3,}|[一-鿿]{3,}")


def memory_query_terms(query: str) -> tuple[str, ...]:
    """Extract deduplicated, casefolded search terms from a bounded query."""
    normalized = query.strip().casefold()
    if not normalized or len(normalized) > MAX_MEMORY_QUERY_CHARS:
        raise ValueError("Memory query must contain 1 to 256 characters")
    terms = tuple(dict.fromkeys(_MEMORY_QUERY_TERM_RE.findall(normalized)))
    if not terms:
        raise ValueError("Memory query must contain searchable terms")
    return terms


def memory_fulltext_terms(query: str) -> tuple[str, ...]:
    """Extract deduplicated terms usable by trigram full-text matching.

    Trigram matching requires at least ``FULLTEXT_MIN_TERM_CHARS`` characters,
    so single CJK characters and very short ASCII words stay on the lexical
    path. Contiguous CJK or word runs of sufficient length become one term.
    """
    normalized = query.strip().casefold()
    if not normalized or len(normalized) > MAX_MEMORY_QUERY_CHARS:
        raise ValueError("Memory query must contain 1 to 256 characters")
    terms = tuple(dict.fromkeys(_MEMORY_FULLTEXT_TERM_RE.findall(normalized)))
    if not terms:
        raise ValueError(
            "Full-text mode requires a term of at least "
            f"{FULLTEXT_MIN_TERM_CHARS} characters"
        )
    return terms


def memory_source_ids(entry: Any) -> list[str]:
    """Resolve bounded provenance ids: explicit source, parent and merges."""
    source_id = entry.metadata.get("source_id")
    parent_id = entry.parent_id
    merged_from = entry.metadata.get("merged_from")
    candidates = [source_id, parent_id]
    if isinstance(merged_from, (list, tuple)):
        candidates.extend(merged_from)

    source_ids: list[str] = []
    for candidate in candidates:
        if type(candidate) is not str:
            continue
        if 0 < len(candidate) <= MAX_MEMORY_SOURCE_ID_CHARS and candidate not in source_ids:
            source_ids.append(candidate)
        if len(source_ids) == MAX_MEMORY_SOURCE_IDS:
            break
    return source_ids


def memory_score(entry: Any, terms: tuple[str, ...]) -> int:
    """Deterministic lexical score: title 5x, tags 3x, body 1x per term."""
    title = entry.title.casefold()
    content = entry.content.casefold()
    tags = [tag.casefold() for tag in entry.tags if isinstance(tag, str)]
    score = 0
    for term in terms:
        score += 5 * title.count(term)
        score += 3 * sum(tag.count(term) for tag in tags)
        score += content.count(term)
    return score


def memory_matches(entry: Any, terms: tuple[str, ...]) -> bool:
    """An entry matches when at least one term occurs in title, body or tags."""
    title = entry.title.casefold()
    content = entry.content.casefold()
    tags = [tag.casefold() for tag in entry.tags if isinstance(tag, str)]
    return any(
        term in title or term in content or any(term in tag for tag in tags)
        for term in terms
    )


def memory_snippet_text(redacted_content: str, terms: tuple[str, ...]) -> str:
    """Align a bounded snippet at the first term match in redacted content."""
    redacted_lower = redacted_content.casefold()
    positions = [
        position
        for position in (redacted_lower.find(term) for term in terms)
        if position >= 0
    ]
    if not positions:
        return redacted_content[:MAX_MEMORY_SNIPPET_CHARS]
    position = min(positions)
    margin = max(0, (MAX_MEMORY_SNIPPET_CHARS - len(terms[0])) // 2)
    start = max(0, position - margin)
    return redacted_content[start:start + MAX_MEMORY_SNIPPET_CHARS]


__all__ = [
    "FULLTEXT_MIN_TERM_CHARS",
    "MAX_MEMORY_QUERY_CHARS",
    "MAX_MEMORY_SNIPPET_CHARS",
    "MAX_MEMORY_SOURCE_IDS",
    "MAX_MEMORY_SOURCE_ID_CHARS",
    "memory_fulltext_terms",
    "memory_matches",
    "memory_query_terms",
    "memory_score",
    "memory_snippet_text",
    "memory_source_ids",
]
