"""Attachment sync orchestration.

Ties together jsm_mirror_link.find_mirror_issue_key and JiraClient to
perform the actual sync: given a JSM issue key (and optionally an attachment
id from the webhook), find the mirrored issue, resolve which attachment to
sync, download it, and re-upload it to the mirror.

See module docstring in tests/test_phase3_attachment_sync.py for the design
rationale on why this does NOT trust an unverified webhook attachment shape.
"""
from __future__ import annotations

from typing import Any, Protocol

from jsm_mirror_link import find_mirror_issue_key, AmbiguousMirrorLinkError


class MalformedWebhookError(Exception):
    """Raised when the webhook body is missing a field that Atlassian's docs
    confirm is always present for this event type. Indicates either a
    genuinely malformed request or a misunderstanding of the payload shape -
    either way, fail loudly rather than guessing."""


class _JiraClientProtocol(Protocol):
    def get_issue(self, issue_key: str, fields: list[str]) -> dict[str, Any]: ...
    def download_attachment(self, content_url: str) -> bytes: ...
    def upload_attachment(self, issue_key: str, filename: str, content: bytes, mime_type: str) -> Any: ...


def extract_issue_key_from_webhook(webhook_body: dict[str, Any]) -> str:
    """Extract the JSM issue key from a webhook payload.

    Only relies on `issue.key`, which Atlassian's docs confirm is present
    for issue-related webhook events (the "Issue shape" table in
    https://developer.atlassian.com/cloud/jira/platform/webhooks/).
    """
    issue = webhook_body.get("issue")
    if not issue or "key" not in issue:
        raise MalformedWebhookError(
            "Webhook body missing 'issue.key' - expected for all "
            "issue-related events per Atlassian's documented webhook shape."
        )
    return issue["key"]


def extract_attachment_id_from_webhook(webhook_body: dict[str, Any]) -> str | None:
    """Best-effort: return webhook_body['attachment']['id'] if present.

    This field's presence/shape is UNCONFIRMED (see Phase 2's skipped test,
    tests/test_phase2_payload_schema.py::test_attachment_field_shape_TODO_needs_live_capture).
    Returns None rather than raising when absent - the caller falls back to
    "most recently created attachment" in that case. Once a real payload is
    captured, if it confirms this field, no code change is needed here; if
    it reveals a different field name/path, update this function only.
    """
    attachment = webhook_body.get("attachment")
    if isinstance(attachment, dict):
        return attachment.get("id")
    return None


def sync_new_attachment(
    jira_client: _JiraClientProtocol,
    jsm_issue_key: str,
    attachment_id: str | None,
    link_type_name: str = "JSM Mirror",
) -> dict[str, Any]:
    """Sync one attachment from a JSM issue to its mirrored Jira Software issue.

    Returns a result dict with at minimum a "status" key:
      - "synced": sync succeeded; result includes source_issue, target_issue,
        attachment_id, filename, and fallback_used (bool).
      - "skipped": sync intentionally not performed; result includes "reason"
        (one of: "no_mirror_link", "no_attachments", "attachment_not_found").

    Never raises on expected "nothing to do" conditions - those are skips,
    not errors. Does raise AmbiguousMirrorLinkError if the issue is
    misconfigured with multiple mirror links (see jsm_mirror_link.py).
    """
    issue = jira_client.get_issue(jsm_issue_key, fields=["issuelinks", "attachment"])
    fields = issue.get("fields", {})

    mirror_key = find_mirror_issue_key(fields.get("issuelinks", []), link_type_name=link_type_name)
    if mirror_key is None:
        return {"status": "skipped", "reason": "no_mirror_link", "source_issue": jsm_issue_key}

    attachments = fields.get("attachment", [])
    if not attachments:
        return {
            "status": "skipped", "reason": "no_attachments",
            "source_issue": jsm_issue_key, "target_issue": mirror_key,
        }

    fallback_used = False
    if attachment_id is not None:
        target_attachment = next((a for a in attachments if a.get("id") == attachment_id), None)
        if target_attachment is None:
            return {
                "status": "skipped", "reason": "attachment_not_found",
                "source_issue": jsm_issue_key, "target_issue": mirror_key,
                "attachment_id": attachment_id,
            }
    else:
        # Fallback: most recently created attachment. ISO 8601 timestamps
        # with explicit offsets (as Jira returns them) sort correctly as
        # strings for this purpose since the offset format is consistent.
        target_attachment = max(attachments, key=lambda a: a.get("created", ""))
        fallback_used = True

    content_bytes = jira_client.download_attachment(target_attachment["content"])
    jira_client.upload_attachment(
        issue_key=mirror_key,
        filename=target_attachment["filename"],
        content=content_bytes,
        mime_type=target_attachment.get("mimeType", "application/octet-stream"),
    )

    return {
        "status": "synced",
        "source_issue": jsm_issue_key,
        "target_issue": mirror_key,
        "attachment_id": target_attachment["id"],
        "filename": target_attachment["filename"],
        "fallback_used": fallback_used,
    }
