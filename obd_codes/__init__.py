"""Server-side OBD-II fault-code lookup.

The dataset is about 29 MB of text (84,694 rows). It stays in a local SQLite
file and is queried through the API; it is never sent to the client as a blob.
"""

from obd_codes.db import ensure_db, get_conn
from obd_codes.lookup import make_group, normalise_code, search

__all__ = ["ensure_db", "get_conn", "make_group", "normalise_code", "search"]
