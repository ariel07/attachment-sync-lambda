"""Phase 6 (in progress) tests: handle_webhook's temporary capture path for
attachment_deleted events.

This path exists ONLY to capture a real payload from icxeed.atlassian.net -
it must never attempt to sync/delete anything, since no confirmed shape or
matching logic exists yet (see docs/phase6-attachment-delete-sync.md
and the changelog investigation that ruled out jira:issue_updated for this
purpose). It must fire even when the payload has no issue.key at all, since
attachment_created (the sibling event) proved that's a real possibility for
this event family - so this check must run BEFORE
extract_issue_key_from_webhook's 400 short-circuit, not after.
"""

from __future__ import annotations

import json

from signature import compute_x_hub_signature

SECRET = "test-webhook-signing-secret"


class _UnusedJiraClient:
    """Deliberately has no working methods - if the capture path ever calls
    into the Jira client, these tests must fail loudly, not silently pass."""

    def get_issue(self, *args, **kwargs):
        raise AssertionError("capture path must not call get_issue")

    def download_attachment(self, *args, **kwargs):
        raise AssertionError("capture path must not call download_attachment")

    def upload_attachment(self, *args, **kwargs):
        raise AssertionError("capture path must not call upload_attachment")

    def delete_attachment(self, *args, **kwargs):
        raise AssertionError("capture path must not call delete_attachment")


def test_handle_webhook_captures_attachment_deleted_without_issue_key():
    """Mirrors the confirmed attachment_created shape (no issue reference at
    all) as the worst case this path must survive."""
    from handler import handle_webhook

    body = json.dumps(
        {
            "timestamp": 1786698564597,
            "webhookEvent": "attachment_deleted",
            "attachment": {"id": "31819", "filename": "Logged Time - Jira.pdf"},
        }
    )
    signature = compute_x_hub_signature(SECRET, body)
    headers = {"X-Hub-Signature": signature}

    response = handle_webhook(
        body,
        headers=headers,
        webhook_signing_secret=SECRET,
        jira_client=_UnusedJiraClient(),
    )

    assert response["statusCode"] == 200
    result = json.loads(response["body"])
    assert result["status"] == "captured"
    assert result["reason"] == "attachment_deleted_capture_only"


def test_handle_webhook_captures_attachment_deleted_with_issue_key():
    """If the real payload DOES include an issue key, the capture path still
    just logs and returns - it must not fall through into sync logic just
    because enough fields happen to be present."""
    from handler import handle_webhook

    body = json.dumps(
        {
            "timestamp": 1786698564597,
            "webhookEvent": "attachment_deleted",
            "issue": {"key": "JTT-102"},
            "attachment": {"id": "31819", "filename": "Logged Time - Jira.pdf"},
        }
    )
    signature = compute_x_hub_signature(SECRET, body)
    headers = {"X-Hub-Signature": signature}

    response = handle_webhook(
        body,
        headers=headers,
        webhook_signing_secret=SECRET,
        jira_client=_UnusedJiraClient(),
    )

    assert response["statusCode"] == 200
    result = json.loads(response["body"])
    assert result["status"] == "captured"


def test_handle_webhook_still_rejects_bad_signature_before_capture_check():
    """Signature verification must still happen first - the capture path is
    not an auth bypass."""
    from handler import handle_webhook

    body = json.dumps({"webhookEvent": "attachment_deleted"})

    response = handle_webhook(
        body,
        headers={},
        webhook_signing_secret=SECRET,
        jira_client=_UnusedJiraClient(),
    )

    assert response["statusCode"] == 401
