# Phase 1 — Manual Steps (must be done by you, outside this environment)

These are account-level actions requiring your AWS console/CLI access and Jira
admin access. I have no credentials to either system, so these cannot be
automated from here — only the code/IaC that depends on them is provided.

**Do not paste actual secret values, API tokens, or account IDs back into this
chat** — reference them by name/ARN only. Nothing below requires sharing them
with me.

## 1. Confirm AWS account access
- Confirm you (or the delivery engineer) have console or CLI access with
  permission to deploy CloudFormation/SAM stacks (`cloudformation:*` on this
  stack's resources, or an equivalent deploy role).
- Confirm the target AWS region (the handoff doc doesn't specify one — pick
  the region closest to your Jira Cloud instance's data residency, or your
  org's standard region).

## 2. Create the Jira service account + API token
1. In Jira admin, create a dedicated service account (not a personal account)
   scoped to `icxeed.atlassian.net`, per the existing architecture pattern.
2. Grant it access to both the JSM project and its paired Jira Software
   project (same requirement as the existing comment-sync automation rules).
3. Generate an API token for that account:
   `https://id.atlassian.com/manage-profile/security/api-tokens`
4. **Do not send me the token.** Store it directly in Secrets Manager (next step).

## 3. Store the token in Secrets Manager
```
aws secretsmanager create-secret \
  --name attachment-sync/jira-service-account \
  --description "Jira API token for attachment sync Lambda" \
  --secret-string '{"email":"<service-account-email>","api_token":"<token>"}'
```
Copy the resulting **secret ARN** — that's the value the SAM template needs
(`JiraServiceAccountSecretArn` parameter), not the secret contents.

## 4. Deploy the Phase 1 scaffold
From `infra/`:
```
sam build
sam deploy --guided \
  --parameter-overrides \
    EnvironmentName=dev \
    JiraServiceAccountSecretArn=<arn-from-step-3>
```
`sam deploy --guided` will prompt for stack name / region / confirmation on
first run and save the answers to `samconfig.toml` for subsequent deploys.

## 5. Record the webhook endpoint
After deploy, note the `WebhookEndpoint` output — you'll register this URL in
Jira (Settings → System → WebHooks) in **Phase 2**, not this phase. Don't
register it yet; the handler currently returns HTTP 501 (Phase 3 implements
the actual sync logic).

---

**What I did instead, in this sandbox:**
- Wrote and validated `infra/template.yaml` (cfn-lint clean, least-privilege
  IAM, scoped Secrets Manager read, no wildcard resources, finite log
  retention, no CORS on the server-to-server endpoint).
- Wrote `tests/test_phase1_infra.py` (10 tests, all passing) asserting those
  same properties, so any future edit to the template that weakens security
  posture fails CI before it fails a security review.
- Left `src/handler.py` as an explicit 501 stub — no invented business logic
  ahead of Phase 3.
