"""Phase 7 tests: handle_webhook()'s jira:issue_created branch.

Covers the mirror create+link path that replaces the native "Auto-create
mirror" rule. Uses the same FakeJiraClient-with-fakes pattern as
test_phase3_handler.py, extended with create_issue/create_issue_link.
"""

from __future__ import annotations

import json

from signature import compute_x_hub_signature

SECRET = "test-webhook-signing-secret"


class FakeMirrorJiraClient:
    """get_issue is used here for the idempotency check (existing
    issuelinks), not for the attachment-sync target lookup - different
    call site, same method name on the real client."""

    def __init__(self, existing_issuelinks: list[dict] | None = None, created_key: str = "KM-500"):
        self._existing_issuelinks = existing_issuelinks if existing_issuelinks is not None else []
        self._created_key = created_key
        self.get_issue_calls: list[dict] = []
        self.create_issue_calls: list[dict] = []
        self.create_issue_link_calls: list[dict] = []

    def get_issue(self, issue_key, fields):
        self.get_issue_calls.append({"issue_key": issue_key, "fields": fields})
        return {"fields": {"issuelinks": self._existing_issuelinks}}

    def create_issue(self, **kwargs):
        self.create_issue_calls.append(kwargs)
        return self._created_key

    def create_issue_link(self, **kwargs):
        self.create_issue_link_calls.append(kwargs)


def _issue_created_body(
    issue_key="KMS-100",
    project_key="KMS",
    issuetype_name="Service Request",
    summary="SR TEST",
):
    return {
        "timestamp": 1735689600000,
        "webhookEvent": "jira:issue_created",
        "issue": {
            "id": "32700",
            "key": issue_key,
            "self": f"https://x/issue/{issue_key}",
            "fields": {
                "project": {"key": project_key, "id": "10981"},
                "issuetype": {"name": issuetype_name, "id": "10558"},
                "summary": summary,
                "description": None,
            },
        },
    }


def test_issue_created_webhook_creates_mirror_and_link():
    from handler import handle_webhook

    body = json.dumps(_issue_created_body())
    signature = compute_x_hub_signature(SECRET, body)
    headers = {"X-Hub-Signature": signature}
    client = FakeMirrorJiraClient(existing_issuelinks=[], created_key="KM-500")

    response = handle_webhook(
        body, headers=headers, webhook_signing_secret=SECRET, jira_client=client
    )

    assert response["statusCode"] == 200
    result = json.loads(response["body"])
    assert result["status"] == "created"
    assert result["source_issue"] == "KMS-100"
    assert result["mirror_issue"] == "KM-500"
    assert len(client.create_issue_calls) == 1
    assert client.create_issue_calls[0]["parent_key"] == "KM-178"  # Service Request epic
    assert len(client.create_issue_link_calls) == 1


def test_issue_created_webhook_rejects_missing_signature():
    from handler import handle_webhook

    body = json.dumps(_issue_created_body())
    client = FakeMirrorJiraClient()

    response = handle_webhook(body, headers={}, webhook_signing_secret=SECRET, jira_client=client)

    assert response["statusCode"] == 401
    assert client.create_issue_calls == []


def test_issue_created_webhook_skips_project_not_in_mirror_map():
    from handler import handle_webhook

    body = json.dumps(_issue_created_body(issue_key="ZZZ-1", project_key="ZZZ"))
    signature = compute_x_hub_signature(SECRET, body)
    headers = {"X-Hub-Signature": signature}
    client = FakeMirrorJiraClient()

    response = handle_webhook(
        body, headers=headers, webhook_signing_secret=SECRET, jira_client=client
    )

    assert response["statusCode"] == 200
    result = json.loads(response["body"])
    assert result["status"] == "skipped"
    assert result["reason"] == "project_not_mirrored"
    assert client.create_issue_calls == []


