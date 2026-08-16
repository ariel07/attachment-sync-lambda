# Phase 6 (In Progress) — One-Directional Attachment Delete Sync

**Status: investigation + capture path done. Detection/matching logic and
the actual delete-sync flow are NOT built. Nothing in this phase is wired
to real infrastructure or deployed beyond the capture path itself.**

Read this before extending Phase 6. Same TDD discipline as every prior
phase applies: red confirmed before green, no invented Jira API behavior,
assumptions flagged explicitly rather than guessed.

## What's being asked for

When an attachment is **deleted** on the JSM side (e.g. JTT-102), delete
the corresponding mirrored attachment on the linked Jira Software issue
(JJST-4) too.

**Explicitly one-directional: JSM → Jira only**, matching the existing
sync-creation direction. A delete on the Jira Software side does **not**
propagate back to JSM. Deletions on the Jira side stay local to Jira —
only JSM is treated as the source of truth for what should or shouldn't
exist as an attachment on the mirror.

## What's actually built and committed

1. **`jira:issue_updated`'s changelog does not record attachment
   deletions.** Confirmed by pulling JTT-102's complete changelog (24
   entries, via Atlassian Rovo) after a real test deletion — the deleted
   attachment's addition was there, its removal was not. This rules out
   reusing the existing `changelog_has_attachment_addition()` detection
   path for deletions.
2. **`is_attachment_deleted_event()`** in `src/attachment_sync.py` —
   identifies an `attachment_deleted` webhook delivery
   (`webhookEvent == "attachment_deleted"`). Pure and defensive: returns
   `False` (never raises) on any missing/malformed field. Tested in
   `tests/test_phase6_delete_event_capture.py` (3 tests).
3. **Temporary capture-only path** in `src/handler.py::handle_webhook()`.
   Runs *before* `extract_issue_key_from_webhook`, deliberately — the
   sibling `attachment_created` event was confirmed (Phase 2/3) to
   sometimes carry no issue reference at all, so this path can't assume
   `issue.key` is present either. It only logs the full payload
   (`ATTACHMENT_DELETED_CAPTURE_ONLY payload (FULL BODY FOR ANALYSIS): ...`)
   and returns `200 {"status": "captured", "reason":
   "attachment_deleted_capture_only"}`. **It must never call into
   `jira_client` or any sync/delete logic** — this is enforced in tests via
   `_UnusedJiraClient`, whose methods raise `AssertionError` if called.
   Tested in `tests/test_phase6_handler_capture.py` (3 tests, including
   that signature verification still runs before this check).
4. **`JiraClient.delete_attachment(attachment_id)`** in `src/jira_client.py`
   — wraps `DELETE /rest/api/3/attachment/{id}`, verified against official
   Atlassian docs: 204 No Content on success, 403 Forbidden (attachments
   disabled or no delete permission), 404 Not Found. All non-2xx responses
   raise via `raise_for_status()`, same convention as every other method on
   this client. **This method does not decide whether a 404 should be
   treated as an idempotent no-op — that policy decision belongs to the
   caller** (see open question 4 below; the caller doesn't exist yet).
   Tested in `tests/test_phase6_jira_client_delete.py` (3 tests: success,
   403, 404).

**Nothing beyond the four items above is built.** In particular: no
detection-from-real-payload logic, no matching-to-target-attachment logic,
no actual delete-sync orchestration function, no idempotency tracking for
deletes, and no `docs/`-recorded confirmation of the real
`attachment_deleted` payload shape yet.

## Open questions to resolve before writing detection/matching code

These are flagged, not answered — confirm each against a real captured
`attachment_deleted` payload before assuming anything, same as Phase 2/3
did for the addition case.

1. **What does the real `attachment_deleted` payload look like?** The
   capture path above exists specifically to get one out of CloudWatch.
   Trigger a deletion on a test issue (JTT) and pull the logged payload
   before writing any matching logic against it.
2. **Does the payload carry an issue reference at all?** `attachment_created`
   proved this event family can omit `issue.key` entirely — confirm
   whether `attachment_deleted` does too. If it doesn't, resolving "which
   issue did this belong to" needs a different mechanism (e.g. a
   self-maintained index recording `attachment_id -> source_issue_key` at
   creation time) — not yet designed or built.
3. **How is the deleted attachment identified?** Creation sync relies on
   `attachment_id` extracted from context. A deletion payload may only
   contain the attachment's name, not a stable ID usable for a target-side
   lookup — confirm the actual shape before designing matching logic.
4. **What happens if the same-named file was uploaded twice on the target
   side?** Filename-only matching for delete is riskier than filename+size
   matching for create-dedup (`dedupe_check.py`), because deleting the
   *wrong* file is destructive and irreversible. Needs a decision: exact
   filename+size match only, and skip (don't guess) on ambiguity —
   analogous to how `AmbiguousMirrorLinkError` refuses to guess when an
   issue has two `JSM Mirror` links.
5. **Idempotency / retry safety:** Jira's webhook retry policy can
   redeliver the same event. A second delivery of the same delete event
   must not error out just because the file is already gone from the
   target — a 404 from `delete_attachment()` in that scenario should be
   treated as "already handled," not a failure. This is explicitly left to
   the (not-yet-built) caller, per `delete_attachment()`'s docstring.
6. **Permissions:** confirm the shared Jira service account actually has
   attachment-delete permission on the target (Kanban) projects — this
   wasn't needed for create-only sync and may not currently be granted.
7. **Business risk sign-off:** unlike creating an attachment, deleting one
   is destructive and not easily undoable (Jira's trash/recycle behavior
   for attachments should be checked — if there's no undo, that changes
   the risk calculus). Worth a deliberate go/no-go conversation before
   building the automated delete-sync flow, not just a technical one.

## Suggested shape for the next step (not a commitment)

- A new pure function, e.g. `extract_deleted_attachment_details()` in
  `attachment_sync.py`, once question 1 is answered from a real payload.
- A matching/sync function (e.g. `sync_deleted_attachment()`) that reuses
  `jsm_mirror_link.find_mirror_issue_key()` and `client_pairs.py` /
  `project_scope.py` unchanged — target resolution and scoping don't
  change for delete vs. create, only detection and matching do.
- Replace the capture-only branch in `handle_webhook()` with real logic
  only once the above is built and tested against the real captured
  fixture — don't remove the capture path until then.

## What NOT to do

Don't build detection/matching logic by pattern-matching the
addition-sync code and assuming the deletion payload mirrors it
structurally. The "no assumption" rule that governed every prior phase
applies here with extra weight, specifically because the failure mode of
a wrong assumption is data loss (deleting the wrong attachment) rather
than a missed sync.