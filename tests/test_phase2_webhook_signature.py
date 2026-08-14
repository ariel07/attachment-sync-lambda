"""Phase 2 tests: webhook signature verification approach.

Jira Cloud signs admin/REST-registered webhooks with HMAC-SHA256 over the raw
request body, sent as `X-Hub-Signature: sha256=<hex>` (WebSub format). Atlassian
publishes an official test vector for implementers to self-check against:
https://developer.atlassian.com/cloud/jira/platform/webhooks/#secure-admin-webhooks

This test does not exercise Phase 3's handler (that logic doesn't exist yet).
It exists to lock in, before any handler code is written, that our planned
verification approach (Python's stdlib `hmac` + `hashlib.sha256`) produces the
exact signature Atlassian says it will send - so Phase 3 can implement against
a pre-validated approach instead of discovering a mismatch after the fact.
"""
from __future__ import annotations

import hashlib
import hmac


# Values published verbatim in Atlassian's Jira Cloud webhooks documentation.
JIRA_DOCUMENTED_TEST_VECTOR = {
    "secret": "It's a Secret to Everybody",
    "payload": "Hello World!",
    "expected_signature": (
        "sha256=a4771c39fbe90f317c7824e83ddef3caae9cb3d976c214ace1f2937e133263c9"
    ),
}


def compute_x_hub_signature(secret: str, raw_body: str) -> str:
    """Mirrors the exact verification approach Phase 3's handler will use.

    Kept here (not yet in src/) deliberately: this is a pre-validated reference
    implementation, not the production handler. Phase 3 will move equivalent
    logic into src/handler.py once webhook parsing exists, with this test
    updated to import from there instead of duplicating the logic.
    """
    digest = hmac.new(
        secret.encode("utf-8"),
        msg=raw_body.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()
    return f"sha256={digest}"


def test_hmac_signature_matches_atlassian_documented_test_vector():
    vector = JIRA_DOCUMENTED_TEST_VECTOR
    computed = compute_x_hub_signature(vector["secret"], vector["payload"])
    assert computed == vector["expected_signature"]


def test_signature_comparison_uses_constant_time_compare():
    """Defensive: verification must use hmac.compare_digest (constant-time),
    never `==`, to avoid timing-attack side channels on the comparison itself.
    This test asserts the comparison primitive we intend to use in Phase 3
    behaves as expected - it does not (and cannot yet) assert the handler
    code uses it, since the handler doesn't exist yet."""
    vector = JIRA_DOCUMENTED_TEST_VECTOR
    computed = compute_x_hub_signature(vector["secret"], vector["payload"])
    assert hmac.compare_digest(computed, vector["expected_signature"])


def test_signature_mismatch_is_detected():
    """Sanity check the negative case: a tampered payload must NOT match."""
    vector = JIRA_DOCUMENTED_TEST_VECTOR
    tampered_computed = compute_x_hub_signature(vector["secret"], "Hello World?")
    assert tampered_computed != vector["expected_signature"]