def test_issue_created_webhook_idempotency_guard_skips_already_linked_issue():
    """Guards against the webhook's confirmed double-fire behavior (seen
    live in CloudWatch for JTT-109/JTT-110, each fired twice). Must not
    create a second mirror issue for a ticket that already has one."""
    from handler import handle_webhook

    body = json.dumps(_issue_created_body())
    signature = compute_x_hub_signature(SECRET, body)
    headers = {"X-Hub-Signature": signature}
    already_linked = [{"type": {"id": "10012"}, "outwardIssue": {"key": "KM-500"}}]
    client = FakeMirrorJiraClient(existing_issuelinks=already_linked)

    response = handle_webhook(
        body, headers=headers, webhook_signing_secret=SECRET, jira_client=client
    )

    assert response["statusCode"] == 200
    result = json.loads(response["body"])
    assert result["status"] == "skipped"
    assert result["reason"] == "already_linked"
    assert client.create_issue_calls == []
    assert client.create_issue_link_calls == []


def test_issue_created_webhook_ignores_unrelated_issue_links():
    """Idempotency check must only match on the JSM Mirror link type id
    (10012), not skip just because SOME link exists."""
    from handler import handle_webhook

    body = json.dumps(_issue_created_body())
    signature = compute_x_hub_signature(SECRET, body)
    headers = {"X-Hub-Signature": signature}
    unrelated_link = [{"type": {"id": "10099"}, "outwardIssue": {"key": "OTHER-1"}}]
    client = FakeMirrorJiraClient(existing_issuelinks=unrelated_link, created_key="KM-500")

    response = handle_webhook(
        body, headers=headers, webhook_signing_secret=SECRET, jira_client=client
    )

    assert response["statusCode"] == 200
    result = json.loads(response["body"])
    assert result["status"] == "created"
    assert len(client.create_issue_calls) == 1


def test_issue_created_webhook_returns_400_on_malformed_payload():
    from handler import handle_webhook

    malformed = {"webhookEvent": "jira:issue_created", "issue": {"key": "KMS-1", "fields": {}}}
    body = json.dumps(malformed)  # missing project/issuetype/summary
    signature = compute_x_hub_signature(SECRET, body)
    headers = {"X-Hub-Signature": signature}
    client = FakeMirrorJiraClient()

    response = handle_webhook(
        body, headers=headers, webhook_signing_secret=SECRET, jira_client=client
    )

    assert response["statusCode"] == 400
    assert client.create_issue_calls == []


def test_issue_created_service_request_vs_incident_request_pick_different_epics():
    """Regression guard: two issue_created events in sequence for
    different issuetypes must each resolve their own epic correctly, not
    leak state between calls."""
    from handler import handle_webhook

    body_sr = json.dumps(_issue_created_body(issue_key="KMS-1", issuetype_name="Service Request"))
    sig_sr = compute_x_hub_signature(SECRET, body_sr)
    client_sr = FakeMirrorJiraClient(created_key="KM-510")
    handle_webhook(
        body_sr,
        headers={"X-Hub-Signature": sig_sr},
        webhook_signing_secret=SECRET,
        jira_client=client_sr,
    )

    body_ir = json.dumps(_issue_created_body(issue_key="KMS-2", issuetype_name="Incident Request"))
    sig_ir = compute_x_hub_signature(SECRET, body_ir)
    client_ir = FakeMirrorJiraClient(created_key="KM-511")
    handle_webhook(
        body_ir,
        headers={"X-Hub-Signature": sig_ir},
        webhook_signing_secret=SECRET,
        jira_client=client_ir,
    )

    assert client_sr.create_issue_calls[0]["parent_key"] == "KM-178"
    assert client_ir.create_issue_calls[0]["parent_key"] == "KM-179"


def test_issue_created_change_request_picks_change_request_epic():
    from handler import handle_webhook

    body = json.dumps(_issue_created_body(issue_key="KMS-3", issuetype_name="Change Request"))
    sig = compute_x_hub_signature(SECRET, body)
    client = FakeMirrorJiraClient(created_key="KM-512")

    handle_webhook(
        body, headers={"X-Hub-Signature": sig}, webhook_signing_secret=SECRET, jira_client=client
    )

    assert client.create_issue_calls[0]["parent_key"] == "KM-231"
