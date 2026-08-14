"""Phase 2 tests: webhook payload envelope schema.

SUPERSEDED BY A LIVE FINDING IN PHASE 3 - kept for the historical record,
not deleted, because it's still an accurate schema for what attachment_created
actually contains. What changed: a real captured attachment_created payload
(icxeed.atlassian.net, JTT-102, attachment id 31804) revealed this event has
NO issue reference at all - not "issue" key, nothing linking it to a ticket.
The Lambda was switched to jira:issue_updated instead (see
tests/test_phase3_changelog_detection.py and docs/phase3-webhook-event-pivot.md
for the full story). This file's schema below is still correct for
attachment_created's shape - it's just not the event this Lambda listens for
anymore.

Source of truth: https://developer.atlassian.com/cloud/jira/platform/webhooks/
("Executing a webhook" / "Webhook payload" sections), fetched and reviewed
directly rather than assumed from training data.

Confirmed by the docs:
  - every webhook callback includes `timestamp` and `webhookEvent`
  - issue-related events include an `issue` object in standard REST API v2/v3
    issue shape (id, self, key, fields)
  - `attachment_created` / `attachment_deleted` are real, distinct webhook
    events (not a guess - explicitly listed under "Attachment webhooks")

NOT confirmed by the docs (and NOT guessed here, per project rules):
  - the exact field name/shape of the attachment object within an
    `attachment_created` payload (e.g. whether it's `attachment`, nested
    under `issue.fields.attachment`, or something else)

That gap is exactly what Phase 2's webhook registration + handler logging
(src/handler.py) exists to close - see docs/phase2-webhook-registration.md,
step "Capture a real payload". Until a real payload is captured, the
attachment-field test below is skipped with an explicit reason rather than
asserting an invented shape.
"""
from __future__ import annotations

import json

import pytest
from jsonschema import validate, ValidationError

# Schema for the parts of the envelope that ARE documented and confirmed.
CONFIRMED_ENVELOPE_SCHEMA = {
    "type": "object",
    "required": ["timestamp", "webhookEvent"],
    "properties": {
        "timestamp": {"type": "integer"},
        "webhookEvent": {
            "type": "string",
            "enum": ["attachment_created", "attachment_deleted"],
        },
        "issue": {
            "type": "object",
            "required": ["id", "self", "key", "fields"],
            "properties": {
                "id": {"type": "string"},
                "self": {"type": "string"},
                "key": {"type": "string"},
                "fields": {"type": "object"},
            },
        },
    },
    # Intentionally NOT "additionalProperties": False - the real payload will
    # have more fields (e.g. an attachment object) that we haven't verified
    # the shape of yet. A strict schema here would be asserting a guess.
}


def _sample_confirmed_envelope() -> dict:
    """A minimal, docs-derived example - NOT a captured real payload.
    Used only to prove the schema itself is well-formed and internally
    consistent. Must be replaced/supplemented with a real captured payload
    once available (see phase2-webhook-registration.md)."""
    return {
        "timestamp": 1735689600000,
        "webhookEvent": "attachment_created",
        "issue": {
            "id": "99291",
            "self": "https://icxeed.atlassian.net/rest/api/2/issue/99291",
            "key": "JTT-102",
            "fields": {},
        },
    }


def test_confirmed_envelope_schema_is_internally_valid():
    """The schema itself must validate the docs-derived example without error."""
    validate(instance=_sample_confirmed_envelope(), schema=CONFIRMED_ENVELOPE_SCHEMA)


def test_webhook_event_enum_rejects_unrelated_events():
    """Defensive: our schema (and eventually the handler) must reject events
    this Lambda was never registered for, in case the webhook scope is ever
    misconfigured to include unrelated event types."""
    bad_envelope = _sample_confirmed_envelope()
    bad_envelope["webhookEvent"] = "jira:issue_deleted"
    with pytest.raises(ValidationError):
        validate(instance=bad_envelope, schema=CONFIRMED_ENVELOPE_SCHEMA)


@pytest.mark.skip(
    reason=(
        "I cannot verify this: the exact attachment-field shape within an "
        "attachment_created payload is not documented with a literal example "
        "by Atlassian. Skipping rather than asserting an invented schema. "
        "Un-skip once a real payload is captured from CloudWatch Logs per "
        "docs/phase2-webhook-registration.md, and replace this test's body "
        "with a schema derived from that captured payload."
    )
)
def test_attachment_field_shape_TODO_needs_live_capture():
    raise NotImplementedError(
        "Blocked on live payload capture - see skip reason above."
    )
