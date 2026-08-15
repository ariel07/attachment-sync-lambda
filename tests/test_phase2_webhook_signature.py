"""Phase 2 tests: webhook signature verification approach.

Jira Cloud signs admin/REST-registered webhooks with HMAC-SHA256 over the raw
request body, sent as `X-Hub-Signature: sha256=<hex>` (WebSub format). Atlassian
publishes an official test vector for implementers to self-check against:
https://developer.atlassian.com/cloud/jira/platform/webhooks/#secure-admin-webhooks

This test does not exercise Phase 3's handler in isolation. It originally
defined its own reference implementation before src/signature.py existed;
now that src/signature.py exists (Phase 3), this test imports from there
directly, so a regression in the real production code is caught here too.
"""

from __future__ import annotations

import hmac

from signature import compute_x_hub_signature

# Values published verbatim in Atlassian's Jira Cloud webhooks documentation.
JIRA_DOCUMENTED_TEST_VECTOR = {
    "secret": "It's a Secret to Everybody",
    "payload": "Hello World!",
    "expected_signature": (
        "sha256=a4771c39fbe90f317c7824e83ddef3caae9cb3d976c214ace1f2937e133263c9"
    ),
}


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
