"""JSM Mirror link resolution.

Given the `issuelinks` field from a Jira issue (as returned by GET
/rest/api/3/issue/{key}?fields=issuelinks), find the key of the linked
mirror issue - if one exists.

Pure function, no network I/O, no AWS dependency - deliberately kept that
way for fast, deterministic unit testing.
"""

from __future__ import annotations

from typing import Any


class AmbiguousMirrorLinkError(Exception):
    """Raised when more than one JSM Mirror link (inward direction) is found
    on a single issue. The architecture is documented as one-to-one; two
    matches means something is misconfigured, and silently picking one risks
    syncing an attachment to the wrong project pair."""


def find_mirror_issue_key(
    issuelinks: list[dict[str, Any]],
    link_type_name: str = "JSM Mirror",
) -> str | None:
    """Return the key of the mirrored issue, or None if no mirror link exists.

    Only considers the INWARD direction (i.e. this function assumes it is
    being called with the issuelinks of a JSM ticket, which is "mirrored by"
    a Jira Software issue - inward on the JSM Mirror link type per the
    project's documented convention). A link where this issue is the
    OUTWARD side (i.e. this issue "mirrors" something) is not a match here;
    call this only from the JSM-ticket side of the pair.

    Raises AmbiguousMirrorLinkError if more than one matching inward link
    is found.
    """
    matches: list[str] = []
    for link in issuelinks:
        link_type = link.get("type", {})
        if link_type.get("name") != link_type_name:
            continue
        inward_issue = link.get("inwardIssue")
        if inward_issue is None:
            # This issue is the OUTWARD side of the link (or the link is
            # malformed) - not a match for this function's contract.
            continue
        key = inward_issue.get("key")
        if key:
            matches.append(key)

    if len(matches) > 1:
        raise AmbiguousMirrorLinkError(
            f"Found {len(matches)} '{link_type_name}' inward links (expected 0 or 1): {matches}"
        )
    return matches[0] if matches else None


def find_source_issue_key(
    issuelinks: list[dict[str, Any]],
    link_type_name: str = "JSM Mirror",
) -> str | None:
    """Return the key of the source JSM issue, or None if no mirror link exists.

    Mirror-image counterpart to find_mirror_issue_key(): only considers the
    OUTWARD direction (i.e. this function assumes it is being called with
    the issuelinks of a Jira Software mirror issue, which "mirrors" a JSM
    ticket - outward on the JSM Mirror link type per the project's
    documented convention). A link where this issue is the INWARD side
    (i.e. this issue "is mirrored by" something) is not a match here; call
    this only from the mirror-issue side of the pair.

    Added in Phase 8 to support bidirectional attachment sync: an
    attachment added directly to a mirror issue needs this to find its way
    back to the JSM source (see attachment_sync.sync_new_attachment, which
    tries find_mirror_issue_key first and falls back to this one).

    Raises AmbiguousMirrorLinkError if more than one matching outward link
    is found - same one-to-one architecture assumption as
    find_mirror_issue_key.
    """
    matches: list[str] = []
    for link in issuelinks:
        link_type = link.get("type", {})
        if link_type.get("name") != link_type_name:
            continue
        outward_issue = link.get("outwardIssue")
        if outward_issue is None:
            # This issue is the INWARD side of the link (or the link is
            # malformed) - not a match for this function's contract.
            continue
        key = outward_issue.get("key")
        if key:
            matches.append(key)

    if len(matches) > 1:
        raise AmbiguousMirrorLinkError(
            f"Found {len(matches)} '{link_type_name}' outward links (expected 0 or 1): {matches}"
        )
    return matches[0] if matches else None
