"""Attachment Sync Lambda entry point.

PHASE 1 STUB: this file exists only so the SAM template (infra/template.yaml)
has a valid CodeUri to reference and can be linted/deployed independently of
business logic. Webhook parsing, link verification, attachment download, and
attachment upload are implemented in Phase 3 per the phased plan.

Do not add logic here yet - Phase 3 will introduce this under TDD (tests
written first in tests/, against documented Jira REST API v3 behavior).
"""
from __future__ import annotations

from typing import Any


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Placeholder handler. Returns 501 until Phase 3 implements sync logic."""
    return {
        "statusCode": 501,
        "body": "Not implemented: attachment sync logic lands in Phase 3.",
    }
