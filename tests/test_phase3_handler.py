"""Phase 3 tests: handle_webhook() - the testable core of handler.py.

lambda_handler() itself (the AWS entry point) is a thin wrapper that wires
real boto3/requests and is not unit tested here - there's nothing to assert
beyond "it calls the real SDKs", which is better verified by an actual
deployed invocation (Phase 7 - Testing, per the LOE) than by mocking boto3
internals. handle_webhook() contains all the actual decision logic and is
fully unit tested here with injected fakes.
"""
from __future__ import annotations

import json

from signature import compute_x_hub_signature

SECRET = "test-webhook-signing-secret"


class FakeJiraClient:
    def __init__(self, issue_data: dict):
        self._issue_data = issue_data
        self.upload_calls: list[dict] = []

    def get_issue(self, issue_key, fields):
        return self._issue_data

    def download_attachment(self, content_url):
        return b"fake-bytes"

    def upload_attachment(self, issue_key, filename, content, mime_type):
        self.upload_calls.append({"issue_key": issue_key, "filename": filename})
        return [{"id": "new"}]


def _issue_with_mirror_and_attachment():
    return {
        "key": "JTT-102",
        "fields": {
            "issuelinks": [
                {
                    "id": "11789",
                    "type": {"name": "JSM Mirror", "inward": "is mirrored by", "outward": "mirrors"},
                    "inwardIssue": {"key": "JJST-4", "id": "32541", "fields": {}},
                }
            ],
            "attachment": [
                {
                    "id": "31711",
                    "filename": "image.png",
                    "created": "2026-08-12T10:11:33.495+0800",
                    "mimeType": "image/png",
                    "content": "https://x/attachment/content/31711",
                }
            ],
        },
    }


def _webhook_body(issue_key="JTT-102"):
    return {
        "timestamp": 1735689600000,
        "webhookEvent": "attachment_created",
        "issue": {"id": "1", "key": issue_key, "self": "https://x/issue/1", "fields": {}},
    }


def test_handle_webhook_rejects_missing_signature():
    from handler import handle_webhook

    body = json.dumps(_webhook_body())
    client = FakeJiraClient(_issue_with_mirror_and_attachment())

    response = handle_webhook(body, headers={}, webhook_signing_secret=SECRET, jira_client=client)

    assert response["statusCode"] == 401
    assert client.upload_calls == []


def test_handle_webhook_rejects_wrong_signature():
    from handler import handle_webhook

    body = json.dumps(_webhook_body())
    client = FakeJiraClient(_issue_with_mirror_and_attachment())
    headers = {"x-hub-signature": "sha256=wrongwrongwrong"}

    response = handle_webhook(body, headers=headers, webhook_signing_secret=SECRET, jira_client=client)

    assert response["statusCode"] == 401
    assert client.upload_calls == []


def test_handle_webhook_accepts_valid_signature_and_syncs():
    from handler import handle_webhook

    body = json.dumps(_webhook_body())
    signature = compute_x_hub_signature(SECRET, body)
    headers = {"X-Hub-Signature": signature}  # deliberately mixed-case, header names are case-insensitive
    client = FakeJiraClient(_issue_with_mirror_and_attachment())

    response = handle_webhook(body, headers=headers, webhook_signing_secret=SECRET, jira_client=client)

    assert response["statusCode"] == 200
    result = json.loads(response["body"])
    assert result["status"] == "synced"
    assert result["target_issue"] == "JJST-4"
    assert len(client.upload_calls) == 1


def test_handle_webhook_returns_400_on_invalid_json():
    from handler import handle_webhook

    client = FakeJiraClient(_issue_with_mirror_and_attachment())
    signature = compute_x_hub_signature(SECRET, "not json")
    headers = {"X-Hub-Signature": signature}

    response = handle_webhook("not json", headers=headers, webhook_signing_secret=SECRET, jira_client=client)

    assert response["statusCode"] == 400


def test_handle_webhook_returns_400_on_missing_issue_key():
    from handler import handle_webhook

    body = json.dumps({"timestamp": 1, "webhookEvent": "attachment_created"})
    signature = compute_x_hub_signature(SECRET, body)
    headers = {"X-Hub-Signature": signature}
    client = FakeJiraClient(_issue_with_mirror_and_attachment())

    response = handle_webhook(body, headers=headers, webhook_signing_secret=SECRET, jira_client=client)

    assert response["statusCode"] == 400


def test_handle_webhook_returns_200_on_skip_no_mirror_link():
    """A skip is not a failure - Jira should see 200 so it doesn't retry."""
    from handler import handle_webhook

    body = json.dumps(_webhook_body(issue_key="JTT-999"))
    signature = compute_x_hub_signature(SECRET, body)
    headers = {"X-Hub-Signature": signature}
    unlinked_issue = {"key": "JTT-999", "fields": {"issuelinks": [], "attachment": []}}
    client = FakeJiraClient(unlinked_issue)

    response = handle_webhook(body, headers=headers, webhook_signing_secret=SECRET, jira_client=client)

    assert response["statusCode"] == 200
    result = json.loads(response["body"])
    assert result["status"] == "skipped"
    assert result["reason"] == "no_mirror_link"
