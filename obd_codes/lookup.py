"""Look up OBD-II and manufacturer fault codes.

Matching follows the reference lookup: case-insensitive codes, a typed letter O
in place of zero (`PO420` -> `P0420`), make aliases (`audi`/`skoda` -> VW group,
`vauxhall` -> Vauxhall plus the related GM and PSA lists), and bare 5-digit
VAG / VCDS codes.
"""

from __future__ import annotations

import json
import re
import sqlite3

from obd_codes.db import get_conn
from obd_codes.sources import ATTRIBUTION, describe_url, parse_field_source

ALIASES = {
    "vw": "VW_GROUP",
    "volkswagen": "VW_GROUP",
    "audi": "VW_GROUP",
    "skoda": "VW_GROUP",
    "seat": "VW_GROUP",
    "cupra": "VW_GROUP",
    "ford": "FORD",
    "vauxhall": "VAUXHALL_OPEL",
    "opel": "VAUXHALL_OPEL",
    "gm": "GM",
    "chevrolet": "GM",
    "chevy": "GM",
    "saab": "GM",
    "bmw": "BMW_MINI",
    "mini": "BMW_MINI",
    "mercedes": "MERCEDES",
    "mercedes-benz": "MERCEDES",
    "benz": "MERCEDES",
    "smart": "MERCEDES",
    "toyota": "TOYOTA_LEXUS",
    "lexus": "TOYOTA_LEXUS",
    "honda": "HONDA",
    "acura": "HONDA",
    "nissan": "NISSAN",
    "infiniti": "NISSAN",
    "hyundai": "HYUNDAI_KIA",
    "kia": "HYUNDAI_KIA",
    "genesis": "HYUNDAI_KIA",
    "peugeot": "PEUGEOT_CITROEN",
    "citroen": "PEUGEOT_CITROEN",
    "ds": "PEUGEOT_CITROEN",
    "psa": "PEUGEOT_CITROEN",
    "renault": "RENAULT",
    "dacia": "RENAULT",
    "fiat": "FIAT",
    "alfa": "FIAT",
    "alfaromeo": "FIAT",
    "alfa romeo": "FIAT",
    "abarth": "FIAT",
    "lancia": "FIAT",
    "volvo": "VOLVO",
    "jaguar": "JLR",
    "land rover": "JLR",
    "landrover": "JLR",
    "range rover": "JLR",
    "jlr": "JLR",
    "mazda": "MAZDA",
    "subaru": "SUBARU",
    "mitsubishi": "MITSUBISHI",
    "porsche": "PORSCHE",
    "suzuki": "SUZUKI",
    "chrysler": "CHRYSLER_JEEP_DODGE",
    "jeep": "CHRYSLER_JEEP_DODGE",
    "dodge": "CHRYSLER_JEEP_DODGE",
    "isuzu": "ISUZU",
}

# Makes whose own lists are thin, so a related group's list is shown too.
RELATED = {
    "VAUXHALL_OPEL": ["GM", "PEUGEOT_CITROEN"],
    "JLR": ["FORD"],
    "VOLVO": ["FORD"],
    "MAZDA": ["FORD"],
    "PORSCHE": ["VW_GROUP"],
    "MITSUBISHI": [],
    "RENAULT": ["NISSAN"],
    "NISSAN": ["RENAULT"],
}

MAKE_LABELS = {
    "GENERIC": "All makes (generic SAE / ISO)",
    "VW_GROUP": "VW / Audi / Skoda / SEAT / Cupra",
    "FORD": "Ford",
    "VAUXHALL_OPEL": "Vauxhall / Opel",
    "GM": "GM / Chevrolet / Saab",
    "BMW_MINI": "BMW / Mini",
    "MERCEDES": "Mercedes-Benz / Smart",
    "TOYOTA_LEXUS": "Toyota / Lexus",
    "HONDA": "Honda / Acura",
    "NISSAN": "Nissan / Infiniti",
    "HYUNDAI_KIA": "Hyundai / Kia / Genesis",
    "PEUGEOT_CITROEN": "Peugeot / Citroen / DS",
    "RENAULT": "Renault / Dacia",
    "FIAT": "Fiat / Alfa Romeo / Abarth",
    "VOLVO": "Volvo",
    "JLR": "Jaguar / Land Rover",
    "MAZDA": "Mazda",
    "SUBARU": "Subaru",
    "MITSUBISHI": "Mitsubishi",
    "PORSCHE": "Porsche",
    "SUZUKI": "Suzuki",
    "CHRYSLER_JEEP_DODGE": "Chrysler / Jeep / Dodge",
    "ISUZU": "Isuzu",
    "UNSPECIFIED_MAKE": "Unspecified make",
}

