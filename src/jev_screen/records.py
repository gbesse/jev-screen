"""Purpose: Stdlib parsers (RIS, PubMed MEDLINE .nbib, CSV) and exporters (RIS, CSV, JSONL) for bibliographic records."""

from __future__ import annotations

import csv
import io
import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

# RIS: two-character tag, two spaces, dash, space, value. `ER  - ` closes a record.
_RIS_TAG = re.compile(r"^([A-Z][A-Z0-9])  - ?(.*)$")
# MEDLINE: tag padded to four characters, dash, space. Continuation lines start with six spaces.
_NBIB_TAG = re.compile(r"^([A-Z]{2,4}) *- (.*)$")
_YEAR = re.compile(r"(\d{4})")
_WS = re.compile(r"\s+")


@dataclass
class Record:
    """One bibliographic record. Only `title` and `abstract` are ever sent to Jev; the rest is for exports."""

    id: str
    title: str = ""
    abstract: str = ""
    authors: list[str] = field(default_factory=list)
    year: str = ""
    doi: str = ""

    def has_abstract(self) -> bool:
        return bool(self.abstract.strip())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clean(text: str) -> str:
    return _WS.sub(" ", text).strip()


def _fallback_id(prefix: str, doi: str, index: int) -> str:
    return doi if doi else f"{prefix}-{index}"


def parse_ris(text: str) -> list[Record]:
    """Parse RIS. Lines without a tag continue the previous value (multi-line abstracts are common in exports)."""
    records: list[Record] = []
    fields: dict[str, list[str]] = {}
    last_tag: str | None = None
    in_record = False

    def flush() -> None:
        nonlocal fields, last_tag, in_record
        if in_record:
            title = fields.get("TI") or fields.get("T1") or [""]
            abstract = fields.get("AB") or fields.get("N2") or [""]
            year_src = (fields.get("PY") or fields.get("Y1") or [""])[0]
            year = _YEAR.search(year_src)
            doi = _clean((fields.get("DO") or [""])[0])
            rid = _clean((fields.get("ID") or [""])[0]) or _fallback_id("ris", doi, len(records) + 1)
            records.append(
                Record(
                    id=rid,
                    title=_clean(title[0]),
                    abstract=_clean(abstract[0]),
                    authors=[_clean(a) for a in (fields.get("AU") or fields.get("A1") or []) if _clean(a)],
                    year=year.group(1) if year else "",
                    doi=doi,
                )
            )
        fields, last_tag, in_record = {}, None, False

    for raw in text.splitlines():
        line = raw.rstrip("\r\n").lstrip("﻿")
        match = _RIS_TAG.match(line)
        if match:
            tag, value = match.group(1), match.group(2)
            if tag == "TY":
                flush()
                in_record = True
            elif tag == "ER":
                flush()
                continue
            if not in_record:
                in_record = True  # tolerate exports that omit TY
            fields.setdefault(tag, []).append(value)
            last_tag = tag
        elif in_record and last_tag and line.strip():
            fields[last_tag][-1] += " " + line.strip()
    flush()
    return records


def parse_nbib(text: str) -> list[Record]:
    """Parse PubMed MEDLINE format; records are separated by blank lines and AB values wrap on indented lines."""
    records: list[Record] = []
    fields: dict[str, list[str]] = {}
    last_tag: str | None = None

    def flush() -> None:
        nonlocal fields, last_tag
        if fields:
            doi = ""
            for candidate in fields.get("LID", []) + fields.get("AID", []):
                if candidate.endswith("[doi]"):
                    doi = _clean(candidate[: -len("[doi]")])
                    break
            year = _YEAR.search((fields.get("DP") or [""])[0])
            pmid = _clean((fields.get("PMID") or [""])[0])
            records.append(
                Record(
                    id=pmid or _fallback_id("nbib", doi, len(records) + 1),
                    title=_clean((fields.get("TI") or [""])[0]),
                    abstract=_clean((fields.get("AB") or [""])[0]),
                    authors=[_clean(a) for a in fields.get("AU", []) if _clean(a)],
                    year=year.group(1) if year else "",
                    doi=doi,
                )
            )
        fields, last_tag = {}, None

    for raw in text.splitlines():
        line = raw.rstrip("\r\n").lstrip("﻿")
        if not line.strip():
            flush()
            continue
        match = _NBIB_TAG.match(line)
        if match:
            tag, value = match.group(1), match.group(2)
            if tag == "PMID" and fields:
                flush()  # some exports omit the blank line between records
            fields.setdefault(tag, []).append(value)
            last_tag = tag
        elif last_tag and line.startswith("      "):
            fields[last_tag][-1] += " " + line.strip()
    flush()
    return records


