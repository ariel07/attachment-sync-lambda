"""Multi-client-pair project allowlist guard.

See tests/test_phase5_project_scope.py module docstring for full design
rationale. Pure functions, no network I/O, no AWS dependency - same pattern
as jsm_mirror_link.py and dedupe_check.py.
"""

from __future__ import annotations


def project_key_of(issue_key: str) -> str:
    """Extract the project key prefix from an issue key (e.g. "JTT-102" ->
    "JTT"). Raises ValueError on a missing/malformed issue_key - same
    validation is_allowed_project already applied inline; extracted here so
    other modules (e.g. attachment_sync.py, for per-project log fields) can
    reuse it without duplicating the parsing rule.
    """
    if not issue_key or "-" not in issue_key:
        raise ValueError(f"issue_key is missing or malformed: {issue_key!r}")

    project_key, _, rest = issue_key.partition("-")
    if not project_key or not rest:
        raise ValueError(f"issue_key is missing or malformed: {issue_key!r}")
    return project_key


def is_allowed_project(issue_key: str, allowed_project_keys: list[str]) -> bool:
    """Return True if issue_key's project prefix is on the allowlist.

    Raises ValueError if issue_key is missing/malformed (no "-", or nothing
    before/after it) or if allowed_project_keys is empty - both are treated
    as configuration errors, not routine "not allowed" outcomes, since an
    empty allowlist would otherwise silently reject every issue with no
    signal that the deploy is misconfigured.
    """
    if not allowed_project_keys:
        raise ValueError("allowed_project_keys must not be empty")

    project_key = project_key_of(issue_key)
    normalized_allowlist = {key.strip().upper() for key in allowed_project_keys}
    return project_key.upper() in normalized_allowlist


def parse_allowed_project_keys(raw: str) -> list[str]:
    """Parse a comma-separated ALLOWED_PROJECT_KEYS env var into a list.

    Trims whitespace around each entry. Raises ValueError on an empty or
    whitespace-only string - same "fail loudly on likely misconfiguration"
    stance as is_allowed_project's empty-list check.
    """
    if not raw or not raw.strip():
        raise ValueError("ALLOWED_PROJECT_KEYS must not be empty")
    return [key.strip() for key in raw.split(",") if key.strip()]
