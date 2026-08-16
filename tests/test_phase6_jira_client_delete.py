"""Phase 6 (in progress) tests: JiraClient.delete_attachment.

Verified against official Atlassian docs (fetched live, not from training
memory):
  DELETE /rest/api/3/attachment/{id}
  https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-attachments/
  Response codes (confirmed against the v2 doc page, which documents the
  same resource/operation the v3 page lists without expanding response
  detail - v2/v3 share attachment endpoints, only field-rendering differs
  for issue-shaped resources, not this one):
    204 No Content - deletion succeeded, empty body
    403 Forbidden  - attachments disabled, or caller lacks delete permission
    404 Not Found  - attachment id does not exist / not accessible

This file only covers the confirmed, non-webhook-shape-dependent piece of
Phase 6 (see docs/phase6-*.md for what's still blocked and why). Uses the
same FakeSession dependency-injection pattern as
tests/test_phase3_jira_client.py rather than a mocking library.
"""

from __future__ import annotations

import pytest


class FakeResponse:
    def __init__(self, status_code=204, json_data=None, content=b""):
        self.status_code = status_code
        self._json_data = json_data
        self.content = content

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    """Records calls and returns pre-programmed responses, in call order."""

    def __init__(self, responses: list[FakeResponse]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def delete(self, url, auth=None, timeout=None, **kwargs):
        self.calls.append({"method": "DELETE", "url": url, "auth": auth, "timeout": timeout})
        return self._responses.pop(0)


def test_delete_attachment_sends_correct_request():
    from jira_client import JiraClient

    session = FakeSession([FakeResponse(204)])
    client = JiraClient(
        base_url="https://icxeed.atlassian.net",
        email="svc@icxeed.ai",
        api_token="fake-token",
        session=session,
    )

    result = client.delete_attachment("31804")

    assert result is None
    call = session.calls[0]
    assert call["method"] == "DELETE"
    assert call["url"] == "https://icxeed.atlassian.net/rest/api/3/attachment/31804"
    assert call["auth"] == ("svc@icxeed.ai", "fake-token")
    assert call["timeout"] is not None  # defensive: must never be an unbounded call


def test_delete_attachment_raises_on_forbidden():
    """403: attachments disabled, or service account lacks delete
    permission on this project - the exact scenario flagged as unconfirmed
    in docs/phase6-attachment-delete-sync.md open question #5."""
    from jira_client import JiraClient

    session = FakeSession([FakeResponse(403)])
    client = JiraClient(
        "https://icxeed.atlassian.net", "svc@icxeed.ai", "fake-token", session=session
    )

    with pytest.raises(RuntimeError):
        client.delete_attachment("31804")


def test_delete_attachment_raises_on_not_found():
    """404: already gone. Caller (not this client) is responsible for
    deciding whether that's an error or an idempotent no-op - see open
    question #4 in the Phase 6 handoff. This test only locks in that the
    client itself surfaces the HTTP error rather than swallowing it."""
    from jira_client import JiraClient

    session = FakeSession([FakeResponse(404)])
    client = JiraClient(
        "https://icxeed.atlassian.net", "svc@icxeed.ai", "fake-token", session=session
    )

    with pytest.raises(RuntimeError):
        client.delete_attachment("99999999")
