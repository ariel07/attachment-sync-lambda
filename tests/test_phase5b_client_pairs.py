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

    pair = ClientPair(jsm_key="KMS", jira_key="KM", client_name="Kip McGrath")

    assert pair.jsm_key == "KMS"
    assert pair.jira_key == "KM"
    assert pair.client_name == "Kip McGrath"


def test_registry_exposes_the_known_pairs():
    from client_pairs import CLIENT_PAIRS

    jsm_keys = {pair.jsm_key for pair in CLIENT_PAIRS}
    assert "KMS" in jsm_keys


def test_jql_filter_lists_every_registered_jsm_key_in_registration_order():
    from client_pairs import ClientPair, jql_filter_for

    pairs = [
        ClientPair(jsm_key="AAA", jira_key="ZZZ", client_name="Client Z"),
        ClientPair(jsm_key="ABB", jira_key="DCC", client_name="Client A"),
        ClientPair(jsm_key="BEE", jira_key="GTT", client_name="Client B"),
    ]

    assert jql_filter_for(pairs) == "project in (AAA, ABB, BEE)"


def test_jql_filter_raises_on_empty_registry():
    from client_pairs import jql_filter_for

    with pytest.raises(ValueError):
        jql_filter_for([])


# --- Phase 8: bidirectional scope ------------------------------------------
# Phase 3-7 assumption ("the mirror side is never referenced by the webhook,
# JQL filter, or ALLOWED_PROJECT_KEYS") no longer holds: attachment_sync now
# tries both link directions (see src/attachment_sync.py), so an attachment
# added directly to a mirror ticket needs the WEBHOOK ITSELF to fire for the
# mirror project too, or the request never reaches this Lambda at all.
# include_mirror_side=True generates the wider scope needed for that; the
# default stays JSM-only so existing Phase 3-7 callers/behavior don't change.


def test_jql_filter_bidirectional_includes_both_sides_interleaved_by_pair():
    from client_pairs import ClientPair, jql_filter_for

    pairs = [
        ClientPair(jsm_key="AAA", jira_key="ZZZ", client_name="Client Z"),
        ClientPair(jsm_key="ABB", jira_key="DCC", client_name="Client A"),
    ]

    assert jql_filter_for(pairs, include_mirror_side=True) == "project in (AAA, ZZZ, ABB, DCC)"


def test_allowed_project_keys_bidirectional_includes_both_sides():
    from client_pairs import ClientPair, allowed_project_keys_env_value_for

    pairs = [
        ClientPair(jsm_key="AAA", jira_key="ZZZ", client_name="Client Z"),
        ClientPair(jsm_key="ABB", jira_key="DCC", client_name="Client A"),
    ]

    assert allowed_project_keys_env_value_for(pairs, include_mirror_side=True) == "AAA,ZZZ,ABB,DCC"


def test_bidirectional_scope_defaults_to_jsm_only_for_backward_compatibility():
    """Existing Phase 3-7 callers that don't pass include_mirror_side must
    see unchanged behavior - JSM-side keys only."""
    from client_pairs import ClientPair, allowed_project_keys_env_value_for, jql_filter_for

    pairs = [ClientPair(jsm_key="AAA", jira_key="ZZZ", client_name="Client Z")]

    assert jql_filter_for(pairs) == "project in (AAA)"
    assert allowed_project_keys_env_value_for(pairs) == "AAA"


def test_bidirectional_jql_for_real_registry_includes_every_mirror_key():
    """Concrete regression check against the actual CLIENT_PAIRS: the real
    production webhook JQL (confirmed live, Aug 22) only lists JSM-side
    keys - AMC/BC/BP/CHE/GLO/KM/SCN/UOM/OUA are all currently missing, which
    is exactly why a mirror-side attachment never reaches this Lambda."""
    from client_pairs import CLIENT_PAIRS, jql_filter_for

    bidirectional_jql = jql_filter_for(CLIENT_PAIRS, include_mirror_side=True)
    for pair in CLIENT_PAIRS:
        assert pair.jsm_key in bidirectional_jql
        assert pair.jira_key in bidirectional_jql


def test_allowed_project_keys_env_value_matches_jql_source_list():
    from client_pairs import ClientPair, allowed_project_keys_env_value_for

    pairs = [
        ClientPair(jsm_key="AAA", jira_key="ZZZ", client_name="Client Z"),
        ClientPair(jsm_key="ABB", jira_key="DCC", client_name="Client A"),
    ]

    assert allowed_project_keys_env_value_for(pairs) == "AAA,ABB"


def test_rejects_duplicate_jsm_key_in_registry():
    from client_pairs import ClientPair, validate_pairs

    pairs = [
        ClientPair(jsm_key="AAA", jira_key="ZZZ", client_name="Client Z"),
        ClientPair(jsm_key="AAA", jira_key="DCC", client_name="Duplicate"),
    ]
    with pytest.raises(ValueError, match="duplicate JSM key"):
        validate_pairs(pairs)


def test_rejects_duplicate_jira_key_in_registry():
    # Two source projects both claiming to mirror into the same target
    # project is a misconfiguration, not a valid multi-tenant setup - the
    # architecture is documented as strictly one-to-one.
    from client_pairs import ClientPair, validate_pairs

    pairs = [
        ClientPair(jsm_key="AAA", jira_key="ZZZ", client_name="Client Z"),
        ClientPair(jsm_key="ABB", jira_key="ZZZ", client_name="Duplicate target"),
    ]
    with pytest.raises(ValueError, match="duplicate Jira key"):
        validate_pairs(pairs)


def test_the_registered_client_pairs_constant_itself_passes_validation():
    # The actual CLIENT_PAIRS data shipped in this module must itself be
    # internally consistent - guards against a future hand-edit introducing
    # a duplicate.
    from client_pairs import CLIENT_PAIRS, validate_pairs

    validate_pairs(CLIENT_PAIRS)  # must not raise


# --- Phase 8: production cutover -------------------------------------------
# CLIENT_PAIRS previously still held the internal TSRC/TSR2/TSR3 <-> TMIR/TMIR2/
# TMIR3 test pairs used during Phase 3-7 development. Those pairs were never
# real client data and are not part of the live MIRROR_MAP (mirror_create.py)
# used in production. This locks CLIENT_PAIRS to the 9 real, deployed pairs -
# the same set already live in mirror_create.py's MIRROR_MAP - so the JQL
# filter / ALLOWED_PROJECT_KEYS generation source matches what's actually
# running, not stale test config.


def test_client_pairs_matches_real_production_mapping():
    from client_pairs import CLIENT_PAIRS

    expected = {
        "AS": "AMC",
        "BS": "BC",
        "BSUP": "BP",
        "CS": "CHE",
        "GSP": "GLO",
        "KMS": "KM",
        "SS": "SCN",
        "UOFM": "UOM",
        "OUAS": "OUA",
    }
    actual = {pair.jsm_key: pair.jira_key for pair in CLIENT_PAIRS}
    assert actual == expected


def test_client_pairs_no_longer_contains_internal_test_pairs():
    from client_pairs import CLIENT_PAIRS

    jsm_keys = {pair.jsm_key for pair in CLIENT_PAIRS}
    jira_keys = {pair.jira_key for pair in CLIENT_PAIRS}
    assert jsm_keys.isdisjoint({"TSRC", "TSR2", "TSR3"})
    assert jira_keys.isdisjoint({"TMIR", "TMIR2", "TMIR3"})
