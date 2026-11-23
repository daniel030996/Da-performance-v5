"""Named sources for the fault-code dataset.

Text was copied from these public sources. Nothing here was rewritten or guessed.
See the dataset README for how a primary value was chosen when sources disagree.
"""

from __future__ import annotations

SOURCES: dict[str, dict[str, str]] = {
    "ocl_csv": {
        "name": "OBD Codes List",
        "url": "https://obdcodeslist.com/code-data.html",
        "licence": "Free with attribution",
        "used_for": "Generic descriptions, category and warning lamp",
    },
    "wal33d": {
        "name": "Wal33D/dtc-database",
        "url": "https://github.com/Wal33D/dtc-database",
        "licence": "MIT",
        "used_for": "Generic cross-check and make lists",
    },
    "autodiag": {
        "name": "autodiag2/database",
        "url": "https://github.com/autodiag2/database",
        "licence": "ODbL-1.0 / DbCL-1.0",
        "used_for": "Generic cross-check, make lists and PSA ECU-specific codes",
    },
    "pyobd": {
        "name": "python-OBD codes.py",
        "url": "https://github.com/brendan-w/python-OBD/blob/master/obd/codes.py",
        "licence": "GPL",
        "used_for": "Generic cross-check (older wording)",
    },
    "mytrile": {
        "name": "mytrile/obd-trouble-codes",
        "url": "https://github.com/mytrile/obd-trouble-codes",
        "licence": "MIT",
        "used_for": "Fallback only (the list has some mis-keyed rows)",
    },
    "auto9": {
        "name": "Automotive-9/dtc-codes",
        "url": "https://github.com/Automotive-9/dtc-codes",
        "licence": "Public GitHub repo, no licence stated",
        "used_for": "Make lists, including VAG 5-digit codes",
    },
    "opendtc": {
        "name": "OpenDTC brand lists",
        "url": "https://opendtc.net/brands",
        "licence": "Public site",
        "used_for": "Manufacturer code lists",
    },
    "opendtc_pg": {
        "name": "OpenDTC",
        "url": "https://opendtc.net/",
        "licence": "Public site",
        "used_for": "Plain-English meaning, severity and can-I-drive for common codes",
    },
    "ocl_pg": {
        "name": "OBD Codes List",
        "url": "https://obdcodeslist.com/",
        "licence": "Public pages",
        "used_for": "Causes, diagnosis steps and fixes",
    },
    "carparts": {
        "name": "CarParts.com",
        "url": "https://www.carparts.com/blog/",
        "licence": "Public articles",
        "used_for": "Causes, symptoms, diagnosis, fixes and meaning for common codes",
    },
    "opendtc_tpl": {
        "name": "OpenDTC category template",
        "url": "https://opendtc.net/",
        "licence": "Public site",
        "used_for": "Not used as a primary answer (reused category text)",
    },
}

# Required notice for the obdcodeslist.com CSV, plus the other licences in the dataset.
ATTRIBUTION = {
    "required_notice": "Code data from OBD Codes List, https://obdcodeslist.com/code-data.html",
    "odbl_notice": (
        "Manufacturer and cross-check rows include autodiag2/database, "
        "which is published under the Open Database License (ODbL-1.0): "
        "https://github.com/autodiag2/database"
    ),
    "mit_notice": (
        "Also includes Wal33D/dtc-database (MIT) and mytrile/obd-trouble-codes (MIT)."
    ),
    "sources": [
        {
            "id": sid,
            "name": meta["name"],
            "url": meta["url"],
            "licence": meta["licence"],
            "used_for": meta["used_for"],
        }
        for sid, meta in SOURCES.items()
        if sid != "opendtc_tpl"
    ],
}


def source_meta(source_id: str | None) -> dict[str, str]:
    if not source_id:
        return {"id": "", "name": "", "url": "", "licence": ""}
    meta = SOURCES.get(source_id, {})
    return {
        "id": source_id,
        "name": meta.get("name", source_id),
        "url": meta.get("url", ""),
        "licence": meta.get("licence", ""),
    }


def parse_field_source(raw: str | None) -> dict | None:
    """Turn 'ocl_pg: https://…' into a name, url and licence."""
    if not raw or not str(raw).strip():
        return None
    sid, _, url = str(raw).partition(": ")
    sid = sid.strip()
    meta = source_meta(sid)
    if url.strip():
        meta["url"] = url.strip()
    return meta


def describe_url(url: str) -> dict[str, str]:
    """Best-effort label for a URL stored on the row."""
    u = url or ""
    rules = (
        ("obdcodeslist.com/code-data", "ocl_csv"),
        ("obdcodeslist.com", "ocl_pg"),
        ("opendtc.net/brands", "opendtc"),
        ("opendtc.net", "opendtc_pg"),
        ("carparts.com", "carparts"),
        ("Wal33D/dtc-database", "wal33d"),
        ("autodiag2/database", "autodiag"),
        ("python-OBD", "pyobd"),
        ("mytrile/obd-trouble-codes", "mytrile"),
        ("Automotive-9/dtc-codes", "auto9"),
    )
    for needle, sid in rules:
        if needle in u:
            meta = source_meta(sid)
            meta["url"] = u
            return meta
    return {"id": "", "name": u, "url": u, "licence": ""}
