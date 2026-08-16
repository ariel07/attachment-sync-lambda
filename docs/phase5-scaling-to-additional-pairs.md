# Phase 5 — Scaling to Additional Client Pairs

**Context:** JTT ↔ JJST, JT2 ↔ JJST2, and JT3 ↔ JJST3 are the three
registered test pairs (all on `icxeed.atlassian.net`). This doc covers the
same onboarding pattern used to scale from one pair to three, for
onboarding any future production pair.

## What does NOT need to change

The sync logic (`jsm_mirror_link.py`, `attachment_sync.py`, `dedupe_check.py`)
resolves the target issue purely by following the "JSM Mirror" issue link on
each ticket - it never reads or hardcodes a project key. This was a
deliberate Phase 3 design choice, not an accident of scope: **one Lambda,
one deployment, serves every client pair**, as long as each pair's tickets
carry the link. No code branches per client, no per-pair config beyond what's
below.

## What DOES need to change per new pair

### 1. Native Jira side (reuse the proven pattern, no new tooling)
- Auto-create rule: copy the JTT→JJST pattern, scoped to the new JSM project
  → new Kanban project.
- `JSM Mirror` link type: already global/reusable - no new link type needed.
- Comment sync rules (JSM→Jira and Jira→JSM): copy the existing rule,
  re-scope to the new project pair, re-verify rule scope includes both
  projects (a bug hit once already on JTT/JJST - see userMemories).
- Status sync rule: same copy-and-rescope pattern once built.

### 2. Webhook JQL filter (Lambda side, config only)
Started scoped to a single project:
```
project = JTT
```
Currently widened to all three registered test pairs:
```
project in (JTT, JT2, JT3)
```
Widen it further as new pairs are added. Don't hand-edit this
separately from the allowlist below - both are now generated from one
source, `src/client_pairs.py`, to remove the drift risk of maintaining two
lists by hand.

### 3. ALLOWED_PROJECT_KEYS (Lambda side, defense-in-depth)
Set the `AllowedProjectKeys` SAM parameter to match the JQL filter's project
list. This is enforced in `handler.py` via
`project_scope.is_allowed_project()` before any Jira API call is made. It is
**not** a substitute for the JQL filter - it's a second, independent check so
that if the JQL filter is ever misconfigured (e.g. someone widens it without
realizing the implication), this Lambda still only acts on issues from
projects it's explicitly been told about, and logs a WARNING (not a silent
skip) when that happens so the drift is visible in CloudWatch.

Leaving the parameter blank (the default) disables the check - existing
single-pair deployments are unaffected.

### 3a. Generating both values from one source (`src/client_pairs.py`)
Add a `ClientPair(jsm_key=..., jira_key=..., client_name=...)` entry to the
`CLIENT_PAIRS` list in `src/client_pairs.py`, then run:
```bash
cd src
python client_pairs.py
```
This prints the exact JQL filter string and `AllowedProjectKeys` value to
paste into the webhook config and the SAM deploy step below - generated
from the same list, so they can't drift apart. `validate_pairs()` also
catches a duplicate JSM key or a Jira key claimed by more than one JSM
key (the architecture is strictly one-to-one) before either value is
generated, and this same check runs in CI via
`tests/test_phase5b_client_pairs.py`.

Note: `client_pairs.py` is a documentation/tooling source of truth read by
a human at onboarding time, not something the Lambda reads at runtime -
the deployed `ALLOWED_PROJECT_KEYS` env var is still what actually governs
Lambda behavior in production (see `project_scope.py`).

### 4. Jira service-account permissions
The one service account (Secrets Manager) is shared across all pairs. Before
onboarding a new pair, confirm the account has:
- Browse permission on the new JSM project
- Create/Edit permission (specifically attachment-create) on the new Kanban
  project
No new secret or credential is needed per pair - this is a permissions
checklist item, not an infra change.

### 5. Redeploy
```bash
cd infra
sam deploy --parameter-overrides AllowedProjectKeys="JTT,JT2,JT3"
```
(`samconfig.toml`'s saved parameters can be updated instead of passing
`--parameter-overrides` each time, if preferred.)

## Onboarding checklist (per new pair)

1. [ ] Add a `ClientPair` entry to `src/client_pairs.py`, run
   `python client_pairs.py` from `src/`, confirm `validate_pairs()` doesn't
   raise (no duplicate JSM/Jira key)
2. [ ] Native automation rules copied and re-scoped (create, both comment
   sync directions, status sync)
3. [ ] Test pair-equivalent smoke test: create a JSM ticket, confirm mirror
   created, confirm link resolves both directions
4. [ ] Service account has Browse + Attachment-create on both new projects
5. [ ] Webhook JQL filter updated to the generated string from step 1
6. [ ] `AllowedProjectKeys` SAM parameter updated to the generated value
   from step 1
7. [ ] Redeployed via `sam deploy`
8. [ ] Upload a test attachment on the new pair's JSM side, confirm it syncs
   and lands on the mirror (Kanban) issue
9. [ ] Confirm a deliberately out-of-scope issue (project not in the
   allowlist) produces a `project_not_allowlisted` skip in CloudWatch logs,
   not a crash

## Per-client observability

`sync_new_attachment()` results (and therefore the CloudWatch log lines in
`handler.py`) include `source_project` and `target_project` fields derived
from `project_scope.project_key_of()`, alongside the existing
`source_issue`/`target_issue` (full keys). This lets a CloudWatch Logs
Insights query filter or group by client pair directly:
```
fields @timestamp, source_project, target_project, status, reason
| filter source_project = "JT2"
```
without parsing project prefixes out of issue keys by hand.