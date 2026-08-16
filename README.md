# attachment-sync-lambda

AWS Lambda that syncs attachments from JSM (Jira Service Management)
issues to their mirrored Jira Software issues, closing a gap native Jira
automation can't fill on its own.

## Why this exists

This is one piece of a larger JSM↔Jira Software mirroring architecture:
JSM issues are paired with client-specific Jira Software projects via a
custom "JSM Mirror" issue link, so developers/PMs without JSM licenses can
still see support-ticket activity mirrored into a project they do have
access to. Auto-create, issue linking, and bidirectional comment/status
sync are handled by native Jira automation rules. **Attachment file sync
is the one requirement native automation cannot fulfill:**

- Jira's attachment upload endpoint
  (`POST /rest/api/3/issue/{issueKey}/attachments`) requires
  `multipart/form-data` with raw binary content.
- Jira automation's "Send web request" action has no multipart/binary body
  option.
- The native "Edit issue → copy Attachment" action — Atlassian's
  documented intended path — was tested repeatedly with verified-correct
  link/scope/condition config and consistently failed to resolve the
  branch to the linked issue, despite an identical link-type/branch
  config working in the parallel comment-sync rule. Platform-level
  inconsistency, not a config error.

This Lambda is the targeted fix for that one gap — everything else in the
architecture stays native.

## How it works

1. A Jira webhook (registered on the JSM project(s)) fires on
   `jira:issue_updated`.
2. API Gateway (HttpApi) forwards the payload to this Lambda.
3. `handler.py::handle_webhook()`:
   - Verifies the `X-Hub-Signature` HMAC header.
   - Filters out updates that aren't an attachment addition (`jira:issue_updated`
     fires on every field change, not just attachments).
   - Confirms the triggering issue's project is on the allowlist (optional,
     defense-in-depth alongside the webhook's own JQL filter).
   - Resolves the linked mirror issue via the issue's `JSM Mirror` link
     (`jsm_mirror_link.py`) — pairing is resolved at runtime through this
     link, not hardcoded per-project config.
   - Skips if the attachment is already on the mirror (`dedupe_check.py`
     — see `docs/phase4-dedupe-check.md`).
   - Downloads the attachment and re-uploads it to the mirror issue
     (`jira_client.py`).

Sync is one-directional: JSM → Jira Software.

## Project structure

```
src/
  handler.py          Lambda entry point (handle_webhook / lambda_handler)
  attachment_sync.py   Orchestration: webhook parsing, sync_new_attachment()
  jira_client.py        Thin Jira REST v3 client (get issue, up/download, delete attachment)
  jsm_mirror_link.py    Resolves the "JSM Mirror" issue link at runtime
  dedupe_check.py        Filename+size dedupe guard (Phase 4)
  project_scope.py         Project allowlist guard (Phase 5)
  client_pairs.py           Single-source-of-truth JSM<->Jira pair registry (Phase 5b)
  signature.py                Webhook HMAC signature verify/compute
  secrets.py                    Secrets Manager access
  requirements.txt                Runtime deps (deployed with the Lambda)
tests/
  test_phase*.py       Unit tests, organized by the phase that introduced them
  fixtures/             Real captured webhook payloads and Jira API responses
infra/
  template.yaml         SAM template (API Gateway HttpApi + Lambda + IAM)
docs/
  phase*.md             Phase-by-phase handoff notes (see below)
```

## Setup and deployment

Manual `sam deploy` — no CD pipeline yet.

```bash
cd infra
sam build
sam deploy --template-file .aws-sam/build/template.yaml \
  --resolve-s3 --capabilities CAPABILITY_IAM
```

**Do not** run `sam deploy -t infra/template.yaml` directly after
`sam build` — it re-resolves `CodeUri` against the raw source tree, not
the built artifact, and silently drops installed dependencies. Deploy the
*built* template as shown above.

Required parameters (see `infra/template.yaml` for full descriptions):
`JiraServiceAccountSecretArn`, `JiraWebhookSigningSecretArn`,
`JiraBaseUrl`, and optionally `AllowedProjectKeys` (comma-separated JSM
project keys; blank disables the allowlist check).

Both secrets must be created manually first — see
`docs/phase1-manual-steps.md`. The webhook itself is registered manually
in Jira (Settings → System → WebHooks) — see
`docs/phase2-webhook-registration.md`.

After any deploy, verify with a throwaway invoke before touching Jira again:

```bash
aws lambda invoke --profile <profile> --region us-east-1 \
  --function-name attachment-sync-prod \
  --payload '{"headers":{},"body":""}' \
  --cli-binary-format raw-in-base64-out /tmp/out.json
cat /tmp/out.json   # expect: {"statusCode": 401, "body": "Invalid signature"}
```

## Testing

```bash
python -m pytest tests/ -v
```

Run from the repo root, not from `src/` — `conftest.py` adds `src/` to
the path. Tests use dependency-injected fakes/protocols throughout; no
mocking library beyond `moto` (for DynamoDB-touching tests, where
applicable) is required.

## Tooling

- **ruff** — lint + format (`pyproject.toml`): `line-length = 100`,
  `target-version = "py314"`, rule sets `E, W, F, I, B, UP, S`. Test files
  get scoped exceptions for assert usage, test-double "secrets," and the
  YAML/subprocess calls used to validate `infra/template.yaml` — see
  `pyproject.toml` for the specific rationale on each.
- **cfn-lint** — validates `infra/template.yaml`.
- Runtime deps are pinned in `src/requirements.txt` — deliberately minimal
  (just `requests`; `boto3`/`botocore` are excluded because Lambda's
  Python runtime ships them preinstalled).

## Documentation index

Phase docs are handoff notes, not a changelog — each records what was
actually built, what was verified against live data vs. assumed, and what
was deliberately deferred, so a future session (or another engineer)
doesn't have to re-derive context.

| Doc | Covers |
|---|---|
| `docs/phase1-manual-steps.md` | Manual AWS/Jira setup prerequisites (secrets, service account) |
| `docs/phase2-webhook-registration.md` | Registering the Jira webhook |
| `docs/phase3-core-logic.md` | Core sync logic: link resolution, download/re-upload |
| `docs/phase3-webhook-event-pivot.md` | Why the webhook event changed from `attachment_created` to `jira:issue_updated` |
| `docs/phase4-dedupe-check.md` | Loop guard / idempotency for duplicate webhook deliveries |
| `docs/phase5-scaling-to-additional-pairs.md` | Onboarding additional client pairs, project allowlist |
| `docs/phase6-attachment-delete-sync.md` | Attachment **delete** sync — investigation + capture path done, detection/matching logic not yet built |

Phase 5b (the `client_pairs.py` single-source-of-truth registry) doesn't
have a standalone doc yet — see the module docstring in `src/client_pairs.py`
and `tests/test_phase5b_client_pairs.py` for the design rationale in the
meantime.

## Known limitations / not yet built

- **Delete sync** (attachment deletions on JSM propagating to the mirror)
  is only at the investigation/capture stage — see
  `docs/phase6-attachment-delete-sync.md`.
- **No CI workflow committed yet.** Tests and linting are run locally.
- **No CD pipeline.** Deploys are manual `sam deploy`.
- **Dedupe guard is a live REST check, not atomic** — see
  `docs/phase4-dedupe-check.md` for the accepted trade-off.