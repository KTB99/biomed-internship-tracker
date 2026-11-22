"""Text and date helpers for untrusted source data."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from html.parser import HTMLParser

_BLOCK_TAGS = frozenset(
    {"p", "br", "li", "div", "ul", "ol", "tr", "section", "h1", "h2", "h3", "h4", "h5", "h6"}
)
_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


class _TextExtractor(HTMLParser):
    """Collects visible text. Markup is parsed, never executed or rendered."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._hidden_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._hidden_depth += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._hidden_depth = max(0, self._hidden_depth - 1)
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._hidden_depth:
            self.parts.append(data)


def html_to_text(markup: str) -> str:
    """Return the visible text of an HTML fragment, one block per line."""
    if not markup:
        return ""
    parser = _TextExtractor()
    parser.feed(markup)
    parser.close()
    lines = (" ".join(line.split()) for line in "".join(parser.parts).splitlines())
    return "\n".join(line for line in lines if line)


def clean(value: object) -> str:
    """Collapse whitespace; None becomes an empty string."""
    if value is None:
        return ""
    return " ".join(str(value).split())


def to_iso_date(value: object) -> str | None:
    """Parse an ISO string or a Unix timestamp (seconds or milliseconds) to YYYY-MM-DD."""
    if value is None or value == "" or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        seconds = value / 1000 if value > 10**11 else value
        try:
            return datetime.fromtimestamp(seconds, tz=UTC).date().isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if text.isdigit():
        return to_iso_date(int(text))
    match = _ISO_DATE.match(text)
    if not match:
        return None
    try:
        return date(*(int(part) for part in match.groups())).isoformat()
    except ValueError:
        return None
