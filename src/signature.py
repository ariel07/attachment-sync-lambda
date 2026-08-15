"""Jira webhook HMAC signature verification.

Implements Atlassian's documented WebSub-style signing scheme:
https://developer.atlassian.com/cloud/jira/platform/webhooks/#secure-admin-webhooks

Verified in Phase 2 (tests/test_phase2_webhook_signature.py) against
Atlassian's own published test vector before this module existed. That test
now imports from here instead of duplicating the logic (see note in that
file).
"""

from __future__ import annotations

import hashlib
import hmac


def compute_x_hub_signature(secret: str, raw_body: str) -> str:
    """Compute the expected X-Hub-Signature header value for a given body."""
    digest = hmac.new(
        secret.encode("utf-8"),
        msg=raw_body.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()
    return f"sha256={digest}"


def verify_signature(secret: str, raw_body: str, received_signature: str | None) -> bool:
    """Verify a received X-Hub-Signature header against the expected value.

    Uses constant-time comparison (hmac.compare_digest) to avoid timing
    side-channels on the comparison itself. Returns False (never raises) for
    a missing/malformed header - the caller treats that as "reject", same as
    a mismatch.
    """
    if not received_signature:
        return False
    expected = compute_x_hub_signature(secret, raw_body)
    return hmac.compare_digest(expected, received_signature)
