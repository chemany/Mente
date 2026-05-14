"""Shared fact normalization and narrow slot classification helpers."""

from __future__ import annotations

import hashlib
import re
import unicodedata

from pydantic import BaseModel

_REMEMBER_RE = re.compile(r"^\s*remember(?:\s+that|\s+this|:)?\s+(.+?)\s*$", re.IGNORECASE)
_CHINESE_REMEMBER_RE = re.compile(
    r"^(?:(?:那就|就|请)\s*)?(?:帮我)?"
    r"(?:记住|记一下|加入(?:你的|我的|到)?记忆|写入记忆|保存(?:到)?记忆)"
    r"(?:[:：，,]|\s+)?(.+?)\s*$"
)
_ENGLISH_NAME_RE = re.compile(r"^my name is\s+.+$", re.IGNORECASE)
_CHINESE_NAME_RE = re.compile(r"^(?:我叫|我的名字是).+$")
_ENGLISH_RESPONSE_LANGUAGE_RE = re.compile(
    r"^i(?:'d)?\s+prefer\s+.+?(?:chinese|english).*$",
    re.IGNORECASE,
)
_CHINESE_RESPONSE_LANGUAGE_RE = re.compile(
    r"^(?:我(?:更)?喜欢|我偏好).*(?:中文回答|中文回复|用中文|英文回答|英文回复|用英文).*$"
)


class FactIdentity(BaseModel):
    """Deterministic identity for one normalized memory fact."""

    normalized_fact: str
    fact_key: str
    slot_key: str | None = None


def build_fact_identity(text: str) -> FactIdentity:
    """Normalize one fact and attach deterministic identity metadata."""

    normalized_fact = normalize_memory_fact_text(text)
    return FactIdentity(
        normalized_fact=normalized_fact,
        fact_key=hashlib.sha256(normalized_fact.encode("utf-8")).hexdigest(),
        slot_key=classify_memory_slot(normalized_fact),
    )


def normalize_memory_fact_text(text: str) -> str:
    """Normalize whitespace, fullwidth variants, and explicit remember prefixes."""

    normalized = unicodedata.normalize("NFKC", text or "")
    lines = [" ".join(line.strip().split()) for line in normalized.splitlines()]
    normalized = "\n".join(line for line in lines if line)
    if not normalized:
        return ""

    for pattern in (_REMEMBER_RE, _CHINESE_REMEMBER_RE):
        match = pattern.match(normalized)
        if match is not None:
            normalized = match.group(1).strip()
            break

    normalized = normalized.rstrip(" \t\r\n：:")
    return normalized


def classify_memory_slot(normalized_fact: str) -> str | None:
    """Return the narrow supported slot key for one fact, if any."""

    if not normalized_fact:
        return None
    if _ENGLISH_NAME_RE.match(normalized_fact) or _CHINESE_NAME_RE.match(normalized_fact):
        return "identity:name"
    if _ENGLISH_RESPONSE_LANGUAGE_RE.match(normalized_fact) or _CHINESE_RESPONSE_LANGUAGE_RE.match(
        normalized_fact
    ):
        return "preference:response_language"
    return None
