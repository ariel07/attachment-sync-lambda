"""Phase 6 (in progress) tests: identifying attachment_deleted webhook events.

This is deliberately NOT sync-detection logic. It exists only to support a
temporary capture path in handler.py so a real attachment_deleted payload
can be captured from icxeed.atlassian.net, mirroring how Phase 2 captured
attachment_created before Phase 3 could be built against a real shape.

Per docs/phase6-attachment-delete-sync-handoff.md and the follow-up
investigation: JTT-102's actual changelog (24 entries, confirmed live via
Atlassian Rovo) shows NO removal entry for a real deleted attachment,
meaning jira:issue_updated's changelog cannot be used to detect deletions.
attachment_deleted is a separately documented Jira Cloud webhook event
(confirmed against https://developer.atlassian.com/cloud/jira/platform/webhooks/,
which names it explicitly as a Secondary-flow event) - this is the
candidate event to capture and verify.
"""

from __future__ import annotations


def test_is_attachment_deleted_event_true_for_matching_webhook_event():
    from attachment_sync import is_attachment_deleted_event

    body = {"webhookEvent": "attachment_deleted", "timestamp": 123}

    assert is_attachment_deleted_event(body) is True


def test_is_attachment_deleted_event_false_for_other_events():
    from attachment_sync import is_attachment_deleted_event

    assert is_attachment_deleted_event({"webhookEvent": "jira:issue_updated"}) is False
    assert is_attachment_deleted_event({"webhookEvent": "attachment_created"}) is False


def test_is_attachment_deleted_event_false_when_field_missing():
    """Defensive: an unexpected/malformed body should not be mistaken for a
    capture target - false, not an exception, so handle_webhook's normal
    parsing/validation path still runs for it."""
    from attachment_sync import is_attachment_deleted_event

    assert is_attachment_deleted_event({}) is False
