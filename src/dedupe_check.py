"""
Phase 4 (simplified) -- Loop Guard / Idempotency.

Scope decision made in this conversation: use a filename+size check
against the target issue's existing attachments as the ONLY dedupe
guard. No DynamoDB table, no new AWS resource, no IaC to maintain.

Trade-off accepted explicitly, not hidden: this is a live REST lookup,
not an atomic compare-and-set. Two genuinely concurrent webhook
deliveries for the same attachment could theoretically both pass the
check before either upload completes. At support-ticket volume for a
single client pair, that race is judged an acceptable risk versus
provisioning and maintaining a DynamoDB table. Revisit with the
DynamoDB-backed version (already built, available if needed) if
volume or criticality grows.

Why this guard is still needed at all, not optional: Jira Cloud's own
webhook documentation confirms retries happen and can result in more
than one delivery for the same event
(https://developer.atlassian.com/cloud/jira/platform/webhooks/) --
"if a webhook is sent to its callback URL but fails, Jira Cloud will
attempt to resend it up to five times... this means that some
webhooks might be delivered more than once." Without this check, each
retried delivery re-uploads the same attachment.
"""

from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class AttachmentLookup(Protocol):
    """
    Minimal interface for fetching a target issue's existing
    attachments.

    Concrete implementation belongs to the Phase 3 Jira client (not
    supplied as source material for this task) -- it would call
    GET /rest/api/3/issue/{issueKey}?fields=attachment and return the
    filename/size of each entry. This Protocol lets dedupe logic be
    built and tested (TDD) without inventing that client's code.
    """

    def get_target_attachments(self, issue_key: str) -> list[tuple[str, int]]:
        """Return (filename, size_bytes) pairs already on the target issue."""
        ...


def already_synced(
    target_issue_key: str,
    filename: str,
    size_bytes: int,
    lookup: AttachmentLookup,
) -> bool:
    """
    Returns True if an attachment with matching filename and size
    already exists on the target issue -- i.e. this webhook delivery
    is a duplicate and the upload step should be skipped.
    """
    if not target_issue_key:
        raise ValueError("target_issue_key must be a non-empty string")
    if not filename:
        raise ValueError("filename must be a non-empty string")
    if size_bytes < 0:
        raise ValueError("size_bytes must be non-negative")

    for existing_filename, existing_size in lookup.get_target_attachments(target_issue_key):
        if existing_filename == filename and existing_size == size_bytes:
            logger.info(
                "dedupe_check.duplicate_skipped",
                extra={"target_issue_key": target_issue_key, "attachment_filename": filename},
            )
            return True
    return False
