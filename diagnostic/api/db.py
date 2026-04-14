"""Database layer — Supabase REST API via httpx.

Uses the PostgREST API (already running on every Supabase project).
No direct PostgreSQL connection needed — avoids pooler/SSL issues.
Requires: SUPABASE_URL and SUPABASE_SERVICE_KEY env vars.
"""

from __future__ import annotations

import os
import json
from datetime import datetime, timezone
from typing import Optional

import httpx

# ── Config ──
_url: Optional[str] = None
_key: Optional[str] = None
_client: Optional[httpx.AsyncClient] = None


async def init_pool():
    """Initialize the HTTP client for Supabase REST API."""
    global _url, _key, _client

    _url = os.environ.get("SUPABASE_URL")
    _key = os.environ.get("SUPABASE_SERVICE_KEY")

    if not _url or not _key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set. "
            "Find them in Supabase → Settings → API"
        )

    _client = httpx.AsyncClient(
        base_url=f"{_url.rstrip('/')}/rest/v1",
        headers={
            "apikey": _key,
            "Authorization": f"Bearer {_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        },
        timeout=30,
    )


async def close_pool():
    """Close the HTTP client."""
    global _client
    if _client:
        await _client.aclose()
        _client = None


def _get_client() -> httpx.AsyncClient:
    if _client is None:
        raise RuntimeError("DB not initialized. Call init_pool() first.")
    return _client


def _check(resp: httpx.Response, context: str = ""):
    """Raise on Supabase API errors."""
    if resp.status_code >= 400:
        detail = resp.text[:300]
        raise RuntimeError(f"Supabase error ({context}): {resp.status_code} — {detail}")


# ══════════════════════════════════════════════════════════
# MESSAGES
# ══════════════════════════════════════════════════════════

async def insert_message(name: str, email: str, message: str) -> int:
    """Insert a contact form message. Returns the new message ID."""
    c = _get_client()
    now = datetime.now(timezone.utc).isoformat()
    resp = await c.post("/messages", json={
        "name": name,
        "email": email,
        "message": message,
        "created_at": now,
    })
    _check(resp, "insert_message")
    return resp.json()[0]["id"]


async def list_messages() -> list[dict]:
    """List all messages, newest first."""
    c = _get_client()
    resp = await c.get("/messages", params={"order": "created_at.desc"})
    _check(resp, "list_messages")
    return resp.json()


async def mark_message_read(msg_id: int) -> bool:
    """Mark a message as read. Returns True if found."""
    c = _get_client()
    resp = await c.patch(
        f"/messages?id=eq.{msg_id}",
        json={"read": True},
    )
    _check(resp, "mark_message_read")
    return len(resp.json()) > 0


async def get_message(msg_id: int) -> Optional[dict]:
    """Get a single message by ID."""
    c = _get_client()
    resp = await c.get("/messages", params={
        "id": f"eq.{msg_id}",
        "limit": "1",
    })
    _check(resp, "get_message")
    rows = resp.json()
    return rows[0] if rows else None


async def mark_message_replied(msg_id: int, reply_text: str) -> bool:
    """Mark a message as replied with the reply text."""
    c = _get_client()
    now = datetime.now(timezone.utc).isoformat()
    resp = await c.patch(
        f"/messages?id=eq.{msg_id}",
        json={"replied": True, "reply_text": reply_text, "replied_at": now, "read": True},
    )
    _check(resp, "mark_message_replied")
    return len(resp.json()) > 0


# ══════════════════════════════════════════════════════════
# DIAGNOSTICS
# ══════════════════════════════════════════════════════════

async def insert_diagnostic(
    url: str,
    health_score: Optional[int],
    report: Optional[dict],
    crawl_summary: str,
    email: Optional[str] = None,
) -> int:
    """Save a diagnostic run. Returns the new diagnostic ID."""
    c = _get_client()
    now = datetime.now(timezone.utc).isoformat()
    resp = await c.post("/diagnostics", json={
        "url": url,
        "email": email,
        "health_score": health_score,
        "report_json": report,
        "crawl_summary": (crawl_summary[:500] if crawl_summary else ""),
        "created_at": now,
    })
    _check(resp, "insert_diagnostic")
    return resp.json()[0]["id"]


async def list_diagnostics() -> list[dict]:
    """List diagnostics (summary only, no full report)."""
    c = _get_client()
    resp = await c.get("/diagnostics", params={
        "select": "id,url,email,health_score,crawl_summary,created_at",
        "order": "created_at.desc",
    })
    _check(resp, "list_diagnostics")
    return resp.json()


async def get_diagnostic(diag_id: int) -> Optional[dict]:
    """Get a full diagnostic by ID."""
    c = _get_client()
    resp = await c.get("/diagnostics", params={
        "id": f"eq.{diag_id}",
        "limit": "1",
    })
    _check(resp, "get_diagnostic")
    rows = resp.json()
    return rows[0] if rows else None


# ══════════════════════════════════════════════════════════
# STATS
# ══════════════════════════════════════════════════════════

async def get_stats() -> dict:
    """Return overview stats for the dashboard."""
    c = _get_client()

    # Supabase supports HEAD with Prefer: count=exact for counting
    headers_count = {"Prefer": "count=exact", "Range-Unit": "items", "Range": "0-0"}

    resp_total = await c.get("/messages?select=id", headers=headers_count)
    total_leads = int(resp_total.headers.get("content-range", "*/0").split("/")[-1])

    resp_diag = await c.get("/diagnostics?select=id", headers=headers_count)
    total_diagnostics = int(resp_diag.headers.get("content-range", "*/0").split("/")[-1])

    resp_unread = await c.get("/messages?select=id&read=eq.false", headers=headers_count)
    unread_messages = int(resp_unread.headers.get("content-range", "*/0").split("/")[-1])

    resp_replied = await c.get("/messages?select=id&replied=eq.true", headers=headers_count)
    total_replied = int(resp_replied.headers.get("content-range", "*/0").split("/")[-1])

    response_rate = round((total_replied / total_leads * 100), 1) if total_leads > 0 else 0

    return {
        "total_leads": total_leads,
        "total_diagnostics": total_diagnostics,
        "unread_messages": unread_messages,
        "response_rate": response_rate,
    }


# ══════════════════════════════════════════════════════════
# LEADS
# ══════════════════════════════════════════════════════════

async def upsert_lead(
    email: str,
    name: Optional[str] = None,
    source: str = "contact_form",
    phone: Optional[str] = None,
    company: Optional[str] = None,
) -> int:
    """Create or update a lead. Returns the lead ID."""
    c = _get_client()
    now = datetime.now(timezone.utc).isoformat()
    data = {"email": email, "source": source, "updated_at": now}
    if name:
        data["name"] = name
    if phone:
        data["phone"] = phone
    if company:
        data["company"] = company

    # Upsert: on conflict (email) update
    resp = await c.post(
        "/leads",
        params={"on_conflict": "email"},
        json=data,
        headers={
            "Prefer": "return=representation,resolution=merge-duplicates",
        },
    )
    _check(resp, "upsert_lead")
    return resp.json()[0]["id"]


async def update_lead_status(lead_id: int, status: str) -> bool:
    """Update a lead's status."""
    c = _get_client()
    resp = await c.patch(
        f"/leads?id=eq.{lead_id}",
        json={"status": status},
    )
    _check(resp, "update_lead_status")
    return len(resp.json()) > 0


async def list_leads(status: Optional[str] = None) -> list[dict]:
    """List leads, optionally filtered by status."""
    c = _get_client()
    params = {"order": "created_at.desc"}
    if status:
        params["status"] = f"eq.{status}"
    resp = await c.get("/leads", params=params)
    _check(resp, "list_leads")
    return resp.json()


async def get_lead_by_email(email: str) -> Optional[dict]:
    """Get a lead by email."""
    c = _get_client()
    resp = await c.get("/leads", params={"email": f"eq.{email}", "limit": "1"})
    _check(resp, "get_lead_by_email")
    rows = resp.json()
    return rows[0] if rows else None


async def add_lead_event(lead_id: int, event_type: str, metadata: Optional[dict] = None) -> int:
    """Log an event for a lead."""
    c = _get_client()
    resp = await c.post("/lead_events", json={
        "lead_id": lead_id,
        "event_type": event_type,
        "metadata": metadata or {},
    })
    _check(resp, "add_lead_event")
    return resp.json()[0]["id"]


# ══════════════════════════════════════════════════════════
# EMAIL CAPTURES
# ══════════════════════════════════════════════════════════

async def capture_email(
    email: str,
    url_diagnosed: Optional[str] = None,
    source_page: str = "landing",
    utm_source: Optional[str] = None,
    utm_medium: Optional[str] = None,
    utm_campaign: Optional[str] = None,
    ip_hash: Optional[str] = None,
) -> int:
    """Capture an email from the diagnostic gate. Returns capture ID."""
    c = _get_client()
    resp = await c.post("/email_captures", json={
        "email": email,
        "url_diagnosed": url_diagnosed,
        "source_page": source_page,
        "utm_source": utm_source,
        "utm_medium": utm_medium,
        "utm_campaign": utm_campaign,
        "ip_hash": ip_hash,
    })
    _check(resp, "capture_email")
    return resp.json()[0]["id"]
