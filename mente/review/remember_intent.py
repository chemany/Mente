"""Shared narrow remember-intent parsing helpers."""

from __future__ import annotations

import re

from mente.memory.fact_normalization import normalize_memory_fact_text


_REMEMBER_RE = re.compile(r"^\s*remember(?:\s+that|\s+this|:)?\s+(.+?)\s*$", re.IGNORECASE)
_CHINESE_REMEMBER_RE = re.compile(
    r"(?:^|[，,。；;!！?？\s])(?:(?:那就|就|请)\s*)?(?:帮我)?"
    r"(?:记住|记一下|加入(?:你的|我的|到)?记忆|写入记忆|保存(?:到)?记忆)"
    r"(?:[:：，,]|\s+)?(.+?)\s*$"
)


def extract_explicit_remember_intent_fact(line: str) -> str | None:
    """Return the normalized fact for one explicit remember-intent line."""

    normalized_line = " ".join(line.strip().split())
    if not normalized_line:
        return None

    remember_match = _REMEMBER_RE.match(normalized_line)
    if remember_match is not None:
        return normalize_memory_fact_text(remember_match.group(1))

    chinese_remember_match = _CHINESE_REMEMBER_RE.search(normalized_line)
    if chinese_remember_match is not None:
        return normalize_memory_fact_text(chinese_remember_match.group(1))

    return None


def extract_explicit_remember_intent_facts(text: str) -> list[str]:
    """Return unique normalized remember-intent facts from one text blob."""

    facts: list[str] = []
    seen: set[str] = set()
    for raw_line in text.splitlines():
        fact = extract_explicit_remember_intent_fact(raw_line)
        if not fact or fact in seen:
            continue
        seen.add(fact)
        facts.append(fact)
    return facts
