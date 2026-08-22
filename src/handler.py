"""Attachment Sync Lambda entry point.

Two-layer design:
  - handle_webhook(): all decision logic (signature check, parsing, sync
    orchestration). Pure w.r.t. AWS - takes its dependencies (jira_client,
    webhook_signing_secret) as arguments, so it's fully unit-testable with
    fakes (see tests/test_phase3_handler.py). No boto3/requests calls here.
  - lambda_handler(): the actual AWS entry point. Thin - only wires real
    Secrets Manager + JiraClient and delegates to handle_webhook(). Not unit
    tested (nothing to assert beyond "calls the real SDKs correctly", which
    Phase 7's live testing against TSRC<->TMIR covers better than a mock).

Event shape: API Gateway HttpApi proxy integration - event["body"] is the
raw JSON string, event["headers"] is a dict (case varies by client, so
handle_webhook lowercases keys before lookup - HTTP headers are
case-insensitive per spec).

MIRROR CREATE+LINK (jira:issue_created branch, added below): replaces the
native "Auto-create mirror" automation rule's Create + Branch + Link steps.
That rule's Branch step ("find the issue I just created") was confirmed
(Aug 17-19, live testing against GLO/CHE/SCN/TMIR) to fail 100% of the time
on new blocks, independent of branch-type setting ("recentlycreated" vs
"created") and independent of target project - while identical blocks
created Aug 17 worked. Root cause unconfirmed (no Atlassian status page
incident found for the window), but the fix doesn't depend on knowing the
cause: create_issue() returns the new key directly from the API response,
so there's no search/lookup step to race against at all. See
mirror_create.py for the full mapping/config.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from attachment_sync import (
    MalformedWebhookError,
    changelog_has_attachment_addition,
    extract_attachment_id_from_webhook,
    extract_issue_key_from_webhook,
    is_attachment_deleted_event,
    sync_new_attachment,
)
from jsm_mirror_link import AmbiguousMirrorLinkError
from mirror_create import JSM_MIRROR_LINK_TYPE_ID, create_mirror
from project_scope import is_allowed_project
from signature import verify_signature

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handle_webhook(
    raw_body: str,
    headers: dict[str, str],
    webhook_signing_secret: str,
    jira_client: Any,
    allowed_project_keys: list[str] | None = None,
) -> dict[str, Any]:
    """Core webhook handling logic. Returns an API Gateway HttpApi response dict.

    Status code conventions:
      - 401: signature missing or invalid - reject before parsing anything else.
      - 400: valid signature, but body isn't parseable JSON or is missing a
        field Atlassian's docs confirm should always be present.
      - 200: request understood and handled, whether that means "synced" or
        "skipped" (a skip is an intentional no-op, not a failure - Jira
        should NOT retry a 200).
      - 500: an unexpected/misconfiguration condition (e.g. more than one
        JSM Mirror link on the issue) - Jira WILL retry a 5xx per its
        documented retry policy, which is desirable here since this
        indicates something worth re-attempting after investigation.

    allowed_project_keys (Phase 5, optional): defense-in-depth source-project
    allowlist, checked before any Jira API call. None means "not configured"
    - no restriction, matching pre-Phase-5 behavior. See project_scope.py for
    why this exists alongside (not instead of) the webhook's own JQL filter.
    """
    headers_lower = {k.lower(): v for k, v in headers.items()}
    received_signature = headers_lower.get("x-hub-signature")

    if not verify_signature(webhook_signing_secret, raw_body, received_signature):
        logger.warning("Rejected webhook: missing or invalid X-Hub-Signature")
        return {"statusCode": 401, "body": "Invalid signature"}

    try:
        webhook_body = json.loads(raw_body)
    except json.JSONDecodeError:
        logger.error("Rejected webhook: body is not valid JSON. Raw body: %s", raw_body)
        return {"statusCode": 400, "body": "Invalid JSON body"}

    # PHASE 6 TEMPORARY CAPTURE PATH - do not extend, do not remove until a
    # real attachment_deleted payload has been captured and Phase 6 core
    # logic is built against it.
    #
    # Runs BEFORE extract_issue_key_from_webhook deliberately: the sibling
    # attachment_created event was confirmed (Phase 2/3, real captured
    # payload) to sometimes carry NO issue reference at all, so this must
    # not depend on issue.key being present. This branch only logs and
    # returns 200 ("captured", not "synced"/"skipped") - it must never call
    # into jira_client or any sync/delete logic. See
    # docs/phase6-attachment-delete-sync.md and the changelog
    # investigation that ruled out jira:issue_updated for detecting
    # deletions (TSRC-102's real changelog, checked live, recorded zero
    # removal entries for a confirmed real deletion).
    if is_attachment_deleted_event(webhook_body):
        logger.info(
            "ATTACHMENT_DELETED_CAPTURE_ONLY payload (FULL BODY FOR ANALYSIS): %s",
            json.dumps(webhook_body),
        )
        return {
            "statusCode": 200,
            "body": json.dumps({"status": "captured", "reason": "attachment_deleted_capture_only"}),
        }

    # MIRROR CREATE+LINK PATH - handles jira:issue_created events, replacing
    # the native "Auto-create mirror" rule's Create + Branch + Link steps
    # (see module docstring for why). Runs BEFORE
    # extract_issue_key_from_webhook() deliberately: issue_created payloads
    # have a different shape than issue_updated ones (no changelog, for
    # instance) and shouldn't be run through attachment-focused extraction
    # logic at all.
    if webhook_body.get("webhookEvent") == "jira:issue_created":
        try:
            issue = webhook_body["issue"]
            issue_key = issue["key"]
            project_key = issue["fields"]["project"]["key"]
            issuetype_name = issue["fields"]["issuetype"]["name"]
            summary = issue["fields"]["summary"]
            description = issue["fields"].get("description") or ""
        except KeyError as exc:
            logger.error(
                "Rejected issue_created webhook: missing field %s | FULL BODY: %s",
                exc,
                json.dumps(webhook_body),
            )
            return {"statusCode": 400, "body": f"Malformed issue_created payload: missing {exc}"}

        # Idempotency guard: the webhook has a confirmed double-fire behavior
        # (seen in CloudWatch for TSRC-109/TSRC-110, each fired twice within
        # the same second). Cheapest guard available without new infra:
        # check if this issue already has a JSM Mirror link before creating
        # another one. Accepts one extra read call per event as the cost of
        # staying infra-light; revisit with a real dedupe table
        # (dedupe_check.py already has the DynamoDB pattern) if this scales
        # past the current handful of client pairs.
        existing = jira_client.get_issue(issue_key, fields=["issuelinks"])
        already_linked = any(
            link.get("type", {}).get("id") == JSM_MIRROR_LINK_TYPE_ID
            for link in existing.get("fields", {}).get("issuelinks", [])
        )
        if already_linked:
            logger.info("Skipping %s: already has a JSM Mirror link", issue_key)
            return {
                "statusCode": 200,
                "body": json.dumps(
                    {"status": "skipped", "reason": "already_linked", "source_issue": issue_key}
                ),
            }

        new_key = create_mirror(
            jira_client,
            source_issue_key=issue_key,
            source_project_key=project_key,
            source_issuetype_name=issuetype_name,
            summary=summary,
            description=description,
        )

        if new_key is None:
            logger.info("Skipping %s: project not in MIRROR_MAP", issue_key)
            return {
                "statusCode": 200,
                "body": json.dumps(
                    {
                        "status": "skipped",
                        "reason": "project_not_mirrored",
                        "source_issue": issue_key,
                    }
                ),
            }

        logger.info("Created mirror %s for %s", new_key, issue_key)
        return {
            "statusCode": 200,
            "body": json.dumps(
                {"status": "created", "source_issue": issue_key, "mirror_issue": new_key}
            ),
        }

    # TEMPORARY diagnostic logging (Phase 2/3 payload-shape gap): log the full
    # parsed body whenever we're about to fail on it, so a real captured
    # payload can be pulled from CloudWatch and used to fix extraction logic
    # with verified data instead of another guess. Remove once
    # tests/test_phase2_payload_schema.py's skipped test is un-skipped against
    # a real captured fixture.
    try:
        issue_key = extract_issue_key_from_webhook(webhook_body)
    except MalformedWebhookError as exc:
        logger.error(
            "Rejected webhook: %s | FULL PARSED BODY FOR DIAGNOSIS: %s",
            exc,
            json.dumps(webhook_body),
        )
        return {"statusCode": 400, "body": str(exc)}

    if allowed_project_keys is not None and not is_allowed_project(issue_key, allowed_project_keys):
        # Should not happen in normal operation - the webhook's own JQL
        # filter is the primary scope control. Logged at WARNING (not INFO,
        # unlike the routine not_attachment_change skip below) because
        # hitting this path means the JQL filter and this allowlist have
        # drifted out of sync and are worth investigating.
        logger.warning(
            "Rejected %s: project not in ALLOWED_PROJECT_KEYS allowlist",
            issue_key,
        )
        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "status": "skipped",
                    "reason": "project_not_allowlisted",
                    "source_issue": issue_key,
                }
            ),
        }

    attachment_id = extract_attachment_id_from_webhook(webhook_body)

    if not changelog_has_attachment_addition(webhook_body):
        # jira:issue_updated fires for EVERY field change on matching issues,
        # not just attachments. This is expected and frequent - log at INFO,
        # not ERROR, and skip cheaply before any Jira API call.
        logger.info("Skipping %s: update did not add an attachment", issue_key)
        return {
            "statusCode": 200,
            "body": json.dumps(
                {"status": "skipped", "reason": "not_attachment_change", "source_issue": issue_key}
            ),
        }

    try:
        result = sync_new_attachment(jira_client, issue_key=issue_key, attachment_id=attachment_id)
    except AmbiguousMirrorLinkError as exc:
        logger.error("Misconfiguration on %s: %s", issue_key, exc)
        return {"statusCode": 500, "body": f"Misconfiguration: {exc}"}

    logger.info("Sync result for %s: %s", issue_key, json.dumps(result))
    return {"statusCode": 200, "body": json.dumps(result)}


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """AWS Lambda entry point. Wires real Secrets Manager + JiraClient."""
    from secrets import get_secret_json

    from jira_client import JiraClient
    from project_scope import parse_allowed_project_keys

    raw_body = event.get("body") or ""
    headers = event.get("headers") or {}

    webhook_signing_secret = get_secret_json(os.environ["JIRA_WEBHOOK_SIGNING_SECRET_ARN"])[
        "secret"
    ]
    service_account = get_secret_json(os.environ["JIRA_SERVICE_ACCOUNT_SECRET_ARN"])

    jira_client = JiraClient(
        base_url=os.environ["JIRA_BASE_URL"],
        email=service_account["email"],
        api_token=service_account["api_token"],
    )

    # ALLOWED_PROJECT_KEYS is optional: unset means no allowlist restriction
    # (pre-Phase-5 behavior). Set it when onboarding additional client pairs
    # (Phase 5) - see docs/phase5-scaling-to-additional-pairs.md.
    raw_allowlist = os.environ.get("ALLOWED_PROJECT_KEYS")
    allowed_project_keys = parse_allowed_project_keys(raw_allowlist) if raw_allowlist else None

    return handle_webhook(
        raw_body, headers, webhook_signing_secret, jira_client, allowed_project_keys
    )
