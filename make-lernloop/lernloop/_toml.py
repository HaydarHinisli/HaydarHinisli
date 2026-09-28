"""Kleiner TOML-Leser für Python < 3.11 (dort fehlt ``tomllib``).

Unterstützt genau das, was lernloop.toml und topics.toml verwenden: Kommentare, [tabelle],
[[tabellen-array]], Schlüssel = Wert mit Zeichenketten, Zahlen (auch mit _), true/false,
(mehrzeiligen) Arrays und Inline-Tabellen. Ab Python 3.11 wird das eingebaute tomllib genutzt.
"""

from __future__ import annotations

import re


class TOMLDecodeError(ValueError):
    pass


def load(f) -> dict:
    return loads(f.read().decode("utf-8"))


def loads(text: str) -> dict:
    root: dict = {}
    current = root
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = _strip_comment(lines[i]).strip()
        i += 1
        if not line:
            continue
        if line.startswith("[["):
            name = line[2:line.index("]]")].strip()
            current = {}
            _table(root, name, array=True).append(current)
            continue
        if line.startswith("["):
            current = _table(root, line[1:line.index("]")].strip())
            continue
        if "=" not in line:
            raise TOMLDecodeError(f"Zeile {i}: '=' erwartet")
        key, value = line.split("=", 1)
        value = value.strip()
        # mehrzeilige Arrays/Inline-Tabellen zusammenführen
        while _depth(value) > 0:
            if i >= len(lines):
                raise TOMLDecodeError("Unvollständiges Array")
            value += " " + _strip_comment(lines[i]).strip()
            i += 1
        parser = _ValueParser(value)
        current[_key(key.strip())] = parser.parse()
        parser.expect_end()
    return root


def _key(k: str) -> str:
    if len(k) >= 2 and k[0] == k[-1] and k[0] in "\"'":
        return k[1:-1]
    return k


def _table(root: dict, dotted: str, array: bool = False):
    parts = [_key(p.strip()) for p in dotted.split(".")]
    node = root
    for p in parts[:-1]:
        node = node.setdefault(p, {})
        if isinstance(node, list):
            node = node[-1]
    last = parts[-1]
    if array:
        return node.setdefault(last, [])
    return node.setdefault(last, {})


def _strip_comment(line: str) -> str:
    out, quote = [], None
    for ch in line:
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            out.append(ch)
        elif ch == "#":
            break
        else:
            out.append(ch)
    return "".join(out)


def _depth(s: str) -> int:
    depth, quote, esc = 0, None, False
    for ch in s:
        if quote:
            if esc:
                esc = False
            elif ch == "\\" and quote == '"':
                esc = True
            elif ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
    return depth


_NUM = re.compile(r"[+-]?[0-9][0-9_]*(\.[0-9_]+)?([eE][+-]?[0-9]+)?")
_ESC = {"n": "\n", "t": "\t", '"': '"', "\\": "\\", "r": "\r"}


class _ValueParser:
    def __init__(self, s: str):
        self.s, self.pos = s, 0

    def _ws(self):
        while self.pos < len(self.s) and self.s[self.pos] in " \t":
            self.pos += 1

    def expect_end(self):
        self._ws()
        if self.pos != len(self.s):
            raise TOMLDecodeError(f"Unerwarteter Rest: {self.s[self.pos:]!r}")

    def parse(self):
        self._ws()
        s, p = self.s, self.pos
        if p >= len(s):
            raise TOMLDecodeError("Wert fehlt")
        ch = s[p]
        if ch == '"':
            return self._basic_string()
        if ch == "'":
            end = s.index("'", p + 1)
            self.pos = end + 1
            return s[p + 1:end]
        if ch == "[":
            return self._array()
        if ch == "{":
            return self._inline_table()
        if s.startswith("true", p):
            self.pos += 4
            return True
        if s.startswith("false", p):
            self.pos += 5
            return False
        m = _NUM.match(s, p)
        if m:
            self.pos = m.end()
            text = m.group(0).replace("_", "")
            return float(text) if (m.group(1) or m.group(2)) else int(text)
        raise TOMLDecodeError(f"Unbekannter Wert: {s[p:]!r}")

    def _basic_string(self) -> str:
        s = self.s
        self.pos += 1
        out = []
        while self.pos < len(s):
            ch = s[self.pos]
            if ch == "\\":
                nxt = s[self.pos + 1]
                if nxt == "u":
                    out.append(chr(int(s[self.pos + 2:self.pos + 6], 16)))
                    self.pos += 6
                    continue
                out.append(_ESC.get(nxt, nxt))
                self.pos += 2
                continue
            if ch == '"':
                self.pos += 1
                return "".join(out)
            out.append(ch)
            self.pos += 1
        raise TOMLDecodeError("Zeichenkette nicht geschlossen")

    def _array(self) -> list:
        self.pos += 1
        items = []
        while True:
            self._ws()
            if self.s[self.pos] == "]":
                self.pos += 1
                return items
            items.append(self.parse())
            self._ws()
            if self.s[self.pos] == ",":
                self.pos += 1
            elif self.s[self.pos] != "]":
                raise TOMLDecodeError("',' oder ']' erwartet")

    def _inline_table(self) -> dict:
        self.pos += 1
        out = {}
        while True:
            self._ws()
            if self.s[self.pos] == "}":
                self.pos += 1
                return out
            m = re.compile(r'("[^"]*"|[A-Za-z0-9_.-]+)\s*=').match(self.s, self.pos)
            if not m:
                raise TOMLDecodeError("Schlüssel in Inline-Tabelle erwartet")
            self.pos = m.end()
            out[_key(m.group(1))] = self.parse()
            self._ws()
            if self.s[self.pos] == ",":
                self.pos += 1
