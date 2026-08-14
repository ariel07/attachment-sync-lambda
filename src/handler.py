"""Attachment Sync Lambda entry point.

Two-layer design:
  - handle_webhook(): all decision logic (signature check, parsing, sync
    orchestration). Pure w.r.t. AWS - takes its dependencies (jira_client,
    webhook_signing_secret) as arguments, so it's fully unit-testable with
    fakes (see tests/test_phase3_handler.py). No boto3/requests calls here.
  - lambda_handler(): the actual AWS entry point. Thin - only wires real
    Secrets Manager + JiraClient and delegates to handle_webhook(). Not unit
    tested (nothing to assert beyond "calls the real SDKs correctly", which
    Phase 7's live testing against JTT<->JJST covers better than a mock).

Event shape: API Gateway HttpApi proxy integration - event["body"] is the
raw JSON string, event["headers"] is a dict (case varies by client, so
handle_webhook lowercases keys before lookup - HTTP headers are
case-insensitive per spec).
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from attachment_sync import (
    MalformedWebhookError,
    extract_attachment_id_from_webhook,
    extract_issue_key_from_webhook,
    sync_new_attachment,
)
from jsm_mirror_link import AmbiguousMirrorLinkError
from signature import verify_signature

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handle_webhook(
    raw_body: str,
    headers: dict[str, str],
    webhook_signing_secret: str,
    jira_client: Any,
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
    """
    headers_lower = {k.lower(): v for k, v in headers.items()}
    received_signature = headers_lower.get("x-hub-signature")

    if not verify_signature(webhook_signing_secret, raw_body, received_signature):
        logger.warning("Rejected webhook: missing or invalid X-Hub-Signature")
        return {"statusCode": 401, "body": "Invalid signature"}

    try:
        webhook_body = json.loads(raw_body)
    except json.JSONDecodeError:
        logger.error("Rejected webhook: body is not valid JSON")
        return {"statusCode": 400, "body": "Invalid JSON body"}

    try:
        issue_key = extract_issue_key_from_webhook(webhook_body)
    except MalformedWebhookError as exc:
        logger.error("Rejected webhook: %s", exc)
        return {"statusCode": 400, "body": str(exc)}

    attachment_id = extract_attachment_id_from_webhook(webhook_body)

    try:
        result = sync_new_attachment(jira_client, jsm_issue_key=issue_key, attachment_id=attachment_id)
    except AmbiguousMirrorLinkError as exc:
        logger.error("Misconfiguration on %s: %s", issue_key, exc)
        return {"statusCode": 500, "body": f"Misconfiguration: {exc}"}

    logger.info("Sync result for %s: %s", issue_key, json.dumps(result))
    return {"statusCode": 200, "body": json.dumps(result)}


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """AWS Lambda entry point. Wires real Secrets Manager + JiraClient."""
    from jira_client import JiraClient
    from secrets import get_secret_json

    raw_body = event.get("body") or ""
    headers = event.get("headers") or {}

    webhook_signing_secret = get_secret_json(os.environ["JIRA_WEBHOOK_SIGNING_SECRET_ARN"])["secret"]
    service_account = get_secret_json(os.environ["JIRA_SERVICE_ACCOUNT_SECRET_ARN"])

    jira_client = JiraClient(
        base_url=os.environ["JIRA_BASE_URL"],
        email=service_account["email"],
        api_token=service_account["api_token"],
    )

    return handle_webhook(raw_body, headers, webhook_signing_secret, jira_client)
