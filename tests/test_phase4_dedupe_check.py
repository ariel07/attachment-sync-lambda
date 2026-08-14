"""
Tests for dedupe_check.py (simplified Phase 4).

Framework: pytest. No AWS mocking needed -- this module makes no AWS
calls; it depends only on the injected AttachmentLookup Protocol.
"""

from __future__ import annotations

import pytest

from dedupe_check import already_synced


class FakeAttachmentLookup:
    """Test double -- avoids depending on the unbuilt Phase 3 Jira client."""

    def __init__(self, existing: list[tuple[str, int]]) -> None:
        self._existing = existing

    def get_target_attachments(self, issue_key: str) -> list[tuple[str, int]]:
        return self._existing


def test_returns_true_when_filename_and_size_match() -> None:
    lookup = FakeAttachmentLookup(existing=[("screenshot.png", 20480)])
    assert already_synced("JJST-4", "screenshot.png", 20480, lookup) is True


def test_returns_false_when_filename_differs() -> None:
    lookup = FakeAttachmentLookup(existing=[("screenshot.png", 20480)])
    assert already_synced("JJST-4", "different.png", 20480, lookup) is False


def test_returns_false_when_size_differs() -> None:
    lookup = FakeAttachmentLookup(existing=[("screenshot.png", 20480)])
    assert already_synced("JJST-4", "screenshot.png", 99999, lookup) is False


def test_returns_false_when_target_has_no_attachments() -> None:
    lookup = FakeAttachmentLookup(existing=[])
    assert already_synced("JJST-4", "screenshot.png", 20480, lookup) is False


def test_finds_match_among_several_existing_attachments() -> None:
    lookup = FakeAttachmentLookup(
        existing=[("a.txt", 10), ("screenshot.png", 20480), ("b.txt", 30)]
    )
    assert already_synced("JJST-4", "screenshot.png", 20480, lookup) is True


@pytest.mark.parametrize(
    ("issue_key", "filename", "size"),
    [
        ("", "screenshot.png", 20480),
        ("JJST-4", "", 20480),
        ("JJST-4", "screenshot.png", -1),
    ],
)
def test_rejects_invalid_input(issue_key: str, filename: str, size: int) -> None:
    lookup = FakeAttachmentLookup(existing=[])
    with pytest.raises(ValueError):
        already_synced(issue_key, filename, size, lookup)
