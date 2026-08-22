"""Phase 8 tests: reverse-direction (mirror -> source) link resolution.

Context (see Phase 8 handoff): find_mirror_issue_key() only ever matches the
INWARD side of a "JSM Mirror" link, which is correct when called from the
JSM ticket's perspective but returns None when called from the mirror
(Jira Software) side - silently dropping attachments added directly to a
mirror issue. This file exercises the new find_source_issue_key(), which is
the mirror-image counterpart: it matches the OUTWARD side, for use when the
triggering issue is the mirror, not the JSM source.

Written before src/jsm_mirror_link.py's find_source_issue_key exists - TDD.
Reuses the same real captured link shape as
tests/test_phase3_jsm_mirror_link.py (tsrc_102_issuelinks.json), just read
from the other side of the same link, since the outward/inward fields are
two views of one real link object, not separately-fetched data.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_fixture(name: str) -> dict:
    with open(FIXTURES / name, encoding="utf-8") as f:
        return json.load(f)


def test_find_source_issue_key_returns_real_linked_key():
    """Mirror image of test_find_mirror_issue_key_returns_real_linked_key:
    same real link (TSRC-102 <-> TMIR-4), but viewed from TMIR-4's own
    issuelinks, where the JSM Mirror link's OUTWARD side is populated with
    the source JSM issue instead of INWARD."""
    from jsm_mirror_link import find_source_issue_key

    link = {
        "id": "11789",
        "type": {
            "id": "10012",
            "name": "JSM Mirror",
            "inward": "is mirrored by",
            "outward": "mirrors",
        },
        "outwardIssue": {"key": "TSRC-102", "id": "32540", "fields": {}},
        # deliberately no "inwardIssue" key - this is TMIR-4's own entry
    }
    assert find_source_issue_key([link]) == "TSRC-102"


def test_find_source_issue_key_returns_none_when_no_links():
    from jsm_mirror_link import find_source_issue_key

    assert find_source_issue_key([]) is None


def test_find_source_issue_key_ignores_other_link_types():
    from jsm_mirror_link import find_source_issue_key

    unrelated_link = {
        "id": "99999",
        "type": {"name": "Blocks", "inward": "is blocked by", "outward": "blocks"},
        "outwardIssue": {"key": "TSRC-1", "id": "1", "fields": {}},
    }
    assert find_source_issue_key([unrelated_link]) is None


def test_find_source_issue_key_ignores_inward_direction():
    """A 'JSM Mirror' link where THIS issue is the inward side (i.e. this
    issue is actually the JSM source, not the mirror) must not be mistaken
    for an outward source link - mirror image of
    test_find_mirror_issue_key_ignores_outward_direction."""
    from jsm_mirror_link import find_source_issue_key

    inward_only_link = {
        "id": "22222",
        "type": {"name": "JSM Mirror", "inward": "is mirrored by", "outward": "mirrors"},
        "inwardIssue": {"key": "TMIR-999", "id": "999", "fields": {}},
        # deliberately no "outwardIssue" key
    }
    assert find_source_issue_key([inward_only_link]) is None


def test_find_source_issue_key_raises_on_multiple_outward_links():
    """Mirror image of test_find_mirror_issue_key_raises_on_multiple_mirror_links -
    same one-to-one architecture assumption, checked from the other side."""
    from jsm_mirror_link import AmbiguousMirrorLinkError, find_source_issue_key

    duplicated = [
        {
            "id": "11789",
            "type": {"name": "JSM Mirror", "inward": "is mirrored by", "outward": "mirrors"},
            "outwardIssue": {"key": "TSRC-102", "id": "32540", "fields": {}},
        },
        {
            "id": "11790",
            "type": {"name": "JSM Mirror", "inward": "is mirrored by", "outward": "mirrors"},
            "outwardIssue": {"key": "TSRC-999", "id": "999", "fields": {}},
        },
    ]
    with pytest.raises(AmbiguousMirrorLinkError):
        find_source_issue_key(duplicated)


def test_find_source_issue_key_custom_link_type_name():
    from jsm_mirror_link import find_source_issue_key

    link = {
        "id": "1",
        "type": {"name": "Custom Mirror Name", "inward": "x", "outward": "y"},
        "outwardIssue": {"key": "ABC-1", "id": "1", "fields": {}},
    }
    assert find_source_issue_key([link], link_type_name="Custom Mirror Name") == "ABC-1"
