"""Client Indexing IDs assigned at the Gmail reception boundary."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone


def assign_client_index_id(sender: str, filename: str, payload: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    digest = hashlib.sha256(f"{sender}|{filename}|{payload[:2048]}".encode("utf-8")).hexdigest()[:10]
    return f"CID-{stamp}-{digest.upper()}"


def assign_event_id(client_index_id: str, filename: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9]+", "-", filename.rsplit(".", 1)[0])[:24].strip("-").upper()
    suffix = hashlib.sha1(f"{client_index_id}|{filename}".encode("utf-8")).hexdigest()[:8].upper()
    return f"EVT-{stem}-{suffix}"
