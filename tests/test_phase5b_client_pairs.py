"""Phase 5b tests: client-pair registry - single source of truth for
JSM<->Jira project pairs.

CONTEXT: Phase 5 added AllowedProjectKeys (the Lambda-side allowlist) as a
plain comma-separated env var, maintained by hand alongside the webhook's
JQL filter. Two independently-maintained lists that are supposed to always
match is exactly the kind of drift this Lambda's own allowlist WARNING log
was built to catch after the fact - this module addresses it before the
fact, by giving both the JQL filter and AllowedProjectKeys a single
generation source.

Written before src/client_pairs.py exists - TDD.

Deliberately a plain Python list of dataclasses, not a JSON/YAML config
file loaded at runtime: this data changes rarely (once per client
onboarded), review of a code change (PR diff) is a feature here not a
limitation, and it avoids adding a config-parsing dependency or a new
runtime failure mode (malformed file) for a handful of static rows. Also
NOT wired into the Lambda's own env-var reading at runtime in this phase -
ALLOWED_PROJECT_KEYS stays the actual deployed mechanism (see handler.py);
this registry is a documentation/tooling source of truth for humans keeping
that value and the JQL filter in sync, not a new runtime dependency.
"""
from __future__ import annotations

import pytest


def test_pair_holds_jsm_and_jira_keys_and_client_name():
    from client_pairs import ClientPair

    pair = ClientPair(jsm_key="JTT", jira_key="JJST", client_name="iCXeed internal test pair")

    assert pair.jsm_key == "JTT"
    assert pair.jira_key == "JJST"
    assert pair.client_name == "iCXeed internal test pair"


def test_registry_exposes_the_known_pairs():
    from client_pairs import CLIENT_PAIRS

    jsm_keys = {pair.jsm_key for pair in CLIENT_PAIRS}
    assert "JTT" in jsm_keys


def test_jql_filter_lists_every_registered_jsm_key_in_registration_order():
    from client_pairs import ClientPair, jql_filter_for

    pairs = [
        ClientPair(jsm_key="JTT", jira_key="JJST", client_name="Test pair"),
        ClientPair(jsm_key="ABB", jira_key="DCC", client_name="Client A"),
        ClientPair(jsm_key="BEE", jira_key="GTT", client_name="Client B"),
    ]

    assert jql_filter_for(pairs) == "project in (JTT, ABB, BEE)"


def test_jql_filter_raises_on_empty_registry():
    from client_pairs import jql_filter_for

    with pytest.raises(ValueError):
        jql_filter_for([])


def test_allowed_project_keys_env_value_matches_jql_source_list():
    from client_pairs import ClientPair, allowed_project_keys_env_value_for

    pairs = [
        ClientPair(jsm_key="JTT", jira_key="JJST", client_name="Test pair"),
        ClientPair(jsm_key="ABB", jira_key="DCC", client_name="Client A"),
    ]

    assert allowed_project_keys_env_value_for(pairs) == "JTT,ABB"


def test_rejects_duplicate_jsm_key_in_registry():
    from client_pairs import ClientPair, validate_pairs

    pairs = [
        ClientPair(jsm_key="JTT", jira_key="JJST", client_name="Test pair"),
        ClientPair(jsm_key="JTT", jira_key="DCC", client_name="Duplicate"),
    ]
    with pytest.raises(ValueError, match="duplicate JSM key"):
        validate_pairs(pairs)


def test_rejects_duplicate_jira_key_in_registry():
    # Two source projects both claiming to mirror into the same target
    # project is a misconfiguration, not a valid multi-tenant setup - the
    # architecture is documented as strictly one-to-one.
    from client_pairs import ClientPair, validate_pairs

    pairs = [
        ClientPair(jsm_key="JTT", jira_key="JJST", client_name="Test pair"),
        ClientPair(jsm_key="ABB", jira_key="JJST", client_name="Duplicate target"),
    ]
    with pytest.raises(ValueError, match="duplicate Jira key"):
        validate_pairs(pairs)


def test_the_registered_client_pairs_constant_itself_passes_validation():
    # The actual CLIENT_PAIRS data shipped in this module must itself be
    # internally consistent - guards against a future hand-edit introducing
    # a duplicate.
    from client_pairs import CLIENT_PAIRS, validate_pairs

    validate_pairs(CLIENT_PAIRS)  # must not raise
