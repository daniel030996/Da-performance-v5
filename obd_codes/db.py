"""Build and open the fault-code SQLite database.

`data/codes.csv.gz` is the copy that ships with the app (about 2 MB). The
first startup unpacks it into SQLite and builds a full-text index. Later
startups reuse that file. The uncompressed CSV is about 29 MB and is not
served to the browser.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import os
import sqlite3
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "data" / "codes.csv.gz"

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

COLUMNS = [
    "code",
    "letter",
    "system",
    "subsystem",
    "scope",
    "make",
    "make_detail",
    "code_format",
    "description",
    "description_source",
    "alt_descriptions",
    "meaning",
    "meaning_source",
    "causes",
    "causes_source",
    "symptoms",
    "symptoms_source",
    "diagnosis",
    "diagnosis_source",
    "fixes",
    "fixes_source",
    "severity",
    "severity_source",
    "drive_advice",
    "drive_advice_source",
    "warning_lamp",
    "warning_lamp_source",
    "notes",
    "source_urls",
]


def csv_path() -> Path:
    override = os.environ.get("OBD_CSV_PATH")
    return Path(override) if override else CSV_PATH


def database_path() -> Path:
    override = os.environ.get("OBD_DB_PATH")
    if override:
        path = Path(override)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    data_dir = ROOT / "data"
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        probe = data_dir / ".write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return data_dir / "codes.db"
    except OSError:
        return Path(tempfile.gettempdir()) / "da-performance-codes.db"


def _fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _existing_fingerprint(path: Path) -> str | None:
    if not path.exists() or path.stat().st_size == 0:
        return None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        row = con.execute("SELECT value FROM meta WHERE key='csv_sha256'").fetchone()
    except sqlite3.Error:
        return None
    finally:
        con.close()
    return row[0] if row else None


def build_database(csv_file: Path, db_file: Path) -> int:
    """Load the gzipped CSV into a fresh SQLite file. Returns the row count."""
    if not csv_file.exists():
        raise FileNotFoundError(f"Fault-code CSV not found at {csv_file}")

    db_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = db_file.with_suffix(".db.building")
    if tmp.exists():
        tmp.unlink()

    started = time.perf_counter()
    con = sqlite3.connect(tmp)
    try:
        con.execute("PRAGMA journal_mode=OFF")
        con.execute("PRAGMA synchronous=OFF")
        con.execute("PRAGMA temp_store=MEMORY")
        con.execute("PRAGMA cache_size=-65536")
        cols = ", ".join(COLUMNS)
        placeholders = ", ".join("?" for _ in COLUMNS)
        con.execute(
            f"""
            CREATE TABLE codes (
                id INTEGER PRIMARY KEY,
                {", ".join(c + " TEXT NOT NULL DEFAULT ''" for c in COLUMNS)}
            )
            """
        )
        insert = f"INSERT INTO codes ({cols}) VALUES ({placeholders})"
        batch: list[tuple] = []
        count = 0
        with gzip.open(csv_file, "rt", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            missing = [c for c in COLUMNS if c not in (reader.fieldnames or [])]
            if missing:
                raise ValueError(f"Fault-code CSV is missing columns: {', '.join(missing)}")
            for row in reader:
                batch.append(tuple((row.get(c) or "").strip() for c in COLUMNS))
                if len(batch) >= 2000:
                    con.executemany(insert, batch)
                    count += len(batch)
                    batch.clear()
            if batch:
                con.executemany(insert, batch)
                count += len(batch)
        con.execute("CREATE UNIQUE INDEX idx_codes_code_make ON codes(code, make)")
        con.execute("CREATE INDEX idx_codes_code ON codes(code)")
        con.execute("CREATE INDEX idx_codes_make ON codes(make)")
        # External-content FTS5. Column order matches the bm25 weights in lookup.py
        # (code, description, meaning, causes, symptoms, then diagnosis and fixes at 0).
        con.execute(
            """
            CREATE VIRTUAL TABLE codes_fts USING fts5(
                code, description, meaning, causes, symptoms, diagnosis, fixes,
                content='codes', content_rowid='id',
                tokenize='unicode61'
            )
            """
        )
        con.execute("INSERT INTO codes_fts(codes_fts) VALUES('rebuild')")
        con.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        con.executemany(
            "INSERT INTO meta (key, value) VALUES (?, ?)",
            [
                ("csv_sha256", _fingerprint(csv_file)),
                ("row_count", str(count)),
                ("built_at", str(int(time.time()))),
            ],
        )
        con.commit()
    except Exception:
        con.close()
        if tmp.exists():
            tmp.unlink()
        raise
    con.close()
    tmp.replace(db_file)
    elapsed = time.perf_counter() - started
    print(f"Built fault-code database: {count} rows in {elapsed:.1f}s at {db_file}", flush=True)
    return count


def ensure_db() -> sqlite3.Connection:
    """Open the database, building it from the CSV the first time."""
    global _conn
    with _lock:
        if _conn is not None:
            return _conn
        source = csv_path()
        dest = database_path()
        fingerprint = _fingerprint(source)
        if _existing_fingerprint(dest) != fingerprint:
            build_database(source, dest)
        conn = sqlite3.connect(dest, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        _conn = conn
        return conn


def get_conn() -> sqlite3.Connection:
    return ensure_db()


def close_db() -> None:
    """Drop the cached connection. Used by tests that point at another file."""
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None