MAKE_OPTIONS = [
    {"id": "VW_GROUP", "label": MAKE_LABELS["VW_GROUP"]},
    {"id": "FORD", "label": MAKE_LABELS["FORD"]},
    {"id": "VAUXHALL_OPEL", "label": MAKE_LABELS["VAUXHALL_OPEL"]},
    {"id": "PEUGEOT_CITROEN", "label": MAKE_LABELS["PEUGEOT_CITROEN"]},
    {"id": "BMW_MINI", "label": MAKE_LABELS["BMW_MINI"]},
    {"id": "MERCEDES", "label": MAKE_LABELS["MERCEDES"]},
    {"id": "TOYOTA_LEXUS", "label": MAKE_LABELS["TOYOTA_LEXUS"]},
    {"id": "HONDA", "label": MAKE_LABELS["HONDA"]},
    {"id": "NISSAN", "label": MAKE_LABELS["NISSAN"]},
    {"id": "HYUNDAI_KIA", "label": MAKE_LABELS["HYUNDAI_KIA"]},
    {"id": "RENAULT", "label": MAKE_LABELS["RENAULT"]},
    {"id": "FIAT", "label": MAKE_LABELS["FIAT"]},
    {"id": "VOLVO", "label": MAKE_LABELS["VOLVO"]},
    {"id": "JLR", "label": MAKE_LABELS["JLR"]},
    {"id": "MAZDA", "label": MAKE_LABELS["MAZDA"]},
    {"id": "GM", "label": MAKE_LABELS["GM"]},
    {"id": "SUBARU", "label": MAKE_LABELS["SUBARU"]},
    {"id": "MITSUBISHI", "label": MAKE_LABELS["MITSUBISHI"]},
    {"id": "PORSCHE", "label": MAKE_LABELS["PORSCHE"]},
    {"id": "SUZUKI", "label": MAKE_LABELS["SUZUKI"]},
    {"id": "CHRYSLER_JEEP_DODGE", "label": MAKE_LABELS["CHRYSLER_JEEP_DODGE"]},
    {"id": "ISUZU", "label": MAKE_LABELS["ISUZU"]},
    {"id": "UNSPECIFIED_MAKE", "label": MAKE_LABELS["UNSPECIFIED_MAKE"]},
]

GUIDANCE_FIELDS = (
    ("meaning", "Meaning"),
    ("causes", "Likely causes"),
    ("symptoms", "Symptoms"),
    ("diagnosis", "Diagnosis steps"),
    ("fixes", "Fixes"),
    ("severity", "Severity"),
    ("drive_advice", "Can I drive?"),
)

_UNVERIFIED = re.compile(r"unverified|no source recorded", re.I)
_TOKEN = re.compile(r"[A-Za-z0-9/]+")


def normalise_code(query: str) -> str | None:
    """Return a canonical code, or None when the query is not a single code."""
    q = query.strip().upper().replace(" ", "").replace("-", "")
    if re.fullmatch(r"\d{5}", q):
        return "VAG" + q
    if re.fullmatch(r"VAG\d{5}", q):
        return q
    if len(q) == 5 and q[0] in "PBCU":
        body = q[1:].replace("O", "0")
        if re.fullmatch(r"[0-9A-F]{4}", body):
            return q[0] + body
    return None


def make_group(make: str | None) -> str | None:
    if not make or not str(make).strip():
        return None
    k = str(make).strip().lower()
    return ALIASES.get(k) or ALIASES.get(k.replace("-", " ")) or str(make).strip().upper().replace(" ", "_")


def make_label(make: str | None) -> str:
    if not make:
        return ""
    return MAKE_LABELS.get(make, make.replace("_", " ").title())


