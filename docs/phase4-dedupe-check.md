# Phase 4 — Loop Guard / Idempotency (simplified)

## What this phase is

Jira Cloud's webhook docs confirm retries happen: "if a webhook is sent to
its callback URL but fails, Jira Cloud will attempt to resend it up to five
times... this means that some webhooks might be delivered more than once"
(https://developer.atlassian.com/cloud/jira/platform/webhooks/). Without a
guard, each retried delivery for the same attachment would re-upload it to
the mirror issue, creating duplicates.

## What's built

`src/dedupe_check.py` — `already_synced(target_issue_key, filename,
size_bytes, lookup)`. Returns `True` if an attachment with matching
filename **and** size already exists on the target issue's attachment
list, meaning the current delivery is a duplicate and the upload step
should be skipped.

`AttachmentLookup` (a `Protocol`) is the only dependency — one method,
`get_target_attachments(issue_key) -> list[tuple[str, int]]`. This keeps
the dedupe logic testable in isolation without depending on the Jira
client directly.

Wired into `src/attachment_sync.py::sync_new_attachment()`: after resolving
the mirror issue and the specific attachment to sync, it fetches the
target issue's current attachments (`_AttachmentListLookup`, an adapter
around data already fetched for that call — no extra round trip), and
checks `already_synced()` before downloading/uploading. A match returns
`{"status": "skipped", "reason": "already_synced", ...}`.

## Scope decision: filename+size check, not DynamoDB

This is the **simplified** version of Phase 4, and it's what's actually
deployed. The scope decision (documented in `dedupe_check.py`'s module
docstring) was: a live REST lookup against the target issue's existing
attachments, filename+size match, no new AWS resource, no IaC to
maintain.

**Trade-off accepted explicitly:** this is a live REST lookup, not an
atomic compare-and-set. Two genuinely concurrent webhook deliveries for
the same attachment could theoretically both pass the check before either
upload completes. At support-ticket volume for a single client pair, that
race is judged an acceptable risk versus provisioning and maintaining a
DynamoDB table.

**Revisit if:** volume or criticality grows to the point where that race
becomes a real, observed problem rather than a theoretical one. A
DynamoDB-backed version (partition key on attachment identity, atomic
conditional writes) is the natural next step if that happens — not yet
needed, not yet built as part of what's committed here.

## Tests

`tests/test_phase4_dedupe_check.py` — 6 tests, no AWS mocking needed since
this module makes no AWS calls; it depends only on the injected
`AttachmentLookup` Protocol (satisfied by a `FakeAttachmentLookup` test
double). Covers: exact match, filename mismatch, size mismatch, no
existing attachments, matching among several existing attachments, and
input validation (empty issue key, empty filename, negative size — all
raise `ValueError`).

## What this phase does NOT cover

- No idempotency guard against a *duplicate delete* — that's Phase 6's
  concern, and it's a separate, not-yet-built problem (see
  `docs/phase6-attachment-deleted-capture.md`).
- No cross-invocation locking. If the underlying race described above
  ever becomes a real issue, it needs a different mechanism than what's
  here (e.g. DynamoDB conditional writes), not an extension of the
  current filename+size check.