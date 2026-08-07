"""
Databricks Genie Conversation API (server-side). Same flow as Supply Chain Control Tower:
start-conversation / create-message / get-message. Auth is resolved via the SDK's unified
auth (CLI profile, OAuth U2M, or the app service principal when deployed) rather than a
raw DATABRICKS_TOKEN read from an env var this account doesn't use.
"""
from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import urlparse

import httpx
from databricks.sdk import WorkspaceClient


def _client() -> WorkspaceClient:
    return WorkspaceClient()


def _base_url(client: WorkspaceClient) -> str:
    """Netloc only, e.g. https://fevm-....cloud.databricks.com"""
    host = (client.config.host or "").strip()
    if not host:
        return ""
    if "://" not in host:
        host = f"https://{host}"
    netloc = urlparse(host).netloc
    return f"https://{netloc}" if netloc else ""


def _parse_space_id_from_url(url: str) -> str | None:
    if not url:
        return None
    m = re.search(r"/genie/(?:spaces|rooms)/([a-fA-F0-9]+)", url)
    return m.group(1) if m else None


def get_genie_space_id() -> str:
    explicit = (os.getenv("DATABRICKS_GENIE_SPACE_ID") or os.getenv("GENIE_SPACE_ID") or "").strip()
    if explicit:
        return explicit
    for key in ("DATABRICKS_GENIE_SPACE_URL", "GENIE_SPACE_URL"):
        parsed = _parse_space_id_from_url(os.getenv(key) or "")
        if parsed:
            return parsed
    return ""


def is_configured() -> bool:
    """Whether the app can resolve Databricks auth plus a target space — i.e. a
    resolvable host/profile and a space id, not any particular env var."""
    if not get_genie_space_id():
        return False
    try:
        client = _client()
        client.config.authenticate()
        return bool(_base_url(client))
    except Exception:
        return False


def start_conversation(space_id: str, content: str) -> dict[str, Any]:
    client = _client()
    url = f"{_base_url(client)}/api/2.0/genie/spaces/{space_id}/start-conversation"
    with httpx.Client(timeout=60.0) as http_client:
        r = http_client.post(
            url,
            json={"content": content},
            headers=client.config.authenticate(),
        )
        r.raise_for_status()
        return r.json()


def create_message(space_id: str, conversation_id: str, content: str) -> dict[str, Any]:
    client = _client()
    url = (
        f"{_base_url(client)}/api/2.0/genie/spaces/{space_id}/conversations/"
        f"{conversation_id}/messages"
    )
    with httpx.Client(timeout=60.0) as http_client:
        r = http_client.post(
            url,
            json={"content": content},
            headers=client.config.authenticate(),
        )
        r.raise_for_status()
        return r.json()


def get_message(space_id: str, conversation_id: str, message_id: str) -> dict[str, Any]:
    client = _client()
    url = (
        f"{_base_url(client)}/api/2.0/genie/spaces/{space_id}/conversations/"
        f"{conversation_id}/messages/{message_id}"
    )
    with httpx.Client(timeout=30.0) as http_client:
        r = http_client.get(url, headers=client.config.authenticate())
        r.raise_for_status()
        return r.json()
