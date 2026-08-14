# Phase 2 — Webhook Configuration (manual steps)

Jira admin action — I can't click through Jira's UI from here. Same caution
as Phase 1: don't paste the generated webhook secret back into this chat.

## Decision made in this phase (flagging before you register anything)

The original handoff doc scoped this to `comment_created` / `jira:issue_updated`.
Atlassian's docs confirm a purpose-built **`attachment_created`** webhook event
that fires specifically when an attachment is added — a better match than
inferring "was this update an attachment?" from a generic issue-update payload.
**These steps register `attachment_created`, not the original doc's events.**
If you'd rather match the original doc exactly, say so and I'll adjust —
it's a one-field change in the registration form.

**Known accepted gap:** Atlassian's docs state attachments added *at issue
creation time* (not added afterward) don't fire `attachment_created` at all —
they only appear in the `jira:issue_created` payload's attachment field. The
existing native text-notice fallback rule already covers "here's a pointer to
the source ticket if sync doesn't happen," so this is being treated as an
accepted v1 gap, not a blocker. Revisit if it proves to matter in practice.

## 1. Deploy the Phase 2 infra changes first

Phase 2 added a second Secrets Manager parameter (`JiraWebhookSigningSecretArn`)
to `infra/template.yaml`, for HMAC signature verification in Phase 3. Before
registering the webhook in Jira, create that secret:

```bash
aws secretsmanager create-secret \
  --name attachment-sync/jira-webhook-signing-secret \
  --description "HMAC secret for verifying Jira webhook X-Hub-Signature" \
  --secret-string '{"secret":"<paste-the-value-Jira-generates-in-step-3-here>"}'
```

You'll actually populate this **after** step 3 below, once Jira generates the
secret — chicken-and-egg, but that's the correct order (Jira only shows you
the secret once, at creation time).

Then redeploy:
```bash
sam build
sam deploy --parameter-overrides \
  EnvironmentName=dev \
  JiraServiceAccountSecretArn=<from-phase-1> \
  JiraWebhookSigningSecretArn=<arn-from-secret-created-above>
```

## 2. Confirm the webhook endpoint from Phase 1

Grab the `WebhookEndpoint` output from your Phase 1 stack (or re-run
`sam list stack-outputs` / check the CloudFormation console). It'll look like:
```
https://<api-id>.execute-api.<region>.amazonaws.com/dev/webhook/jira-attachment
```

## 3. Register the webhook in Jira

1. Go to **Settings (gear icon) → System → Advanced → WebHooks**
   (`https://icxeed.atlassian.net/plugins/servlet/webhooks`)
2. Click **Create a WebHook**
3. **Name:** `attachment-sync-dev` (or `-staging`/`-prod` to match environment)
4. **URL:** the `WebhookEndpoint` output from step 2
5. **Description:** "Syncs new attachments to the JSM-mirror issue (attachment-sync-lambda)"
6. **Events:** under **Attachment**, check only **created** — leave everything
   else unchecked. Do not select "all events."
7. **JQL filter (scope):** start narrow, matching your existing test pattern:
   ```
   project = JTT
   ```
   Expand to additional client projects only after Phase 7 (Testing) passes.
8. **Secret:** click **Generate secret** (don't type your own — let Jira
   generate high-entropy randomness). Copy it immediately — Jira will not
   show it again. Use this value in the `aws secretsmanager create-secret`
   command from step 1.
9. Leave **Exclude body** unchecked — we need the JSON payload.
10. Save.

## 4. Fire a real event and capture the payload

1. In JTT (or whichever test project you scoped the JQL to), upload any
   attachment to a test issue.
2. In AWS Console → CloudWatch → Log groups → `/aws/lambda/attachment-sync-dev`,
   find the most recent log stream. You'll see a line like:
   ```
   attachment-sync webhook received: {"resource":..., "requestContext":..., "body": "{...}"}
   ```
   The `body` field (a JSON *string* inside the event, since this arrives via
   API Gateway) contains the actual Jira webhook payload — parse that string
   to see the real `attachment_created` shape.
3. Also check Jira's own delivery log: on the webhook's detail page in Jira
   admin, **Recent Deliveries** shows the same payload Jira sent, plus the
   HTTP status your Lambda returned (should be `501` right now — expected,
   confirms delivery is working before Phase 3 implements real handling).

## 5. Close the schema gap

Paste the captured payload (with any real ticket summaries/attachment
filenames redacted if sensitive) back into this conversation, or save it as
`tests/fixtures/attachment_created_sample.json` in the repo. Either way, that
unblocks `tests/test_phase2_payload_schema.py::test_attachment_field_shape_TODO_needs_live_capture`,
which is currently `SKIP`ped rather than guessed at.

## 6. Note on firewall allowlisting (only relevant if you add one later)

Your Lambda's API Gateway endpoint is a public AWS URL — no inbound
allowlisting is required for Jira to reach it today. If you later put this
endpoint behind a WAF, VPC, or corporate firewall with IP restrictions,
you'd need to allow Atlassian's documented outgoing IP ranges from
`https://support.atlassian.com/organization-administration/docs/ip-addresses-and-domains-for-atlassian-cloud-products/`.
Not needed for the current architecture — noting for completeness only.

---

**What I did instead, in this sandbox:**
- Added `JiraWebhookSigningSecretArn` parameter + scoped IAM read + env var to
  `infra/template.yaml` (still least-privilege — two named secrets, no wildcards).
- Updated `src/handler.py` to log the raw event (still no business logic,
  still returns 501) so step 4 above has something to capture from.
- Wrote `tests/test_phase2_webhook_signature.py` — validates our planned HMAC
  verification approach against Atlassian's own published test vector, before
  any handler code exists.
- Wrote `tests/test_phase2_payload_schema.py` — schema-validates the envelope
  fields the docs *do* confirm, and explicitly skips (doesn't guess) the one
  field shape the docs don't confirm.
