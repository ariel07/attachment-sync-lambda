"""Phase 8 tests: bidirectional attachment sync.

Context (see Phase 8 handoff, `phase8-bidirectional-attachment-sync-handoff.md`):
sync_new_attachment() previously only worked JSM -> mirror, because it only
ever called find_mirror_issue_key() (inward-only). An attachment added
directly to a mirror issue (e.g. KM-500) would silently no-op:
find_mirror_issue_key() returns None (no inwardIssue on the mirror's own
issuelinks entry) -> {"status": "skipped", "reason": "no_mirror_link"}.

Approach chosen (option (b) from the handoff, "link-direction based"):
sync_new_attachment tries the inward match first (existing JSM -> mirror
path, unchanged behavior), and falls back to the outward match
(find_source_issue_key, Phase 8) if the first attempt returns nothing. No
extra API call either way - issuelinks was already fetched as part of the
first get_issue() call this function makes.

Renamed parameter: `jsm_issue_key` -> `issue_key`, since after this change
the triggering issue is no longer assumed to be the JSM side. Existing
Phase 3 tests (tests/test_phase3_attachment_sync.py) were updated to the
new keyword as part of this rename - behavior for the JSM -> mirror
direction is otherwise unchanged (same fixtures, same assertions).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_fixture(name: str) -> dict:
    with open(FIXTURES / name, encoding="utf-8") as f:
        return json.load(f)


class FakeJiraClient:
    """Same shape as tests/test_phase3_attachment_sync.py's FakeJiraClient -
    duplicated rather than imported, matching this repo's existing
    convention of independent, self-contained test doubles per test file
    (see test_phase7_mirror_create.py's own FakeJiraClient)."""

    def __init__(
        self,
        issue_data: dict,
        download_bytes: bytes = b"fake-bytes",
        target_issue_data: dict | None = None,
    ):
        self._issue_data = issue_data
        self._download_bytes = download_bytes
        self._target_issue_data = (
            target_issue_data if target_issue_data is not None else {"fields": {"attachment": []}}
        )
        self.get_issue_calls: list[dict] = []
        self.download_calls: list[str] = []
        self.upload_calls: list[dict] = []

    def get_issue(self, issue_key: str, fields: list[str]) -> dict[str, Any]:
        self.get_issue_calls.append({"issue_key": issue_key, "fields": fields})
        if issue_key == self._issue_data.get("key"):
            return self._issue_data
        return self._target_issue_data

    def download_attachment(self, content_url: str) -> bytes:
        self.download_calls.append(content_url)
        return self._download_bytes

    def upload_attachment(self, issue_key: str, filename: str, content: bytes, mime_type: str):
        self.upload_calls.append(
            {
                "issue_key": issue_key,
                "filename": filename,
                "content": content,
                "mime_type": mime_type,
            }
        )
        return [{"id": "new-id", "filename": filename}]


def _mirror_side_issue_with_outward_link_and_attachments() -> dict:
    """TMIR-4 (the mirror side), with the SAME real link as
    tsrc_102_issuelinks.json but viewed from its own issuelinks - outward
    populated, inward absent - plus its own attachments (reusing the
    tsrc_102 attachment fixture's shape/content; only the direction of the
    link under test matters here, not which project "really" owns these
    particular attachment fixtures)."""
    attachments = _load_fixture("tsrc_102_attachments.json")["attachment"]
    outward_link = {
        "id": "11789",
        "type": {
            "id": "10012",
            "name": "JSM Mirror",
            "inward": "is mirrored by",
            "outward": "mirrors",
        },
        "outwardIssue": {"key": "TSRC-102", "id": "32540", "fields": {}},
    }
    return {"key": "TMIR-4", "fields": {"issuelinks": [outward_link], "attachment": attachments}}


def test_sync_new_attachment_reverse_direction_synced():
    """Attachment added directly to the mirror issue (TMIR-4) must sync
    back to the JSM source (TSRC-102) - the exact silent-no-op case flagged
    in the Phase 8 handoff."""
    from attachment_sync import sync_new_attachment

    client = FakeJiraClient(_mirror_side_issue_with_outward_link_and_attachments())
    result = sync_new_attachment(client, issue_key="TMIR-4", attachment_id="31711")

    assert result["status"] == "synced"
    assert result["source_issue"] == "TMIR-4"
    assert result["target_issue"] == "TSRC-102"
    assert result["filename"] == "image-20260812-021129.png"

    upload = client.upload_calls[0]
    assert upload["issue_key"] == "TSRC-102"


def test_sync_new_attachment_reverse_direction_marks_outward_direction():
    from attachment_sync import sync_new_attachment

    client = FakeJiraClient(_mirror_side_issue_with_outward_link_and_attachments())
    result = sync_new_attachment(client, issue_key="TMIR-4", attachment_id="31711")

    assert result["direction"] == "outward"


def test_sync_new_attachment_forward_direction_still_marks_inward_direction():
    """Existing JSM -> mirror path (Phase 3) must still report the inward
    match - confirms the fallback to outward only kicks in when inward
    genuinely finds nothing, not unconditionally."""
    from attachment_sync import sync_new_attachment

    links = _load_fixture("tsrc_102_issuelinks.json")["issuelinks"]
    attachments = _load_fixture("tsrc_102_attachments.json")["attachment"]
    issue = {"key": "TSRC-102", "fields": {"issuelinks": links, "attachment": attachments}}
    client = FakeJiraClient(issue)

    result = sync_new_attachment(client, issue_key="TSRC-102", attachment_id="31711")

    assert result["direction"] == "inward"
    assert result["target_issue"] == "TMIR-4"


def test_sync_new_attachment_reverse_direction_dedupe_still_applies():
    """The Phase 4 dedupe guard (filename+size against the target's
    existing attachments) must apply identically in the reverse direction -
    confirms dedupe_check.already_synced has no directional assumption, as
    flagged as an open question in the Phase 8 handoff."""
    from attachment_sync import sync_new_attachment

    target_with_existing = {
        "fields": {"attachment": [{"filename": "image-20260812-021129.png", "size": 39183}]}
    }
    client = FakeJiraClient(
        _mirror_side_issue_with_outward_link_and_attachments(),
        target_issue_data=target_with_existing,
    )
    result = sync_new_attachment(client, issue_key="TMIR-4", attachment_id="31711")

    assert result["status"] == "skipped"
    assert result["reason"] == "already_synced"
    assert client.upload_calls == []


def test_sync_new_attachment_still_skips_when_neither_direction_has_a_link():
    from attachment_sync import sync_new_attachment

    issue = {"key": "TSRC-999", "fields": {"issuelinks": [], "attachment": []}}
    client = FakeJiraClient(issue)
    result = sync_new_attachment(client, issue_key="TSRC-999", attachment_id=None)

    assert result["status"] == "skipped"
    assert result["reason"] == "no_mirror_link"
    assert "direction" not in result
    assert client.upload_calls == []


def test_sync_new_attachment_reverse_direction_projects_reported_correctly():
    from attachment_sync import sync_new_attachment

    client = FakeJiraClient(_mirror_side_issue_with_outward_link_and_attachments())
    result = sync_new_attachment(client, issue_key="TMIR-4", attachment_id="31711")

    assert result["source_project"] == "TMIR"
    assert result["target_project"] == "TSRC"
