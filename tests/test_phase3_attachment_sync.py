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
    dependency needed for these tests.

    target_issue_data models the SEPARATE get_issue call sync_new_attachment
    now makes against the mirror issue (Phase 4 dedupe check). Defaults to
    an empty attachment list so every existing test in this file - none of
    which cares about dedupe - continues to exercise the "not a duplicate"
    path with no changes required.
    """

    def __init__(
        self,
        issue_data: dict,
        download_bytes: bytes = b"fake-bytes",
        target_issue_data: dict | None = None,
    ):
        self._issue_data = issue_data
        self._download_bytes = download_bytes
        self._target_issue_data = (
            target_issue_data
            if target_issue_data is not None
            else {"fields": {"attachment": []}}
        )
        self.get_issue_calls: list[dict] = []
        self.download_calls: list[str] = []
        self.upload_calls: list[dict] = []

    def get_issue(self, issue_key: str, fields: list[str]) -> dict[str, Any]:
        self.get_issue_calls.append({"issue_key": issue_key, "fields": fields})
        if issue_key == self._issue_data.get("key"):
            return self._issue_data
        return self._target_issue_data

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


# --- Phase 5b: source_project / target_project fields for observability ----
# Added so CloudWatch Logs Insights queries can filter/group by client pair
# (e.g. "how many syncs for ABB this week") without parsing issue keys out
# of source_issue/target_issue by hand - flagged as a known gap in
# docs/phase5-scaling-to-additional-pairs.md before this was built.

def test_synced_result_includes_source_and_target_project():
    from attachment_sync import sync_new_attachment

    client = FakeJiraClient(_issue_with_links_and_attachments())
    result = sync_new_attachment(client, jsm_issue_key="JTT-102", attachment_id="31711")

    assert result["source_project"] == "JTT"
    assert result["target_project"] == "JJST"


def test_skipped_no_mirror_link_result_includes_source_project_only():
    # No target_issue is resolved on this path, so there's nothing to
    # derive target_project from - must not be present, not an empty string.
    from attachment_sync import sync_new_attachment

    issue = {"key": "JTT-999", "fields": {"issuelinks": [], "attachment": []}}
    client = FakeJiraClient(issue)
    result = sync_new_attachment(client, jsm_issue_key="JTT-999", attachment_id=None)

    assert result["source_project"] == "JTT"
    assert "target_project" not in result


def test_skipped_already_synced_result_includes_both_projects():
    from attachment_sync import sync_new_attachment

    target_with_existing = {
        "fields": {"attachment": [{"filename": "image-20260812-021129.png", "size": 39183}]}
    }
    client = FakeJiraClient(_issue_with_links_and_attachments(), target_issue_data=target_with_existing)
    result = sync_new_attachment(client, jsm_issue_key="JTT-102", attachment_id="31711")

    assert result["status"] == "skipped"
    assert result["reason"] == "already_synced"
    assert result["source_project"] == "JTT"
    assert result["target_project"] == "JJST"


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


# --- Phase 4: loop guard / idempotency, integrated into sync_new_attachment ---
# See docs/phase3-core-logic.md "Known gaps carried forward" for why this
# wasn't part of Phase 3, and dedupe_check.py for the filename+size
# strategy's own unit tests (this file only tests the integration point).

def test_sync_new_attachment_skips_when_already_synced():
    """The target issue already has an attachment with matching filename
    and size - this is a duplicate webhook delivery (or retry) for an
    attachment already mirrored. Must skip, not re-upload."""
    from attachment_sync import sync_new_attachment

    # Target (mirror) issue already has the same file, same size, as the
    # source's 31711 attachment (image-20260812-021129.png, 39183 bytes -
    # see tests/fixtures/jtt_102_attachments.json).
    target_issue_data = {
        "fields": {
            "attachment": [
                {"filename": "image-20260812-021129.png", "size": 39183},
            ]
        }
    }
    client = FakeJiraClient(_issue_with_links_and_attachments(), target_issue_data=target_issue_data)

    result = sync_new_attachment(client, jsm_issue_key="JTT-102", attachment_id="31711")

    assert result["status"] == "skipped"
    assert result["reason"] == "already_synced"
    assert result["target_issue"] == "JJST-4"
    assert client.upload_calls == []  # must not re-upload
    assert client.download_calls == []  # must not even download - skip before that


def test_sync_new_attachment_proceeds_when_target_has_different_attachments():
    """Target issue has attachments, but none match this one by
    filename+size - not a duplicate, sync should proceed normally.
    (This is effectively the existing happy-path test with an explicit,
    non-empty target_issue_data, to confirm the dedupe check doesn't
    false-positive on an unrelated existing attachment.)"""
    from attachment_sync import sync_new_attachment

    target_issue_data = {
        "fields": {
            "attachment": [
                {"filename": "unrelated-file.pdf", "size": 999},
            ]
        }
    }
    client = FakeJiraClient(_issue_with_links_and_attachments(), target_issue_data=target_issue_data)

    result = sync_new_attachment(client, jsm_issue_key="JTT-102", attachment_id="31711")

    assert result["status"] == "synced"
    assert len(client.upload_calls) == 1


def test_sync_new_attachment_dedupe_check_uses_mirror_key_not_source_key():
    """The dedupe check's second get_issue call must target the MIRROR
    issue (JJST-4), not the source JSM issue (JTT-102) again - confirms
    the integration point queries the right issue for existing
    attachments, not accidentally re-checking the source."""
    from attachment_sync import sync_new_attachment

    client = FakeJiraClient(_issue_with_links_and_attachments())
    sync_new_attachment(client, jsm_issue_key="JTT-102", attachment_id="31711")

    issue_keys_queried = [call["issue_key"] for call in client.get_issue_calls]
    assert issue_keys_queried == ["JTT-102", "JJST-4"]