def _json_list(raw: str | None) -> list:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _field(row, key: str) -> dict:
    text = (row[key] or "").strip()
    raw_source = row[key + "_source"] if key + "_source" in row.keys() else ""
    source = parse_field_source(raw_source)
    unverified = bool(_UNVERIFIED.search(text) or _UNVERIFIED.search(raw_source or ""))
    if source is not None:
        source = {**source, "unverified": unverified}
    items = [line.strip() for line in text.split("\n") if line.strip()] if text else []
    return {
        "text": text,
        "items": items,
        "source": source,
        "unverified": unverified,
        "available": bool(text),
    }


def _manufacturer_range(code: str) -> bool:
    return (
        code.startswith("VAG")
        or code[1] == "1"
        or (code[0] == "P" and code[1] == "3" and len(code) > 2 and code[2] in "0123")
        or (code[0] in "BCU" and code[1] == "2")
    )


def serialise_entry(row, relation: str) -> dict:
    notes = row["notes"] or ""
    original_language = "original language" in notes.lower()
    notes_unverified = bool(_UNVERIFIED.search(notes))
    fields = {key: _field(row, key) for key, _label in GUIDANCE_FIELDS}
    # description source has no separate review text; still surface a flag if one is embedded.
    description_source = parse_field_source(row["description_source"])
    description_unverified = bool(_UNVERIFIED.search(row["description"] or "") or _UNVERIFIED.search(row["description_source"] or ""))
    if description_source is not None:
        description_source = {**description_source, "unverified": description_unverified}

    alt = []
    for item in _json_list(row["alt_descriptions"]):
        if not isinstance(item, dict):
            continue
        source_id = item.get("source") or ""
        parsed = parse_field_source(source_id) or {"id": source_id, "name": source_id, "url": "", "licence": ""}
        alt.append(
            {
                "text": item.get("text") or "",
                "source": source_id,
                "source_name": parsed.get("name") or source_id,
                "unverified": bool(_UNVERIFIED.search(item.get("text") or "")),
            }
        )

    urls = [u for u in _json_list(row["source_urls"]) if isinstance(u, str) and u]
    sources = []
    seen: set[str] = set()
    for url in urls:
        described = describe_url(url)
        key = described.get("url") or described.get("name") or ""
        if not key or key in seen:
            continue
        seen.add(key)
        sources.append(described)
    if description_source and description_source.get("url") and description_source["url"] not in seen:
        sources.append(description_source)
    for field in fields.values():
        src = field.get("source")
        if src and src.get("url") and src["url"] not in seen:
            seen.add(src["url"])
            sources.append(src)

    unverified_fields = [key for key, field in fields.items() if field["unverified"]]
    if description_unverified:
        unverified_fields.insert(0, "description")

    return {
        "code": row["code"],
        "letter": row["letter"],
        "system": row["system"],
        "subsystem": row["subsystem"],
        "scope": row["scope"],
        "make": row["make"],
        "make_label": make_label(row["make"]),
        "make_detail": row["make_detail"],
        "code_format": row["code_format"],
        "relation": relation,
        "description": row["description"],
        "description_source": description_source,
        "description_unverified": description_unverified,
        "alt_descriptions": alt,
        "warning_lamp": row["warning_lamp"],
        "warning_lamp_source": parse_field_source(row["warning_lamp_source"]),
        "notes": notes,
        "original_language": original_language,
        "notes_unverified": notes_unverified,
        "guidance_available": any(field["available"] for field in fields.values()),
        "unverified_fields": unverified_fields,
        "fields": fields,
        "source_urls": urls,
        "sources": sources,
    }


def _relation(make: str, selected: str | None) -> str:
    if make == "GENERIC":
        return "generic"
    if selected and make == selected:
        return "selected"
    if selected and make in RELATED.get(selected, []):
        return "related"
    return "listed"


