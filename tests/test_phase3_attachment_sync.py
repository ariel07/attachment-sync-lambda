"""Phase 3 tests: sync orchestration (attachment_sync.py).

Design note (why this doesn't parse the webhook body's attachment field
directly): Phase 2 confirmed the webhook envelope's `issue.key` field from
official docs, but could NOT confirm the exact shape of the attachment data
embedded in an attachment_created payload (see
tests/test_phase2_payload_schema.py - that test is still SKIPped).

Rather than guess at that shape and risk building on an invented schema,
this orchestration treats the webhook as a trigger only: it extracts the
issue key (confirmed field), then re-fetches the issue's attachment list via
GET /rest/api/3/issue/{key}?fields=attachment - a call whose response shape
IS confirmed (tests/fixtures/jtt_102_attachments.json, captured live). If a
real captured webhook payload later confirms an `attachment.id` field, that
id is used to pick the exact attachment; if not, the most recently created
attachment is used as a best-effort fallback (documented explicitly as a
fallback, not silently).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_fixture(name: str) -> dict:
    with open(FIXTURES / name, encoding="utf-8") as f:
        return json.load(f)


class FakeJiraClient:
    """Records calls; returns pre-programmed data. No network, no requests
    dependency needed for these tests."""

    def __init__(self, issue_data: dict, download_bytes: bytes = b"fake-bytes"):
        self._issue_data = issue_data
        self._download_bytes = download_bytes
        self.get_issue_calls: list[dict] = []
        self.download_calls: list[str] = []
        self.upload_calls: list[dict] = []

    def get_issue(self, issue_key: str, fields: list[str]) -> dict[str, Any]:
        self.get_issue_calls.append({"issue_key": issue_key, "fields": fields})
        return self._issue_data

    def download_attachment(self, content_url: str) -> bytes:
        self.download_calls.append(content_url)
        return self._download_bytes

    def upload_attachment(self, issue_key: str, filename: str, content: bytes, mime_type: str):
        self.upload_calls.append({
            "issue_key": issue_key, "filename": filename,
            "content": content, "mime_type": mime_type,
        })
        return [{"id": "new-id", "filename": filename}]


def _issue_with_links_and_attachments() -> dict:
    links = _load_fixture("jtt_102_issuelinks.json")["issuelinks"]
    attachments = _load_fixture("jtt_102_attachments.json")["attachment"]
    return {"key": "JTT-102", "fields": {"issuelinks": links, "attachment": attachments}}


def test_sync_new_attachment_happy_path_with_explicit_attachment_id():
    from attachment_sync import sync_new_attachment

    client = FakeJiraClient(_issue_with_links_and_attachments())
    result = sync_new_attachment(client, jsm_issue_key="JTT-102", attachment_id="31711")

    assert result["status"] == "synced"
    assert result["source_issue"] == "JTT-102"
    assert result["target_issue"] == "JJST-4"
    assert result["attachment_id"] == "31711"
    assert result["filename"] == "image-20260812-021129.png"

    # verify the right content URL was downloaded and the right target/mime used
    assert client.download_calls == [
        "https://api.atlassian.com/ex/jira/19ddd9fa-c177-467f-bfa3-58a0589dfb8d/rest/api/3/attachment/content/31711"
    ]
    upload = client.upload_calls[0]
    assert upload["issue_key"] == "JJST-4"
    assert upload["filename"] == "image-20260812-021129.png"
    assert upload["mime_type"] == "image/png"


def test_sync_new_attachment_falls_back_to_most_recent_when_no_id_given():
    from attachment_sync import sync_new_attachment

    client = FakeJiraClient(_issue_with_links_and_attachments())
    result = sync_new_attachment(client, jsm_issue_key="JTT-102", attachment_id=None)

    # fixture's two attachments: 31711 created 2026-08-12, 31758 created 2026-08-13 (later)
    assert result["status"] == "synced"
    assert result["attachment_id"] == "31758"
    assert result["filename"] == "Jira (3).html"
    assert result["fallback_used"] is True


def test_sync_new_attachment_handles_missing_thumbnail_field_gracefully():
    """The 31758 fixture entry (Jira (3).html) has no thumbnail field at all -
    confirmed live. Syncing it must not KeyError on a field that isn't there
    and isn't needed for the sync (thumbnail is never read by this code)."""
    from attachment_sync import sync_new_attachment

    client = FakeJiraClient(_issue_with_links_and_attachments())
    result = sync_new_attachment(client, jsm_issue_key="JTT-102", attachment_id="31758")
    assert result["status"] == "synced"
    assert result["filename"] == "Jira (3).html"


def test_sync_new_attachment_skips_when_no_mirror_link():
    from attachment_sync import sync_new_attachment

    issue = {"key": "JTT-999", "fields": {"issuelinks": [], "attachment": []}}
    client = FakeJiraClient(issue)
    result = sync_new_attachment(client, jsm_issue_key="JTT-999", attachment_id=None)

    assert result["status"] == "skipped"
    assert result["reason"] == "no_mirror_link"
    assert client.upload_calls == []  # must not attempt upload


def test_sync_new_attachment_skips_when_attachment_id_not_found():
    from attachment_sync import sync_new_attachment

    client = FakeJiraClient(_issue_with_links_and_attachments())
    result = sync_new_attachment(client, jsm_issue_key="JTT-102", attachment_id="does-not-exist")

    assert result["status"] == "skipped"
    assert result["reason"] == "attachment_not_found"
    assert client.upload_calls == []


def test_sync_new_attachment_skips_when_no_attachments_at_all():
    from attachment_sync import sync_new_attachment

    links = _load_fixture("jtt_102_issuelinks.json")["issuelinks"]
    issue = {"key": "JTT-102", "fields": {"issuelinks": links, "attachment": []}}
    client = FakeJiraClient(issue)
    result = sync_new_attachment(client, jsm_issue_key="JTT-102", attachment_id=None)

    assert result["status"] == "skipped"
    assert result["reason"] == "no_attachments"
    assert client.upload_calls == []


def test_extract_issue_key_from_webhook_uses_only_confirmed_field():
    """issue.key is confirmed by Atlassian docs for issue-related webhook
    events; this must not depend on any unconfirmed field."""
    from attachment_sync import extract_issue_key_from_webhook

    webhook_body = {
        "timestamp": 1735689600000,
        "webhookEvent": "attachment_created",
        "issue": {"id": "99291", "key": "JTT-102", "self": "https://x/issue/99291", "fields": {}},
    }
    assert extract_issue_key_from_webhook(webhook_body) == "JTT-102"


def test_extract_issue_key_from_webhook_raises_on_missing_issue():
    from attachment_sync import extract_issue_key_from_webhook, MalformedWebhookError

    with pytest.raises(MalformedWebhookError):
        extract_issue_key_from_webhook({"timestamp": 1, "webhookEvent": "attachment_created"})


def test_extract_attachment_id_from_webhook_when_present():
    """Best-effort: IF the webhook happens to include an attachment.id field
    (unconfirmed but plausible), use it. Must not raise if absent - that's
    the expected/common case until we've captured a real payload."""
    from attachment_sync import extract_attachment_id_from_webhook

    with_id = {"attachment": {"id": "31711"}}
    assert extract_attachment_id_from_webhook(with_id) == "31711"

    without_id = {"timestamp": 123, "webhookEvent": "attachment_created", "issue": {"key": "JTT-1"}}
    assert extract_attachment_id_from_webhook(without_id) is None