def parse_csv(text: str) -> list[Record]:
    """Parse `id,title,abstract,year,doi[,authors]`; header names are case-insensitive, missing columns are empty."""
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return []
    names = {name.strip().lower(): name for name in reader.fieldnames if name}
    if "title" not in names and "abstract" not in names:
        raise ValueError("CSV needs at least a 'title' or 'abstract' column")

    def col(row: dict[str, str], key: str) -> str:
        source = names.get(key)
        return _clean(row.get(source) or "") if source else ""

    records: list[Record] = []
    for index, row in enumerate(reader, start=1):
        doi = col(row, "doi")
        authors = [a.strip() for a in col(row, "authors").split(";") if a.strip()]
        records.append(
            Record(
                id=col(row, "id") or _fallback_id("csv", doi, index),
                title=col(row, "title"),
                abstract=col(row, "abstract"),
                authors=authors,
                year=col(row, "year"),
                doi=doi,
            )
        )
    return records


def detect_format(path: str | os.PathLike[str], text: str) -> str:
    """Extension first, then a content sniff for `.txt` exports, which both PubMed and reference managers produce."""
    suffix = Path(path).suffix.lower()
    if suffix == ".ris":
        return "ris"
    if suffix == ".nbib":
        return "nbib"
    if suffix == ".csv":
        return "csv"
    head = text.lstrip("﻿")[:2000]
    if re.search(r"^PMID- ", head, re.M):
        return "nbib"
    if re.search(r"^TY  - ", head, re.M):
        return "ris"
    raise ValueError(f"cannot detect record format of {path}; use .ris, .nbib or .csv")


def load_records(path: str | os.PathLike[str], fmt: str | None = None) -> list[Record]:
    text = Path(path).read_text(encoding="utf-8-sig")
    fmt = fmt or detect_format(path, text)
    if fmt == "ris":
        return parse_ris(text)
    if fmt == "nbib":
        return parse_nbib(text)
    if fmt == "csv":
        return parse_csv(text)
    raise ValueError(f"unknown record format {fmt!r}")


def check_unique_ids(records: Iterable[Record]) -> None:
    """Resume and agreement join on id; a duplicate would silently merge two studies."""
    seen: set[str] = set()
    for record in records:
        if record.id in seen:
            raise ValueError(f"duplicate record id {record.id!r}")
        seen.add(record.id)


def to_ris(records: Iterable[Record], notes: dict[str, str] | None = None) -> str:
    """Serialise records as RIS. `notes` (id -> text) is written as N1 so decisions travel with the export."""
    lines: list[str] = []
    for record in records:
        lines.append("TY  - JOUR")
        lines.append(f"ID  - {record.id}")
        if record.title:
            lines.append(f"TI  - {_clean(record.title)}")
        for author in record.authors:
            lines.append(f"AU  - {author}")
        if record.year:
            lines.append(f"PY  - {record.year}")
        if record.abstract:
            lines.append(f"AB  - {_clean(record.abstract)}")
        if record.doi:
            lines.append(f"DO  - {record.doi}")
        if notes and record.id in notes:
            lines.append(f"N1  - {notes[record.id]}")
        lines.append("ER  - ")
        lines.append("")
    return "\n".join(lines)


def write_ris(records: Iterable[Record], path: str | os.PathLike[str], notes: dict[str, str] | None = None) -> None:
    Path(path).write_text(to_ris(records, notes), encoding="utf-8")


def write_csv(rows: Iterable[dict[str, Any]], path: str | os.PathLike[str], columns: list[str]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_jsonl(rows: Iterable[dict[str, Any]], path: str | os.PathLike[str]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