def lookup_code(code: str, make: str | None) -> dict:
    con = get_conn()
    rows = con.execute(
        "SELECT * FROM codes WHERE code=? ORDER BY scope='manufacturer', make",
        (code,),
    ).fetchall()
    mg = make_group(make)
    if mg:
        want = [mg] + RELATED.get(mg, [])
        selected_rows = [r for r in rows if r["make"] == "GENERIC"]
        selected_rows += [r for group in want for r in rows if r["make"] == group]
        others = sorted({r["make"] for r in rows if r not in selected_rows})
    else:
        selected_rows, others = list(rows), []

    entries = [serialise_entry(r, _relation(r["make"], mg)) for r in selected_rows]
    mfr_range = _manufacturer_range(code)
    warning = None
    if (
        mfr_range
        and not mg
        and len([r for r in rows if r["scope"] == "manufacturer"]) > 1
    ):
        warning = (
            f"{code} is a manufacturer-specific code; its meaning differs by make. "
            "Choose a vehicle make to narrow it down."
        )
    message = None
    hint = None
    make_missing = None
    if not rows:
        message = f"No entry for {code} in the database."
        if code[1] in "123" or code.startswith("VAG"):
            hint = "It is a manufacturer-specific code; it may not be in the public lists collected so far."
    elif mg and mfr_range and not any(r["make"] == mg for r in selected_rows):
        make_missing = f"No {make_label(mg)} entry for {code} in the collected lists."

    return {
        "query": code,
        "mode": "code",
        "normalised_code": code,
        "make_group": mg,
        "make_label": make_label(mg) if mg else None,
        "warning": warning,
        "message": message,
        "hint": hint,
        "make_missing": make_missing,
        "also_defined_for": [{"id": m, "label": make_label(m)} for m in others],
        "entries": entries,
        "matches": [],
        "attribution": ATTRIBUTION,
    }


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def _term_in_text(text: str, term: str, prefix: bool) -> bool:
    """True when `term` matches a word in `text`.

    The last search term is a prefix, matching the reference lookup. A word and
    a term of at least 5 letters also match when one starts with the other, so
    "catalytic" still finds a description that says "catalyst".
    """
    needle = term.lower()
    if not needle:
        return False
    for word in _words(text):
        if prefix and word.startswith(needle):
            return True
        if word == needle:
            return True
        # "catalyst" and "catalytic" share a stem but neither is a prefix of the other.
        if len(needle) >= 5 and len(word) >= 5 and _shared_prefix(word, needle) >= 6:
            return True
    return False


def _shared_prefix(left: str, right: str) -> int:
    count = 0
    for a, b in zip(left, right):
        if a != b:
            break
        count += 1
    return count


def _keyword_rank(row, terms: list[str]) -> tuple:
    """Put the standard code ahead of a short manufacturer row that repeats the words.

    Full-text rank alone favours a 4-word VAG line over P0300, because the generic
    row also carries causes and diagnosis. Title matches (description, then
    meaning) and the generic code come first; bm25 is only the tie-break inside
    the candidate query.
    """
    description = row["description"] or ""
    meaning = row["meaning"] or ""
    desc_hits = 0
    title_hits = 0
    for index, term in enumerate(terms):
        prefix = index == len(terms) - 1
        in_desc = _term_in_text(description, term, prefix)
        in_meaning = _term_in_text(meaning, term, prefix)
        desc_hits += int(in_desc)
        title_hits += int(in_desc or in_meaning)
    guidance = bool(row["meaning"] or row["causes"] or row["diagnosis"] or row["fixes"])
    return (
        -title_hits,
        0 if row["scope"] == "generic" else 1,
        -desc_hits,
        0 if guidance else 1,
        row["code"],
        row["make"],
    )


