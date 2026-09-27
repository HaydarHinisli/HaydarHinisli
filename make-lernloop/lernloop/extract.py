"""HTML → Titel, Abschnitte (nach Überschriften), Links, sichtbare Datumsangaben.

Es wird nur Text extrahiert; Skripte, Styles und Navigationselemente werden verworfen.
Nichts aus der Seite wird ausgeführt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin

_SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form", "button", "iframe", "template"}
_BLOCK = {"p", "div", "li", "tr", "br", "pre", "table", "ul", "ol", "section", "article", "blockquote",
          "dd", "dt", "td", "th", "figcaption", "summary", "details"}
_HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4}
_VOID = {"br", "img", "hr", "input", "meta", "link", "source", "wbr", "area", "base", "col", "embed", "track"}


@dataclass
class Section:
    heading_path: str
    anchor: str | None
    text: str


@dataclass
class Page:
    title: str
    sections: list[Section]
    links: list[tuple[str, str]] = field(default_factory=list)  # (absolute URL, Linktext)
    updated_at: str | None = None


class _Parser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.skip_depth = 0
        self.skip_stack: list[str] = []
        self.title_parts: list[str] = []
        self.in_title = False
        self.heading_level: int | None = None
        self.heading_parts: list[str] = []
        self.heading_anchor: str | None = None
        self.path: list[tuple[int, str]] = []
        self.current_anchor: str | None = None
        self.buf: list[str] = []
        self.sections: list[Section] = []
        self.links: list[tuple[str, str]] = []
        self.link_href: str | None = None
        self.link_text: list[str] = []
        self.updated_at: str | None = None

    # Hilfen
    def _flush(self) -> None:
        text = _clean("".join(self.buf))
        if text:
            heading = " > ".join(t for _, t in self.path) or "(Einleitung)"
            self.sections.append(Section(heading, self.current_anchor, text))
        self.buf = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta":
            prop = (a.get("property") or a.get("name") or "").lower()
            if prop in ("article:modified_time", "last-modified", "dc.date.modified", "article:published_time") \
                    and a.get("content") and not self.updated_at:
                self.updated_at = a["content"]
            return
        if tag == "time" and a.get("datetime") and not self.updated_at:
            self.updated_at = a["datetime"]
        if self.skip_depth:
            if tag in _SKIP:
                self.skip_depth += 1
            return
        if tag in _SKIP:
            self.skip_depth = 1
            return
        if tag == "title":
            self.in_title = True
        elif tag in _HEADINGS:
            self._flush()
            self.heading_level = _HEADINGS[tag]
            self.heading_parts = []
            self.heading_anchor = a.get("id")
        elif tag == "a" and a.get("href"):
            self.link_href = urljoin(self.base_url, a["href"])
            self.link_text = []
        elif tag in _BLOCK and tag not in _VOID:
            self.buf.append("\n")
        elif tag == "br":
            self.buf.append("\n")
        if a.get("id") and tag not in _HEADINGS and self.heading_level is None and not self.buf:
            self.current_anchor = a.get("id")

    def handle_endtag(self, tag):
        if self.skip_depth:
            if tag in _SKIP:
                self.skip_depth -= 1
            return
        if tag == "title":
            self.in_title = False
        elif tag in _HEADINGS and self.heading_level is not None:
            level = self.heading_level
            text = _clean("".join(self.heading_parts))
            self.path = [(lvl, t) for lvl, t in self.path if lvl < level]
            if text:
                self.path.append((level, text))
            self.current_anchor = self.heading_anchor
            self.heading_level = None
        elif tag == "a" and self.link_href:
            self.links.append((self.link_href, _clean("".join(self.link_text))))
            self.link_href = None
        elif tag in _BLOCK:
            self.buf.append("\n")

    def handle_data(self, data):
        if self.skip_depth:
            return
        if self.in_title:
            self.title_parts.append(data)
            return
        if self.heading_level is not None:
            self.heading_parts.append(data)
            return
        if self.link_href is not None:
            self.link_text.append(data)
        self.buf.append(data)

    def close(self):
        super().close()
        self._flush()


def _clean(text: str) -> str:
    lines = [re.sub(r"[ \t ]+", " ", ln).strip() for ln in text.splitlines()]
    out: list[str] = []
    for ln in lines:
        if ln or (out and out[-1]):
            out.append(ln)
    return "\n".join(out).strip()


def parse_html(html: str, base_url: str, min_section_chars: int = 40) -> Page:
    p = _Parser(base_url)
    p.feed(html)
    p.close()
    title = _clean("".join(p.title_parts)) or (p.path[0][1] if p.path else base_url)
    # Sehr kurze Abschnitte mit dem nächsten zusammenlegen, damit Zitate Kontext behalten.
    merged: list[Section] = []
    for s in p.sections:
        if merged and len(merged[-1].text) < min_section_chars and merged[-1].heading_path == s.heading_path:
            merged[-1].text += "\n" + s.text
        else:
            merged.append(s)
    return Page(title=title, sections=merged, links=p.links, updated_at=p.updated_at)


def normalize_for_quote(text: str) -> str:
    """Vergleichsform für Zitatprüfung: Anführungszeichen/Striche vereinheitlicht, Leerraum zusammengefasst."""
    table = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-",
                           "—": "-", " ": " ", "…": "..."})
    return re.sub(r"\s+", " ", text.translate(table)).strip().lower()


def quote_in_text(quote: str, text: str, min_len: int = 12) -> bool:
    """True, wenn das Zitat (normalisiert) wörtlich im Text steht. Auslassungen „…“ trennen Teilzitate."""
    q = normalize_for_quote(quote)
    if len(q) < min_len:
        return False
    t = normalize_for_quote(text)
    parts = [part.strip() for part in q.split("...") if part.strip()]
    if not parts:
        return False
    pos = 0
    for part in parts:
        if len(part) < 6:
            return False
        idx = t.find(part, pos)
        if idx < 0:
            return False
        pos = idx + len(part)
    return True
