"""Phase 3 tests: verify_signature() - the production entry point handler.py
will call, as opposed to Phase 2's lower-level compute_x_hub_signature()."""

from __future__ import annotations

from signature import compute_x_hub_signature, verify_signature

SECRET = "It's a Secret to Everybody"
BODY = "Hello World!"


def test_verify_signature_accepts_correct_signature():
    correct = compute_x_hub_signature(SECRET, BODY)
    assert verify_signature(SECRET, BODY, correct) is True


def test_verify_signature_rejects_wrong_secret():
    signed_with_wrong_secret = compute_x_hub_signature("wrong secret", BODY)
    assert verify_signature(SECRET, BODY, signed_with_wrong_secret) is False


def test_verify_signature_rejects_tampered_body():
    signature_for_original_body = compute_x_hub_signature(SECRET, BODY)
    assert verify_signature(SECRET, "Tampered body!", signature_for_original_body) is False


def test_verify_signature_rejects_missing_header():
    assert verify_signature(SECRET, BODY, None) is False


def test_verify_signature_rejects_empty_header():
    assert verify_signature(SECRET, BODY, "") is False


def test_verify_signature_does_not_raise_on_malformed_header():
    """A malformed header (wrong prefix, truncated, garbage) must be treated
    as a rejection, not an exception that could crash the handler or leak
    a stack trace back to the caller."""
    assert verify_signature(SECRET, BODY, "not-a-valid-signature-format") is False
