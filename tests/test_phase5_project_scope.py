"""Phase 5 tests: multi-client-pair project allowlist guard.

Written before src/project_scope.py exists - TDD.

CONTEXT: as of Phase 4, this Lambda is already client-pair-agnostic at the
sync-logic level - sync_new_attachment() resolves the target purely via the
issue's "JSM Mirror" link (see jsm_mirror_link.py), never via a hardcoded
project key. Scaling to additional pairs (e.g. ABB->DCC, BEE->GTT) is
primarily a JSM-automation + webhook-JQL-scoping exercise, not a code
change - see docs/phase5-scaling-to-additional-pairs.md.

This module adds one piece of defense-in-depth: an explicit allowlist of
source (JSM) project keys, checked in-Lambda before any Jira API call. This
protects against a webhook JQL filter being misconfigured or widened by
someone unaware of the in-Lambda assumption (e.g. `project is not EMPTY`
instead of an explicit `project in (...)` list) - without it, the Lambda
would silently attempt to process issues from ANY project in the Jira site,
including ones with no "JSM Mirror" link convention at all. A skip is the
correct outcome for those, not a crash, but skipping loudly (logged as a
warning, since a healthy system should never hit this) surfaces a
misconfiguration instead of masking it as routine "no_mirror_link" noise.

Assumption flagged, not verified against live Jira: project keys are the
substring of an issue key before the first "-", and Jira enforces uppercase
project keys. This is documented, longstanding Jira behavior
(https://support.atlassian.com/jira-software-cloud/docs/what-is-an-issue/)
but no live payload was captured to re-confirm it for this task.
"""

from __future__ import annotations

import pytest


def test_allows_issue_from_an_allowlisted_project():
    from project_scope import is_allowed_project

    assert is_allowed_project("JTT-102", allowed_project_keys=["JTT", "ABB", "BEE"]) is True


def test_rejects_issue_from_a_project_not_on_the_allowlist():
    from project_scope import is_allowed_project

    assert is_allowed_project("XYZ-1", allowed_project_keys=["JTT", "ABB", "BEE"]) is False


def test_is_case_insensitive_on_the_project_key_prefix():
    # Defense-in-depth, not a documented Jira behavior change: Jira project
    # keys are always uppercase, but this comparison is made robust to a
    # miscased allowlist entry in config rather than trusting operator input.
    from project_scope import is_allowed_project

    assert is_allowed_project("jtt-102", allowed_project_keys=["JTT"]) is True
    assert is_allowed_project("JTT-102", allowed_project_keys=["jtt"]) is True


def test_matches_multi_letter_and_numeric_suffixed_project_keys():
    from project_scope import is_allowed_project

    assert is_allowed_project("GTT2-55", allowed_project_keys=["GTT2"]) is True


@pytest.mark.parametrize("issue_key", ["", "NODASH", "-102", None])
def test_raises_on_malformed_or_missing_issue_key(issue_key):
    from project_scope import is_allowed_project

    with pytest.raises(ValueError):
        is_allowed_project(issue_key, allowed_project_keys=["JTT"])


def test_raises_on_empty_allowlist():
    # Fail loudly rather than silently allow-all: an empty allowlist is
    # almost certainly a deploy/config mistake, not an intentional "accept
    # everything" state.
    from project_scope import is_allowed_project

    with pytest.raises(ValueError):
        is_allowed_project("JTT-102", allowed_project_keys=[])


def test_parse_allowed_project_keys_splits_and_trims_env_var():
    from project_scope import parse_allowed_project_keys

    assert parse_allowed_project_keys("JTT, ABB,BEE ") == ["JTT", "ABB", "BEE"]


def test_parse_allowed_project_keys_raises_on_empty_string():
    from project_scope import parse_allowed_project_keys

    with pytest.raises(ValueError):
        parse_allowed_project_keys("")


def test_project_key_of_extracts_prefix_before_first_dash():
    from project_scope import project_key_of

    assert project_key_of("JTT-102") == "JTT"
    assert project_key_of("GTT2-55") == "GTT2"


@pytest.mark.parametrize("issue_key", ["", "NODASH", "-102", None])
def test_project_key_of_raises_on_malformed_or_missing_issue_key(issue_key):
    from project_scope import project_key_of

    with pytest.raises(ValueError):
        project_key_of(issue_key)
