"""Universal INI document: reads *any* ``[SECTION]`` / ``KEY=VALUE`` file (such as the
``shader ... .ini`` preset, whose sections look like ``[FFB_TWEAKS:POSTPROCESSING]``), keeps the
order, comments and unknown keys, and writes it back unchanged except for the edits made.
"""

from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass, field
from typing import Iterator, Optional


@dataclass
class Entry:
    kind: str  # "kv" | "comment" | "blank" | "raw"
    key: str = ""
    value: str = ""
    raw: str = ""  # original text of non key/value lines

    @property
    def is_kv(self) -> bool:
        return self.kind == "kv"


@dataclass
class Section:
    name: str
    entries: list = field(default_factory=list)

    def items(self) -> Iterator[Entry]:
        return (e for e in self.entries if e.is_kv)

    def find(self, key: str) -> Optional[Entry]:
        """Last entry for ``key`` (case-insensitive) - later duplicates win, like most parsers."""
        found = None
        k = key.lower()
        for e in self.entries:
            if e.is_kv and e.key.lower() == k:
                found = e
        return found


class IniDocument:
    def __init__(self) -> None:
        self.sections: list[Section] = []
        self.newline = "\r\n"
        self.path: str | None = None

    # ------------------------------------------------------------------ parse
    @classmethod
    def parse(cls, text: str) -> "IniDocument":
        doc = cls()
        if text.startswith("﻿"):
            text = text[1:]
        if "\r\n" in text:
            doc.newline = "\r\n"
        elif "\n" in text:
            doc.newline = "\n"
        current: Section | None = None
        for line in re.split(r"\r\n|\n|\r", text):
            stripped = line.strip()
            if not stripped:
                if current is not None:
                    current.entries.append(Entry("blank"))
                continue
            if stripped.startswith("[") and "]" in stripped:
                name = stripped[1 : stripped.rindex("]")].strip()
                current = doc.section(name, create=True)
                continue
            if current is None:  # keys / comments before the first section header
                current = doc.section("", create=True)
            if stripped[0] in ";#":
                current.entries.append(Entry("comment", raw=line.rstrip()))
            elif "=" in stripped:
                key, _, value = stripped.partition("=")
                current.entries.append(Entry("kv", key.strip(), value.strip()))
            else:
                current.entries.append(Entry("raw", raw=line.rstrip()))
        for sec in doc.sections:  # trailing blanks are formatting, not data
            while sec.entries and sec.entries[-1].kind == "blank":
                sec.entries.pop()
        if doc.sections and doc.sections[0].name == "" and not doc.sections[0].entries:
            doc.sections.pop(0)
        return doc

    @classmethod
    def load(cls, path: str) -> "IniDocument":
        data = open(path, "rb").read()
        for enc in ("utf-8-sig", "utf-16", "cp1252"):
            try:
                text = data.decode(enc)
                break
            except (UnicodeDecodeError, UnicodeError):
                continue
        else:  # pragma: no cover - cp1252 decodes nearly everything
            text = data.decode("latin-1")
        doc = cls.parse(text)
        doc.path = path
        return doc

    # ---------------------------------------------------------------- serialize
    def to_text(self) -> str:
        out: list[str] = []
        for sec in self.sections:
            if sec.name != "":
                out.append(f"[{sec.name}]")
            for e in sec.entries:
                if e.kind == "kv":
                    out.append(f"{e.key}={e.value}")
                elif e.kind == "blank":
                    out.append("")
                else:
                    out.append(e.raw)
            out.append("")  # one blank line between sections
        return self.newline.join(out)

    def save(self, path: str | None = None) -> str:
        path = path or self.path
        if not path:
            raise ValueError("no file path")
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(self.to_text())
        self.path = path
        return path

    # ------------------------------------------------------------------ access
    def section(self, name: str, create: bool = False) -> Optional[Section]:
        low = name.lower()
        for sec in self.sections:
            if sec.name.lower() == low:
                return sec
        if not create:
            return None
        sec = Section(name)
        self.sections.append(sec)
        return sec

    def has(self, section: str, key: str) -> bool:
        sec = self.section(section)
        return bool(sec and sec.find(key))

    def get(self, section: str, key: str, default: Optional[str] = None) -> Optional[str]:
        sec = self.section(section)
        entry = sec.find(key) if sec else None
        return entry.value if entry else default

    def set(self, section: str, key: str, value: str) -> None:
        sec = self.section(section, create=True)
        entry = sec.find(key)
        if entry:
            entry.value = str(value)
        else:
            # keep a trailing blank line out of the way
            idx = len(sec.entries)
            while idx > 0 and sec.entries[idx - 1].kind == "blank":
                idx -= 1
            sec.entries.insert(idx, Entry("kv", key, str(value)))

    def delete(self, section: str, key: str | None = None) -> None:
        sec = self.section(section)
        if sec is None:
            return
        if key is None:
            self.sections.remove(sec)
            return
        k = key.lower()
        sec.entries = [e for e in sec.entries if not (e.is_kv and e.key.lower() == k)]

    def iter_items(self) -> Iterator[tuple]:
        """Yield ``(section, key, value)`` for every key/value pair."""
        for sec in self.sections:
            for e in sec.items():
                yield sec.name, e.key, e.value

    def section_names(self) -> list:
        return [s.name for s in self.sections]

    def count(self) -> int:
        return sum(1 for _ in self.iter_items())

    def groups(self) -> dict:
        """Top-level group (the part before ``:``) -> list of section names."""
        result: dict = {}
        for sec in self.sections:
            result.setdefault(sec.name.split(":", 1)[0], []).append(sec.name)
        return result

    def copy(self) -> "IniDocument":
        return IniDocument.parse(self.to_text())


# ------------------------------------------------------------------- value typing
def infer_type(value: str) -> str:
    """'empty' | 'bool' | 'int' | 'float' | 'embedded' | 'text'"""
    v = value.strip()
    if v == "":
        return "empty"
    if v in ("0", "1"):
        return "bool"
    if re.fullmatch(r"[+-]?\d+", v):
        return "int"
    if re.fullmatch(r"[+-]?(\d+\.\d*|\.\d+)([eE][+-]?\d+)?", v):
        return "float"
    if decode_embedded(v) is not None:
        return "embedded"
    return "text"


def decode_embedded(value: str) -> Optional[IniDocument]:
    """Some keys (``POSTPROCESSING_SCRIPT_SETTINGS``, ``SCRIPT_SETTINGS`` ...) contain a complete
    INI file encoded as base64 (often without padding). Returns the nested document or None."""
    v = value.strip()
    if len(v) < 12 or not re.fullmatch(r"[A-Za-z0-9+/_-]+={0,2}", v):
        return None
    try:
        raw = base64.b64decode(v + "=" * (-len(v) % 4), altchars=b"-_" if ("-" in v or "_" in v) else None, validate=False)
        text = raw.decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    stripped = text.lstrip()
    if not stripped.startswith("[") or "]" not in stripped.splitlines()[0]:
        return None
    return IniDocument.parse(text)


def encode_embedded(doc: IniDocument, like: str = "") -> str:
    """Re-encode a nested document; padding style follows the original value."""
    encoded = base64.b64encode(doc.to_text().encode("utf-8")).decode("ascii")
    if like and not like.rstrip().endswith("="):
        encoded = encoded.rstrip("=")
    return encoded
