"""Phase 7 tests: mirror_create.py - config-driven mirror issue creation.
Three-way Service Request / Incident Request / Change Request branching),
replacing the earlier TMIR-family test config entirely.
"""

from __future__ import annotations


class FakeJiraClient:
    """Records create_issue/create_issue_link calls, returns a fixed key."""

    def __init__(self, created_key: str = "KM-500"):
        self._created_key = created_key
        self.create_issue_calls: list[dict] = []
        self.create_issue_link_calls: list[dict] = []

    def create_issue(self, **kwargs):
        self.create_issue_calls.append(kwargs)
        return self._created_key

    def create_issue_link(self, **kwargs):
        self.create_issue_link_calls.append(kwargs)


# --- resolve_epic() ---------------------------------------------------------


def test_resolve_epic_picks_sr_epic_for_service_request():
    from mirror_create import resolve_epic

    cfg = {"sr_epic_key": "KM-178", "bf_epic_key": "KM-179", "cr_epic_key": "KM-231"}
    assert resolve_epic(cfg, "Service Request") == "KM-178"


def test_resolve_epic_picks_bf_epic_for_incident_request():
    from mirror_create import resolve_epic

    cfg = {"sr_epic_key": "KM-178", "bf_epic_key": "KM-179", "cr_epic_key": "KM-231"}
    assert resolve_epic(cfg, "Incident Request") == "KM-179"


def test_resolve_epic_picks_cr_epic_for_change_request():
    from mirror_create import resolve_epic

    cfg = {"sr_epic_key": "KM-178", "bf_epic_key": "KM-179", "cr_epic_key": "KM-231"}
    assert resolve_epic(cfg, "Change Request") == "KM-231"


def test_resolve_epic_returns_none_for_unrecognized_issuetype():
    """Safer than guessing - an unexpected issue type (e.g. a bug/story
    that somehow lands in a JSM queue) gets no parent set, rather than
    silently defaulting to one of the three categories."""
    from mirror_create import resolve_epic

    cfg = {"sr_epic_key": "KM-178", "bf_epic_key": "KM-179", "cr_epic_key": "KM-231"}
    assert resolve_epic(cfg, "Bug") is None
    assert resolve_epic(cfg, "") is None


# --- create_mirror() ---------------------------------------------------------


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


def test_create_mirror_kms_service_request_creates_in_km_with_correct_epic_and_account():
    from mirror_create import create_mirror

    client = FakeJiraClient(created_key="KM-500")
    result = create_mirror(
        client,
        source_issue_key="KMS-100",
        source_project_key="KMS",
        source_issuetype_name="Service Request",
        summary="SR test",
        description="body",
    )

    assert result == "KM-500"
    assert len(client.create_issue_calls) == 1
    call = client.create_issue_calls[0]
    assert call["project_id"] == "11313"
    assert call["issuetype_id"] == "10121"
    assert call["parent_key"] == "KM-178"
    assert call["account_field_id"] == "customfield_10108"
    assert call["account_option_id"] == "3"


def test_create_mirror_kms_incident_request_uses_breakfix_epic():
    from mirror_create import create_mirror

    client = FakeJiraClient(created_key="KM-501")
    create_mirror(
        client,
        source_issue_key="KMS-101",
        source_project_key="KMS",
        source_issuetype_name="Incident Request",
        summary="BF test",
    )

    assert client.create_issue_calls[0]["parent_key"] == "KM-179"


def test_create_mirror_kms_change_request_uses_change_epic():
    from mirror_create import create_mirror

    client = FakeJiraClient(created_key="KM-502")
    create_mirror(
        client,
        source_issue_key="KMS-102",
        source_project_key="KMS",
        source_issuetype_name="Change Request",
        summary="CR test",
    )

    assert client.create_issue_calls[0]["parent_key"] == "KM-231"


