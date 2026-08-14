# Phase 3 correction: webhook event pivot (attachment_created → jira:issue_updated)

## What happened

Phase 2 chose `attachment_created` over the original handoff doc's
`comment_created` / `jira:issue_updated`, reasoning it was a more precise,
purpose-built event. That reasoning was correct in isolation, but missed a
structural limitation: **a real `attachment_created` payload, captured live
from your production Lambda's CloudWatch logs, has no issue reference of any
kind.** See `tests/fixtures/real_captured_attachment_created_payload.json`
for the actual captured data.

Cross-checked against the official `GET /rest/api/3/attachment/{id}` schema
(fetched live, not assumed) - it has the same gap. This isn't a parsing bug;
the event genuinely cannot tell you which issue an attachment belongs to.

**The original handoff doc's choice of `jira:issue_updated` was correct.**
Phase 2 overrode it without this information. Correcting now, before Phase 4
builds anything further on the broken foundation.

## What changed in code

- `src/attachment_sync.py`: added `changelog_has_attachment_addition()` -
  detects an attachment addition from a `jira:issue_updated` payload's
  `changelog.items`, so the Lambda doesn't waste API calls (or worse, wrongly
  re-sync "most recent attachment") on every unrelated issue update.
- `src/handler.py`: checks `changelog_has_attachment_addition()` immediately
  after extracting `issue.key`, before any Jira API call. Non-attachment
  updates return `200 {"status": "skipped", "reason": "not_attachment_change"}`
  cheaply.
- Everything downstream (`sync_new_attachment`, link resolution, download/
  upload) is **unchanged** - it never depended on the old event's shape in
  the first place, by design (see Phase 3's original defensive design note).

Confidence note: Atlassian's docs confirm `changelog.items` exists and give
an example for summary/issuetype field changes, but not a literal example
for an `Attachment`-field entry. The convention used (`field == "Attachment"`,
`from`/`fromString` being `null` means "added", not "removed") is
well-established, widely-observed Jira behavior - flagged as such, not
presented as docs-certain. Worst case if this heuristic is ever wrong: a
missed sync (safe, caught by the existing native fallback notice) or a
harmless redundant one - never a sync to the wrong issue.

## Manual step required: fix the live Jira webhook registration

Your currently-registered webhook (`attachment-sync-prod`) is still
subscribed to **Attachment → created**. It needs to change to **Issue →
updated**, or the redeployed code will never receive a payload with an
`issue.key` to act on.

1. Jira admin → **Settings → System → Advanced → WebHooks**
2. Open the `attachment-sync-prod` webhook
3. Under **Events**, uncheck **Attachment → created**, check **Issue →
   updated**
4. **JQL filter**: keep `project = JTT` (unchanged)
5. Leave the secret and URL as-is - nothing else about the registration
   changes
6. Save

## Redeploy

```bash
cd infra
sam build
sam deploy
```

No parameter changes needed - this is a code-only update, same as the last
diagnostic-logging deploy.

## Re-test

1. Upload a fresh attachment to JTT-102 (plain issue-level attachment).
2. Watch logs:
   ```bash
   aws logs tail /aws/lambda/attachment-sync-prod --region us-east-1 --since 2m --follow
   ```
3. Expect a line like:
   ```
   Sync result for JTT-102: {"status": "synced", ..., "fallback_used": true}
   ```
4. Confirm the file actually landed on JJST-4.

One extra thing to expect and not be alarmed by: because `jira:issue_updated`
fires on *every* field change (not just attachments), you'll also see
`"status": "skipped", "reason": "not_attachment_change"` lines for unrelated
edits to JTT issues matching the JQL filter - e.g. status changes, comments,
assignee changes. That's the new filtering logic working correctly, not a bug.
