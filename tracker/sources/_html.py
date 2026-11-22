"""Parsers for job listings embedded in HTML. Markup is parsed, never executed or rendered."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin

Attrs = dict[str, str]
Matcher = Callable[[str, Attrs], bool]


@dataclass
class Card:
    url: str
    job_id: str = ""
    title_parts: list[str] = field(default_factory=list)
    location_parts: list[str] = field(default_factory=list)

    @property
    def title(self) -> str:
        return " ".join(" ".join(self.title_parts).split())

    @property
    def location(self) -> str:
        return " ".join(" ".join(self.location_parts).split())


def has_class(attrs: Attrs, name: str) -> bool:
    return name in attrs.get("class", "").split()


class CardParser(HTMLParser):
    """Collects job links and their locations from search-result markup.

    `is_job_link` picks the <a> elements that are job titles; their text is the
    title. `is_location` picks the element holding a job's location, which may
    sit inside or after the link. Repeated links to the same URL (sites often
    render desktop and mobile copies) merge into one card.
    """

    def __init__(self, base_url: str, is_job_link: Matcher, is_location: Matcher) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.is_job_link = is_job_link
        self.is_location = is_location
        self.cards: dict[str, Card] = {}
        self._current: Card | None = None
        self._in_link = False
        self._fresh_title = False
        self._location_tag: str | None = None
        self._location_depth = 0
        self._fresh_location = False

    def handle_starttag(self, tag, attrs):
        attributes = {key: value or "" for key, value in attrs}
        if tag == "a" and self.is_job_link(tag, attributes) and attributes.get("href"):
            url = urljoin(self.base_url, attributes["href"].strip())
            card = self.cards.get(url)
            self._fresh_title = card is None
            if card is None:
                card = self.cards[url] = Card(url=url, job_id=attributes.get("data-job-id", ""))
            self._current = card
            self._in_link = True
            self._fresh_location = not card.location_parts
            return
        if self._location_tag is not None:
            if tag == self._location_tag:
                self._location_depth += 1
            return
        if self._current is not None and self.is_location(tag, attributes):
            self._location_tag = tag
            self._location_depth = 1

    def handle_endtag(self, tag):
        if self._location_tag is not None and tag == self._location_tag:
            self._location_depth -= 1
            if self._location_depth == 0:
                self._location_tag = None
                self._fresh_location = False
            return
        if tag == "a" and self._in_link:
            self._in_link = False
            self._fresh_title = False

    def handle_data(self, data):
        if self._current is None:
            return
        if self._location_tag is not None:
            if self._fresh_location:
                self._current.location_parts.append(data)
        elif self._in_link and self._fresh_title:
            self._current.title_parts.append(data)


def parse_cards(html: str, base_url: str, is_job_link: Matcher, is_location: Matcher) -> list[Card]:
    parser = CardParser(base_url, is_job_link, is_location)
    parser.feed(html)
    parser.close()
    return [card for card in parser.cards.values() if card.title]


@dataclass
class Cell:
    text: str
    href: str = ""


class TableParser(HTMLParser):
    """Rows of the first table whose class includes `table_class`, keyed by header text."""

    def __init__(self, base_url: str, table_class: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.table_class = table_class
        self.headers: list[str] = []
        self.rows: list[dict[str, Cell]] = []
        self._table_depth = 0
        self._done = False
        self._cell: list[str] | None = None
        self._cell_href = ""
        self._row: list[Cell] | None = None
        self._header_row = False

    def handle_starttag(self, tag, attrs):
        attributes = {key: value or "" for key, value in attrs}
        if self._done:
            return
        if tag == "table":
            if self._table_depth or has_class(attributes, self.table_class):
                self._table_depth += 1
            return
        if not self._table_depth:
            return
        if tag == "tr":
            self._row, self._header_row = [], False
        elif tag in ("td", "th") and self._row is not None:
            self._cell, self._cell_href = [], ""
            self._header_row = self._header_row or tag == "th"
        elif tag == "a" and self._cell is not None and not self._cell_href:
            self._cell_href = urljoin(self.base_url, attributes.get("href", "").strip())

    def handle_endtag(self, tag):
        if not self._table_depth or self._done:
            return
        if tag == "table":
            self._table_depth -= 1
            self._done = self._table_depth == 0
        elif tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(Cell(" ".join(" ".join(self._cell).split()), self._cell_href))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._header_row:
                self.headers = [cell.text.lower() for cell in self._row]
            elif self._row:
                self.rows.append(dict(zip(self.headers, self._row, strict=False)))
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def parse_table(html: str, base_url: str, table_class: str) -> list[dict[str, Cell]]:
    parser = TableParser(base_url, table_class)
    parser.feed(html)
    parser.close()
    return parser.rows


class _JsonLdCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.blocks: list[str] = []
        self._buffer: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        attributes = {key: (value or "").lower() for key, value in attrs}
        if tag == "script" and attributes.get("type", "").strip() == "application/ld+json":
            self._buffer = []

    def handle_endtag(self, tag):
        if tag == "script" and self._buffer is not None:
            self.blocks.append("".join(self._buffer))
            self._buffer = None

    def handle_data(self, data):
        if self._buffer is not None:
            self._buffer.append(data)


def json_ld_objects(html: str) -> list[dict]:
    """Every JSON object in the page's ld+json blocks, including @graph members."""
    collector = _JsonLdCollector()
    collector.feed(html)
    collector.close()
    found: list[dict] = []

    def walk(value: object) -> None:
        if isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, dict):
            found.append(value)
            walk(value.get("@graph"))

    for block in collector.blocks:
        try:
            walk(json.loads(block))
        except ValueError:
            continue
    return found