def lookup_keyword(query: str, make: str | None, limit: int) -> dict:
    terms = [t for t in _TOKEN.findall(query) if t]
    mg = make_group(make)
    base = {
        "query": query,
        "mode": "keyword",
        "normalised_code": None,
        "make_group": mg,
        "make_label": make_label(mg) if mg else None,
        "warning": None,
        "message": None,
        "hint": None,
        "make_missing": None,
        "also_defined_for": [],
        "entries": [],
        "matches": [],
        "attribution": ATTRIBUTION,
    }
    if not terms:
        base["message"] = "No matches."
        return base

    # Same MATCH expression as the reference lookup: exact tokens, prefix on the last.
    fts = " ".join(f'"{t}"' for t in terms[:-1]) + f' "{terms[-1]}"*'
    con = get_conn()
    pooled: dict[tuple[str, str], sqlite3.Row] = {}

    def remember(rows) -> None:
        for row in rows:
            pooled[(row["code"], row["make"])] = row

    fts_sql = "SELECT c.* FROM codes_fts f JOIN codes c ON c.id=f.rowid WHERE codes_fts MATCH ?"
    fts_args: list = [fts]
    if mg:
        fts_sql += " AND c.make IN (?, 'GENERIC')"
        fts_args.append(mg)
    fts_sql += " ORDER BY bm25(codes_fts, 10.0, 8.0, 3.0, 2.0, 1.0, 0.0, 0.0), c.scope, c.code LIMIT ?"
    fts_args.append(max(limit, 80))
    try:
        remember(con.execute(fts_sql, fts_args).fetchall())
    except sqlite3.OperationalError:
        base["message"] = "No matches."
        return base

    # Title matches are collected separately because a long generic entry ranks
    # poorly on bm25 and would otherwise fall out of the top of the FTS list.
    title_sql = "SELECT * FROM codes WHERE 1=1"
    title_args: list = []
    if mg:
        title_sql += " AND make IN (?, 'GENERIC')"
        title_args.append(mg)
    for term in terms:
        pattern = "%" + term.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        title_sql += " AND (lower(description) LIKE ? ESCAPE '\\' OR lower(meaning) LIKE ? ESCAPE '\\')"
        title_args.extend((pattern, pattern))
    title_sql += " ORDER BY scope, code LIMIT 400"
    remember(con.execute(title_sql, title_args).fetchall())

    if not pooled:
        base["message"] = "No matches."
        return base
    ranked = sorted(pooled.values(), key=lambda row: _keyword_rank(row, terms))
    base["matches"] = [
        {
            "code": r["code"],
            "make": r["make"],
            "make_label": make_label(r["make"]),
            "scope": r["scope"],
            "description": r["description"],
            "has_guidance": bool(r["causes"] or r["diagnosis"] or r["fixes"] or r["meaning"]),
            "original_language": "original language" in (r["notes"] or "").lower(),
            "warning_lamp": r["warning_lamp"],
        }
        for r in ranked[:limit]
    ]
    return base


_EMBEDDED_CODE = re.compile(r"\b(?:[Vv][Aa][Gg]\s*\d{5}|[PpBbCcUu][0-9A-Fa-fOo]{4})\b")
_BARE_VAG = re.compile(r"\b\d{5}\b")


def extract_codes(text: str, make: str | None = None) -> list[str]:
    """Pull fault codes out of a free-text symptom description.

    A query that is only a code, including a bare 5-digit VAG code, is handled
    the same way as the reference lookup. Inside a longer sentence, bare 5-digit
    numbers are treated as VAG codes only when the vehicle make is in that group,
    so a mileage figure on another make is left alone.
    """
    raw = text or ""
    whole = normalise_code(raw)
    if whole:
        return [whole]
    found: list[str] = []
    for match in _EMBEDDED_CODE.finditer(raw):
        code = normalise_code(match.group(0))
        if code and code not in found:
            found.append(code)
    if make_group(make) == "VW_GROUP":
        for match in _BARE_VAG.finditer(raw):
            code = normalise_code(match.group(0))
            if code and code not in found:
                found.append(code)
    return found[:5]


def search(query: str, make: str | None = None, limit: int = 30) -> dict:
    text = (query or "").strip()
    if not text:
        return {
            "query": "",
            "mode": "empty",
            "normalised_code": None,
            "make_group": make_group(make),
            "make_label": make_label(make_group(make)) if make else None,
            "warning": None,
            "message": "Enter a code or a keyword.",
            "hint": None,
            "make_missing": None,
            "also_defined_for": [],
            "entries": [],
            "matches": [],
            "attribution": ATTRIBUTION,
        }
    code = normalise_code(text)
    if code:
        result = lookup_code(code, make)
        result["query"] = text
        return result
    return lookup_keyword(text, make, limit)


def makes_payload() -> dict:
    """Dropdown data. Each option's id is accepted by `make`, and so are aliases."""
    options = []
    for option in MAKE_OPTIONS:
        aliases = sorted(alias for alias, group in ALIASES.items() if group == option["id"])
        options.append({**option, "aliases": aliases})
    return {"makes": options, "attribution": ATTRIBUTION}

