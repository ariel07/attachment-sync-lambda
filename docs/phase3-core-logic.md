# Phase 3 — Lambda Core Logic (manual steps)

## What changed vs. Phase 1/2

`src/handler.py` is no longer a 501 stub. Five new modules do the real work:

| Module | Responsibility |
|---|---|
| `src/signature.py` | HMAC verification of `X-Hub-Signature` (validated in Phase 2 against Atlassian's own test vector, now the production path) |
| `src/jsm_mirror_link.py` | Finds the mirrored issue key from `issuelinks`, given a link type name |
| `src/jira_client.py` | Thin REST v3 wrapper: `get_issue`, `download_attachment`, `upload_attachment` |
| `src/secrets.py` | Secrets Manager JSON fetch, dependency-injectable for tests |
| `src/attachment_sync.py` | Orchestration: webhook → mirror lookup → attachment resolution → sync |

`src/handler.py` is now a thin AWS wrapper around `handle_webhook()`, which contains all the actual decision logic and is fully unit tested with fakes (no real AWS calls in the test suite).

## Design decision worth knowing: how the unverified webhook schema was handled

Phase 2 flagged that the exact shape of the `attachment` field inside an `attachment_created` webhook payload couldn't be confirmed from Atlassian's docs. Rather than guess at it, Phase 3's `sync_new_attachment()` treats the webhook as a **trigger only**:

1. Extract `issue.key` from the webhook (this field IS confirmed by docs).
2. Best-effort: if the webhook happens to include `attachment.id`, use it to pick the exact attachment.
3. If not, re-fetch the issue's attachment list via `GET /rest/api/3/issue/{key}?fields=attachment` — a call whose response shape **is** confirmed (verified live against your actual `icxeed.atlassian.net` instance via Rovo, not guessed), and fall back to the most recently created attachment.

This means Phase 3 works correctly **today**, even without a captured real payload — but once you capture one (per Phase 2's runbook), if it turns out `attachment.id` **is** present, the code already handles that path with no changes needed. If the real payload reveals something entirely different, only `extract_attachment_id_from_webhook()` in `src/attachment_sync.py` needs updating — everything downstream is unaffected.

## Real data used to build this (not invented)

Two fixtures in `tests/fixtures/` were captured live from `icxeed.atlassian.net` via Atlassian Rovo, not fabricated:

- `jtt_102_issuelinks.json` — confirms the JSM Mirror link shape: on a JSM ticket, the mirrored issue is under `issuelinks[].inwardIssue`, for a link where `type.name == "JSM Mirror"`.
- `jtt_102_attachments.json` — confirms the attachment object shape, **including** a real edge case: the `.html` attachment on JTT-102 has no `thumbnail` field at all (only image types get one). A test (`test_sync_new_attachment_handles_missing_thumbnail_field_gracefully`) locks this in.

## Deploy

New pieces since Phase 2: the `JiraBaseUrl` parameter (plain string, not a secret) and `src/requirements.txt` (adds `requests` — `boto3` ships preinstalled in the Lambda runtime, not bundled).

```bash
sam build
sam deploy --parameter-overrides \
  EnvironmentName=dev \
  JiraServiceAccountSecretArn=<from-phase-1> \
  JiraWebhookSigningSecretArn=<from-phase-2> \
  JiraBaseUrl=https://icxeed.atlassian.net
```

`sam build` needs `src/requirements.txt` present to bundle `requests` — confirm it's in the repo before building (it should be, from this commit).

## Test after deploy (Phase 7 territory, but do a smoke check now)

1. Upload a fresh attachment to JTT-102 (or any JTT issue with a confirmed JSM Mirror link to a JJST issue).
2. Check CloudWatch Logs (`/aws/lambda/attachment-sync-dev`) for a `Sync result for JTT-XXX: {"status": "synced", ...}` line.
3. Confirm the attachment actually landed on the JJST-side issue.
4. If it shows `"status": "skipped", "reason": "..."`, that's working-as-designed for the reason given (no mirror link, no attachments, or attachment_not_found) — not a bug.

## Known gaps carried forward (not silently dropped)

- **Loop guard / idempotency** — not yet implemented. If the webhook fires twice for the same attachment (Jira's documented retry-up-to-5-times behavior on failure, or a duplicate `attachment_created` event), this Lambda will currently re-upload it, creating a duplicate attachment on the mirror. This is explicitly **Phase 4** scope per the original LOE — flagging so it's not mistaken for a Phase 3 bug.
- **`fields=attachment` returns ALL attachments on the issue**, not just the new one, when falling back (no `attachment.id` in the webhook). On an issue with many attachments, this means re-fetching a growing list every time — fine at current volume, worth revisiting if a JTT-equivalent ticket accumulates dozens of attachments.
- **Multi-environment / CI-CD, alerting, and scaled parameterization** are Phases 5, 6, and 8 respectively — not touched here.

---

**What I did instead, in this sandbox:** built all five modules test-first (red→green shown in this conversation for each), verified against real captured data from your instance rather than invented fixtures, verified the attachment-upload endpoint's exact multipart/header requirements against official docs before writing `jira_client.py`, and kept `handle_webhook()` fully unit-testable via dependency injection so the test suite needs zero real AWS/Jira credentials to run.
