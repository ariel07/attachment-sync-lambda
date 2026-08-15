"""Phase 3 tests: JiraClient.

Verified against official Atlassian docs (fetched live, not from training
memory):
  - GET /rest/api/3/issue/{key}?fields=... returns the standard issue shape
  - GET attachment content URL (fields.attachment[].content) returns raw bytes
  - POST /rest/api/3/issue/{key}/attachments requires:
      - X-Atlassian-Token: no-check header
      - multipart/form-data with field name "file"
    https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-attachments/

Uses a fake HTTP session (dependency injection) rather than a mocking
library, per the project's "minimal dependencies" rule - no extra package
needed beyond what production code already uses (requests).
"""

from __future__ import annotations

import pytest


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, content=b""):
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

    def get(self, url, auth=None, params=None, timeout=None, **kwargs):
        self.calls.append(
            {"method": "GET", "url": url, "auth": auth, "params": params, "timeout": timeout}
        )
        return self._responses.pop(0)

    def post(self, url, auth=None, headers=None, files=None, timeout=None, **kwargs):
        self.calls.append(
            {
                "method": "POST",
                "url": url,
                "auth": auth,
                "headers": headers,
                "files": files,
                "timeout": timeout,
            }
        )
        return self._responses.pop(0)


def test_get_issue_requests_correct_url_and_fields():
    from jira_client import JiraClient

    fake_issue = {"key": "JTT-102", "fields": {"issuelinks": []}}
    session = FakeSession([FakeResponse(200, json_data=fake_issue)])
    client = JiraClient(
        base_url="https://icxeed.atlassian.net",
        email="svc@icxeed.ai",
        api_token="fake-token",
        session=session,
    )

    result = client.get_issue("JTT-102", fields=["issuelinks", "attachment"])

    assert result == fake_issue
    call = session.calls[0]
    assert call["method"] == "GET"
    assert call["url"] == "https://icxeed.atlassian.net/rest/api/3/issue/JTT-102"
    assert call["params"] == {"fields": "issuelinks,attachment"}
    assert call["auth"] == ("svc@icxeed.ai", "fake-token")
    assert call["timeout"] is not None  # defensive: must never be an unbounded call


def test_get_issue_raises_on_http_error():
    from jira_client import JiraClient

    session = FakeSession([FakeResponse(404)])
    client = JiraClient(
        "https://icxeed.atlassian.net", "svc@icxeed.ai", "fake-token", session=session
    )

    with pytest.raises(RuntimeError):
        client.get_issue("NOPE-1", fields=["issuelinks"])


def test_download_attachment_returns_raw_bytes():
    from jira_client import JiraClient

    fake_bytes = b"\x89PNG\r\n\x1a\n fake png bytes"
    session = FakeSession([FakeResponse(200, content=fake_bytes)])
    client = JiraClient(
        "https://icxeed.atlassian.net", "svc@icxeed.ai", "fake-token", session=session
    )

    content_url = "https://api.atlassian.com/ex/jira/xxx/rest/api/3/attachment/content/31711"
    result = client.download_attachment(content_url)

    assert result == fake_bytes
    call = session.calls[0]
    assert call["url"] == content_url
    assert call["auth"] == ("svc@icxeed.ai", "fake-token")


def test_upload_attachment_sends_correct_multipart_request():
    from jira_client import JiraClient

    fake_response = [{"id": "99999", "filename": "image-20260812-021129.png"}]
    session = FakeSession([FakeResponse(200, json_data=fake_response)])
    client = JiraClient(
        "https://icxeed.atlassian.net", "svc@icxeed.ai", "fake-token", session=session
    )

    result = client.upload_attachment(
        issue_key="JJST-4",
        filename="image-20260812-021129.png",
        content=b"fake image bytes",
        mime_type="image/png",
    )

    assert result == fake_response
    call = session.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://icxeed.atlassian.net/rest/api/3/issue/JJST-4/attachments"
    assert call["headers"] == {"X-Atlassian-Token": "no-check"}
    assert call["files"] == {
        "file": ("image-20260812-021129.png", b"fake image bytes", "image/png")
    }
    assert call["timeout"] is not None


def test_upload_attachment_raises_on_http_error():
    from jira_client import JiraClient

    session = FakeSession([FakeResponse(413)])  # payload too large
    client = JiraClient(
        "https://icxeed.atlassian.net", "svc@icxeed.ai", "fake-token", session=session
    )

    with pytest.raises(RuntimeError):
        client.upload_attachment("JJST-4", "big.zip", b"x" * 100, "application/zip")
