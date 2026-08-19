"""Phase 7 tests: mirror_create.py - config-driven mirror issue creation."""

from __future__ import annotations


class FakeJiraClient:
    """Records create_issue/create_issue_link calls, returns a fixed key."""

    def __init__(self, created_key: str = "JJST-8"):
        self._created_key = created_key
        self.create_issue_calls: list[dict] = []
        self.create_issue_link_calls: list[dict] = []

    def create_issue(self, **kwargs):
        self.create_issue_calls.append(kwargs)
        return self._created_key

    def create_issue_link(self, **kwargs):
        self.create_issue_link_calls.append(kwargs)


def test_resolve_epic_returns_flat_epic_when_configured():
    from mirror_create import resolve_epic

    cfg = {"flat_epic_key": "BC-33"}
    assert resolve_epic(cfg, "Service Request") == "BC-33"
    assert resolve_epic(cfg, "Incident Request") == "BC-33"


def test_resolve_epic_picks_sr_epic_for_service_request():
    from mirror_create import resolve_epic

    cfg = {"sr_epic_key": "KM-178", "bf_epic_key": "KM-179"}
    assert resolve_epic(cfg, "Service Request") == "KM-178"


def test_resolve_epic_picks_bf_epic_for_non_service_request():
    from mirror_create import resolve_epic

    cfg = {"sr_epic_key": "KM-178", "bf_epic_key": "KM-179"}
    assert resolve_epic(cfg, "Incident Request") == "KM-179"
    assert resolve_epic(cfg, "Change Request") == "KM-179"


def test_resolve_epic_returns_none_when_target_has_no_epic_config():
    from mirror_create import resolve_epic

    cfg = {"target_project_id": "12719", "task_issuetype_id": "11440"}
    assert resolve_epic(cfg, "Service Request") is None
    assert resolve_epic(cfg, "Incident Request") is None


def test_create_mirror_returns_none_for_unconfigured_project():
    from mirror_create import create_mirror

    client = FakeJiraClient()
    result = create_mirror(
        client,
        source_issue_key="ZZZ-1",
        source_project_key="ZZZ",
        source_issuetype_name="Service Request",
        summary="unrelated project",
    )

    assert result is None
    assert client.create_issue_calls == []
    assert client.create_issue_link_calls == []


def test_create_mirror_jtt_service_request_creates_in_jjst_no_epic_no_account():
    from mirror_create import create_mirror

    client = FakeJiraClient(created_key="JJST-8")
    result = create_mirror(
        client,
        source_issue_key="JTT-111",
        source_project_key="JTT",
        source_issuetype_name="Service Request",
        summary="SR TEST",
        description="body",
    )

    assert result == "JJST-8"
    assert len(client.create_issue_calls) == 1
    create_call = client.create_issue_calls[0]
    assert create_call["project_id"] == "12719"
    assert create_call["issuetype_id"] == "11440"
    assert create_call["summary"] == "SR TEST"
    assert create_call["description"] == "body"
    assert create_call["parent_key"] is None
    assert create_call["account_field_id"] is None
    assert create_call["account_option_id"] is None


def test_create_mirror_links_new_issue_as_inward_and_source_as_outward():
    from mirror_create import create_mirror

    client = FakeJiraClient(created_key="JJST-8")
    create_mirror(
        client,
        source_issue_key="JTT-111",
        source_project_key="JTT",
        source_issuetype_name="Service Request",
        summary="SR TEST",
    )

    assert len(client.create_issue_link_calls) == 1
    link_call = client.create_issue_link_calls[0]
    assert link_call["link_type_id"] == "10012"
    assert link_call["inward_issue_key"] == "JJST-8"
    assert link_call["outward_issue_key"] == "JTT-111"


def test_create_mirror_jt2_and_jt3_route_to_correct_test_targets():
    from mirror_create import create_mirror

    client = FakeJiraClient(created_key="JJST2-1")
    create_mirror(
        client,
        source_issue_key="JT2-5",
        source_project_key="JT2",
        source_issuetype_name="Incident Request",
        summary="x",
    )
    assert client.create_issue_calls[0]["project_id"] == "12720"
    assert client.create_issue_calls[0]["issuetype_id"] == "11446"

    client2 = FakeJiraClient(created_key="JJST3-1")
    create_mirror(
        client2,
        source_issue_key="JT3-5",
        source_project_key="JT3",
        source_issuetype_name="Service Request",
        summary="x",
    )
    assert client2.create_issue_calls[0]["project_id"] == "12721"
    assert client2.create_issue_calls[0]["issuetype_id"] == "11452"


def test_create_mirror_link_direction_satisfies_the_real_jsm_mirror_link_consumer():
    from jsm_mirror_link import find_mirror_issue_key
    from mirror_create import create_mirror

    client = FakeJiraClient(created_key="JJST-8")
    create_mirror(
        client,
        source_issue_key="JTT-111",
        source_project_key="JTT",
        source_issuetype_name="Service Request",
        summary="SR TEST",
    )

    link_call = client.create_issue_link_calls[0]
    source_side_issuelinks = [
        {
            "type": {"name": "JSM Mirror", "inward": "is mirrored by", "outward": "mirrors"},
            "inwardIssue": {"key": link_call["inward_issue_key"]},
        }
    ]

    found = find_mirror_issue_key(source_side_issuelinks)

    assert found == "JJST-8"
