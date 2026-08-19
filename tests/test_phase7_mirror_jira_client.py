"""JiraClient.create_issue / create_issue_link.

Added to support mirror_create.py, replacing the native "Auto-create
mirror" automation rule's Create + Branch + Link steps (see
mirror_create.py module docstring for why). Uses the same FakeSession
pattern as test_phase3_jira_client.py - no new test dependency introduced.
"""

from __future__ import annotations

import pytest
from test_phase3_jira_client import FakeResponse, FakeSession


def test_create_issue_sends_minimal_fields_and_returns_key():
    from jira_client import JiraClient

    fake_response = {"id": "32700", "key": "JJST-8", "self": "https://x/issue/32700"}
    session = FakeSession([FakeResponse(201, json_data=fake_response)])
    client = JiraClient(
        "https://icxeed.atlassian.net", "svc@icxeed.ai", "fake-token", session=session
    )

    result = client.create_issue(
        project_id="12719",
        issuetype_id="11440",
        summary="SR TEST",
    )

    assert result == "JJST-8"
    call = session.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://icxeed.atlassian.net/rest/api/3/issue"
    body = call["json"]
    assert body["fields"]["project"] == {"id": "12719"}
    assert body["fields"]["issuetype"] == {"id": "11440"}
    assert body["fields"]["summary"] == "SR TEST"
    assert "description" not in body["fields"]
    assert "parent" not in body["fields"]
    assert "customfield_10108" not in body["fields"]


def test_create_issue_includes_parent_and_account_when_provided():
    from jira_client import JiraClient

    fake_response = {"id": "1", "key": "KM-300"}
    session = FakeSession([FakeResponse(201, json_data=fake_response)])
    client = JiraClient(
        "https://icxeed.atlassian.net", "svc@icxeed.ai", "fake-token", session=session
    )

    result = client.create_issue(
        project_id="11313",
        issuetype_id="10121",
        summary="SR TEST",
        description="body text",
        parent_key="KM-178",
        account_field_id="customfield_10108",
        account_option_id="3",
    )

    assert result == "KM-300"
    body = session.calls[0]["json"]
    assert body["fields"]["parent"] == {"key": "KM-178"}
    assert body["fields"]["customfield_10108"] == {"id": "3"}
    assert body["fields"]["description"] == {
        "type": "doc",
        "version": 1,
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "body text"}]}],
    }


def test_create_issue_omits_description_key_when_empty():
    """Regression guard for the Aug 19 bug: sending description at all
    when there's nothing to say (empty string) was part of what triggered
    the 400 - the fix is to not send the key, not to send an empty ADF
    document."""
    from jira_client import JiraClient

    session = FakeSession([FakeResponse(201, json_data={"key": "JJST-9"})])
    client = JiraClient(
        "https://icxeed.atlassian.net", "svc@icxeed.ai", "fake-token", session=session
    )

    client.create_issue(project_id="12719", issuetype_id="11440", summary="x", description="")

    assert "description" not in session.calls[0]["json"]["fields"]


def test_create_issue_raises_on_http_error():
    from jira_client import JiraClient

    session = FakeSession([FakeResponse(400)])
    client = JiraClient(
        "https://icxeed.atlassian.net", "svc@icxeed.ai", "fake-token", session=session
    )

    with pytest.raises(RuntimeError):
        client.create_issue(project_id="12719", issuetype_id="11440", summary="x")


def test_create_issue_logs_response_body_on_http_error(caplog):
    """The bug that motivated this: a real 400 from Jira came through
    CloudWatch with NO detail beyond "Bad Request for url: ..." -
    raise_for_status() alone discards the response body. This locks in
    that the body is logged before the exception propagates."""
    from jira_client import JiraClient

    session = FakeSession([FakeResponse(400, text='{"errorMessages":["description must be ADF"]}')])
    client = JiraClient(
        "https://icxeed.atlassian.net", "svc@icxeed.ai", "fake-token", session=session
    )

    with caplog.at_level("ERROR"):
        with pytest.raises(RuntimeError):
            client.create_issue(project_id="12719", issuetype_id="11440", summary="x")

    assert "description must be ADF" in caplog.text


def test_create_issue_link_sends_correct_direction():
    """outward_issue_key must land in the outwardIssue field, inward_issue_key
    in the inwardIssue field - this is a pure "does the method build the
    request body correctly" test, independent of which values mirror_create.py
    chooses to pass for its use case (see test_phase7_mirror_create.py's
    direction tests for that higher-level contract)."""
    from jira_client import JiraClient

    session = FakeSession([FakeResponse(201, json_data={})])
    client = JiraClient(
        "https://icxeed.atlassian.net", "svc@icxeed.ai", "fake-token", session=session
    )

    client.create_issue_link(
        link_type_id="10012",
        inward_issue_key="JTT-111",
        outward_issue_key="JJST-8",
    )

    call = session.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://icxeed.atlassian.net/rest/api/3/issueLink"
    body = call["json"]
    assert body["type"] == {"id": "10012"}
    assert body["inwardIssue"] == {"key": "JTT-111"}
    assert body["outwardIssue"] == {"key": "JJST-8"}


def test_create_issue_link_raises_on_http_error():
    from jira_client import JiraClient

    session = FakeSession([FakeResponse(404)])
    client = JiraClient(
        "https://icxeed.atlassian.net", "svc@icxeed.ai", "fake-token", session=session
    )

    with pytest.raises(RuntimeError):
        client.create_issue_link(
            link_type_id="10012", inward_issue_key="JTT-1", outward_issue_key="NOPE-1"
        )