def test_create_mirror_links_new_issue_as_inward_and_source_as_outward():
    """DIRECTION NOTE: empirically confirmed (Aug 19, real TSRC-114/TMIR-9
    test) mapping - see mirror_create.py's inline comment. Getting this
    backwards doesn't error - it silently creates a link the rest of the
    system (attachment sync) can't find."""
    from mirror_create import create_mirror

    client = FakeJiraClient(created_key="KM-500")
    create_mirror(
        client,
        source_issue_key="KMS-100",
        source_project_key="KMS",
        source_issuetype_name="Service Request",
        summary="SR test",
    )

    assert len(client.create_issue_link_calls) == 1
    link_call = client.create_issue_link_calls[0]
    assert link_call["link_type_id"] == "10012"
    assert link_call["inward_issue_key"] == "KM-500"
    assert link_call["outward_issue_key"] == "KMS-100"


def test_create_mirror_link_direction_satisfies_the_real_jsm_mirror_link_consumer():
    """End-to-end regression guard: builds the exact issuelinks shape the
    JSM-ticket side would have after create_mirror() runs, and feeds it
    into jsm_mirror_link.find_mirror_issue_key() - the actual, pre-existing
    attachment-sync consumer. Prevents a repeat of the Aug 19 production
    incident (link created successfully, but in the wrong direction)."""
    from jsm_mirror_link import find_mirror_issue_key
    from mirror_create import create_mirror

    client = FakeJiraClient(created_key="KM-500")
    create_mirror(
        client,
        source_issue_key="KMS-100",
        source_project_key="KMS",
        source_issuetype_name="Service Request",
        summary="SR test",
    )

    link_call = client.create_issue_link_calls[0]
    source_side_issuelinks = [
        {
            "type": {"name": "JSM Mirror", "inward": "is mirrored by", "outward": "mirrors"},
            "inwardIssue": {"key": link_call["inward_issue_key"]},
        }
    ]

    found = find_mirror_issue_key(source_side_issuelinks)

    assert found == "KM-500"


def test_create_mirror_all_nine_client_pairs_route_correctly():
    """Locks in every source->target project_id + issuetype_id mapping in
    one pass, so a typo in any one of the 9 MIRROR_MAP entries fails
    loudly rather than only surfacing when that specific client's traffic
    happens to flow through."""
    from mirror_create import create_mirror

    expected = {
        "AS": "11378",
        "BS": "11447",
        "BSUP": "11279",
        "CS": "11311",
        "GSP": "11316",
        "KMS": "11313",
        "SS": "11312",
        "UOFM": "11345",
        "OUAS": "11610",
    }

    for source_key, expected_project_id in expected.items():
        client = FakeJiraClient(created_key=f"{source_key}-MIRROR")
        create_mirror(
            client,
            source_issue_key=f"{source_key}-1",
            source_project_key=source_key,
            source_issuetype_name="Service Request",
            summary="x",
        )
        assert client.create_issue_calls[0]["project_id"] == expected_project_id
        assert client.create_issue_calls[0]["issuetype_id"] == "10121"


def test_create_mirror_che_and_scn_use_confirmed_billable_account():
    """CHE and SCN both have two Tempo Accounts in real use (Billable +
    Non-Billable) - Ariel confirmed Aug 22 that Billable is the correct
    classification for mirror-created tickets going forward, resolving
    the split-billing question flagged in the Phase 8 handoff. Locks in
    that confirmed choice so a future change is a deliberate, visible
    test change, not a silent drift."""
    from mirror_create import create_mirror

    che_client = FakeJiraClient(created_key="CHE-500")
    create_mirror(
        che_client,
        source_issue_key="CS-1",
        source_project_key="CS",
        source_issuetype_name="Service Request",
        summary="x",
    )
    assert che_client.create_issue_calls[0]["account_option_id"] == "7"

    scn_client = FakeJiraClient(created_key="SCN-500")
    create_mirror(
        scn_client,
        source_issue_key="SS-1",
        source_project_key="SS",
        source_issuetype_name="Service Request",
        summary="x",
    )
    assert scn_client.create_issue_calls[0]["account_option_id"] == "5"
