"""Phase 3 tests: JSM Mirror link resolution.

Written before src/jsm_mirror_link.py exists - TDD. Uses a real issuelinks
payload captured live from icxeed.atlassian.net (TSRC-102) via Atlassian Rovo,
not an invented fixture. See tests/fixtures/tsrc_102_issuelinks.json for
provenance.

Confirmed live (not assumed): on a JSM ticket, the mirrored Jira Software
issue appears under issuelinks[].inwardIssue, for a link of type.name ==
"JSM Mirror". This matches the project's documented link-type convention
(inward: "is mirrored by", outward: "mirrors") - see userMemories.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_fixture(name: str) -> dict:
    with open(FIXTURES / name, encoding="utf-8") as f:
        return json.load(f)


def test_find_mirror_issue_key_returns_real_linked_key():
    from jsm_mirror_link import find_mirror_issue_key

    fixture = _load_fixture("tsrc_102_issuelinks.json")
    result = find_mirror_issue_key(fixture["issuelinks"])
    assert result == "TMIR-4"


def test_find_mirror_issue_key_returns_none_when_no_links():
    from jsm_mirror_link import find_mirror_issue_key

    assert find_mirror_issue_key([]) is None


def test_find_mirror_issue_key_ignores_other_link_types():
    from jsm_mirror_link import find_mirror_issue_key

    unrelated_link = {
        "id": "99999",
        "type": {"name": "Blocks", "inward": "is blocked by", "outward": "blocks"},
        "inwardIssue": {"key": "TSRC-1", "id": "1", "fields": {}},
    }
    result = find_mirror_issue_key([unrelated_link])
    assert result is None


def test_find_mirror_issue_key_ignores_outward_direction():
    """A 'JSM Mirror' link where THIS issue is the outward side (i.e. this
    function is being called on a Jira Software issue, not a JSM ticket)
    must not be mistaken for an inward mirror - the caller is responsible
    for knowing which perspective it's checking from. This guards against
    the exact bug documented in project memory: link-type direction must
    match the perspective of the current execution context."""
    from jsm_mirror_link import find_mirror_issue_key

    outward_only_link = {
        "id": "22222",
        "type": {"name": "JSM Mirror", "inward": "is mirrored by", "outward": "mirrors"},
        "outwardIssue": {"key": "TSRC-999", "id": "999", "fields": {}},
        # deliberately no "inwardIssue" key
    }
    result = find_mirror_issue_key([outward_only_link])
    assert result is None


def test_find_mirror_issue_key_raises_on_multiple_mirror_links():
    """Defensive: the architecture is documented as one-to-one (each JSM
    project pairs with exactly one Kanban project). Two JSM Mirror links on
    one issue means something is misconfigured - fail loudly rather than
    silently picking one and syncing to the wrong place."""
    from jsm_mirror_link import AmbiguousMirrorLinkError, find_mirror_issue_key

    fixture = _load_fixture("tsrc_102_issuelinks.json")
    duplicated = fixture["issuelinks"] + [
        {
            "id": "11790",
            "type": {"name": "JSM Mirror", "inward": "is mirrored by", "outward": "mirrors"},
            "inwardIssue": {"key": "TMIR-999", "id": "999", "fields": {}},
        }
    ]
    with pytest.raises(AmbiguousMirrorLinkError):
        find_mirror_issue_key(duplicated)


def test_find_mirror_issue_key_custom_link_type_name():
    """The link type name is a template default, not a hardcoded constant -
    must be overridable in case a future client pair uses a different name."""
    from jsm_mirror_link import find_mirror_issue_key

    link = {
        "id": "1",
        "type": {"name": "Custom Mirror Name", "inward": "x", "outward": "y"},
        "inwardIssue": {"key": "ABC-1", "id": "1", "fields": {}},
    }
    assert (
        find_mirror_issue_key(
            link if isinstance(link, list) else [link], link_type_name="Custom Mirror Name"
        )
        == "ABC-1"
    )
