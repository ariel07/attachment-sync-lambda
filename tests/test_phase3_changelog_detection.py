"""Tests for changelog_has_attachment_addition().

Design pivot, captured here for the record: the real, live-captured
attachment_created payload (from icxeed.atlassian.net, JTT-102, attachment
id 31804) has NO issue reference at all - confirmed empirically, not
assumed. Cross-checked against official Attachment resource schema
(GET /rest/api/3/attachment/{id}), which also has no issue/container field.
This is a genuine, structural limitation of that event type - not fixable
by parsing harder.

The original handoff doc's choice of jira:issue_updated (not
attachment_created) was therefore correct, and Phase 2's decision to switch
to attachment_created was a mistake made without this information. This
module implements the fix: jira:issue_updated DOES include issue.key
(confirmed in Atlassian's own payload example) plus a changelog, from which
an attachment addition can be detected.

NOTE on confidence level: Atlassian's docs confirm changelog.items exists
and give an example for summary/issuetype changes, but do NOT give a
literal example of an Attachment-field changelog entry. The convention used
below (field == "Attachment", from/fromString == None means "added" not
"removed") is well-established, widely-observed Jira behavior, not a
literally-documented example - flagged here rather than presented as
docs-certain. Worst case if this heuristic is ever wrong: a missed sync
(safe) or a redundant one (harmless, no worse than the existing fallback
behavior) - never a wrong sync to the wrong issue.
"""

from __future__ import annotations


def test_detects_attachment_addition():
    from attachment_sync import changelog_has_attachment_addition

    webhook_body = {
        "changelog": {
            "items": [
                {
                    "field": "Attachment",
                    "fieldtype": "jira",
                    "from": None,
                    "fromString": None,
                    "to": "31804",
                    "toString": "image-20260814-090920.png",
                }
            ],
            "id": 12345,
        }
    }
    assert changelog_has_attachment_addition(webhook_body) is True


def test_ignores_attachment_removal():
    from attachment_sync import changelog_has_attachment_addition

    webhook_body = {
        "changelog": {
            "items": [
                {
                    "field": "Attachment",
                    "fieldtype": "jira",
                    "from": "31804",
                    "fromString": "image-20260814-090920.png",
                    "to": None,
                    "toString": None,
                }
            ]
        }
    }
    assert changelog_has_attachment_addition(webhook_body) is False


def test_ignores_unrelated_field_changes():
    from attachment_sync import changelog_has_attachment_addition

    webhook_body = {
        "changelog": {
            "items": [
                {
                    "field": "summary",
                    "fromString": "Old",
                    "toString": "New",
                    "from": "x",
                    "to": "y",
                },
                {
                    "field": "status",
                    "fromString": "Open",
                    "toString": "In Progress",
                    "from": "1",
                    "to": "2",
                },
            ]
        }
    }
    assert changelog_has_attachment_addition(webhook_body) is False


def test_handles_missing_changelog_gracefully():
    """Bulk operations and some event shapes may omit changelog entirely -
    must not raise, must default to False (skip, don't guess)."""
    from attachment_sync import changelog_has_attachment_addition

    assert changelog_has_attachment_addition({"webhookEvent": "jira:issue_updated"}) is False


def test_handles_empty_items_list():
    from attachment_sync import changelog_has_attachment_addition

    assert changelog_has_attachment_addition({"changelog": {"items": []}}) is False


def test_detects_addition_among_multiple_simultaneous_field_changes():
    """A single issue update can change multiple fields at once (e.g.
    someone adds an attachment AND changes status in one action) - must
    find the Attachment item even when it's not first in the list."""
    from attachment_sync import changelog_has_attachment_addition

    webhook_body = {
        "changelog": {
            "items": [
                {
                    "field": "status",
                    "from": "1",
                    "to": "2",
                    "fromString": "Open",
                    "toString": "In Progress",
                },
                {
                    "field": "Attachment",
                    "from": None,
                    "to": "99999",
                    "fromString": None,
                    "toString": "file.pdf",
                },
            ]
        }
    }
    assert changelog_has_attachment_addition(webhook_body) is True
