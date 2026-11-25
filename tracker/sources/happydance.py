"""Career sites built by the agency Happy Dance (Regeneron): server-rendered /en/jobs/ lists.

Each result is an element with class `card-job` and a `data-id`. Its first
link to a job page is the title, and a list item labelled "Location:" holds
the location. `search=` takes the keyword and `page=` numbers the pages.

J&J's careers site is built the same way, but its server ignores the keyword
and filters (the browser filters through an internal API), so J&J stays
link-only.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urljoin

from tracker.config import Company
from tracker.http import Client
from tracker.models import Lead
from tracker.sources._common import origin, search_terms
from tracker.sources._html import has_class
from tracker.text import clean

JOBS_PATH = "/en/jobs/"
MAX_PAGES = 30
_TOTAL = re.compile(r'id="js-job-search-results"[^>]*data-results="(\d+)"')
_LOCATION_LABEL = re.compile(r"^location\s*:\s*", re.IGNORECASE)


def fetch(client: Client, company: Company) -> list[Lead]:
    base = origin(company)
    leads: dict[str, Lead] = {}
    for term in search_terms(company):
        seen: set[str] = set()
        for page in range(1, MAX_PAGES + 1):
            params = {"search": term, "page": str(page)} if page > 1 else {"search": term}
            html = client.get_text(base + JOBS_PATH, params=params)
            new = [card for card in parse(html, base + "/") if card.job_id not in seen]
            for card in new:
                seen.add(card.job_id)
                leads.setdefault(
                    card.job_id,
                    Lead(
                        company=company.name,
                        platform="happydance",
                        external_id=card.job_id,
                        title=card.title,
                        url=card.url,
                        locations=[card.location] if card.location else [],
                    ),
                )
            total = _TOTAL.search(html)
            if not new or (total and len(seen) >= int(total.group(1))):
                break
    return list(leads.values())


class _Card:
    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        self.url = ""
        self.title_parts: list[str] = []
        self.location = ""

    @property
    def title(self) -> str:
        return clean(" ".join(self.title_parts))


class _Parser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.cards: list[_Card] = []
        self._card: _Card | None = None
        self._card_tag = ""
        self._card_depth = 0
        self._in_title = False
        self._place_tag = ""
        self._place_parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        attributes = {key: value or "" for key, value in attrs}
        if self._card is None:
            if has_class(attributes, "card-job") and attributes.get("data-id"):
                self._card = _Card(attributes["data-id"].strip())
                self._card_tag, self._card_depth = tag, 1
            return
        if tag == self._card_tag:
            self._card_depth += 1
        href = attributes.get("href", "")
        if tag == "a" and not self._card.url and "/jobs/" in href:
            self._card.url = urljoin(self.base_url, href.strip())
            self._in_title = True
        elif tag == "li" and not self._card.location and not self._place_tag:
            self._place_tag, self._place_parts = tag, []

    def handle_endtag(self, tag):
        if self._card is None:
            return
        if tag == "a" and self._in_title:
            self._in_title = False
        elif tag == self._place_tag:
            text = clean(" ".join(self._place_parts))
            if _LOCATION_LABEL.match(text):
                self._card.location = _LOCATION_LABEL.sub("", text)
            self._place_tag = ""
        if tag == self._card_tag:
            self._card_depth -= 1
            if self._card_depth == 0:
                if self._card.url and self._card.title:
                    self.cards.append(self._card)
                self._card = None

    def handle_data(self, data):
        if self._card is None:
            return
        if self._in_title:
            self._card.title_parts.append(data)
        elif self._place_tag:
            self._place_parts.append(data)


def parse(html: str, base_url: str) -> list[_Card]:
    parser = _Parser(base_url)
    parser.feed(html)
    parser.close()
    return parser.cards
