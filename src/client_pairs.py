"""Client-pair registry - single source of truth for JSM<->Jira project pairs.

See tests/test_phase5b_client_pairs.py module docstring for full design
rationale. This is a documentation/tooling source of truth for humans
keeping the webhook's JQL filter and the deployed ALLOWED_PROJECT_KEYS value
in sync - it is NOT read at runtime by handler.py/lambda_handler(). The
Lambda's actual runtime behavior is still driven only by the deployed
ALLOWED_PROJECT_KEYS env var (see project_scope.py), same as Phase 5.

PHASE 8 UPDATE: as of bidirectional attachment sync, the mirror (Jira
Software) side is no longer out of scope for the webhook/JQL filter -
attachment_sync.sync_new_attachment() now resolves the link in either
direction, so an attachment added directly to a mirror ticket needs the
webhook to fire for the mirror project too, or it never reaches this Lambda.
jql_filter_for()/allowed_project_keys_env_value_for() take an
include_mirror_side flag for this - default False preserves the original
JSM-only scope for any existing caller.

To onboard a new pair:
  1. Add a ClientPair entry below.
  2. Run jql_filter_for(CLIENT_PAIRS, include_mirror_side=True) and paste
     the result into the Jira webhook's JQL filter (Settings > System >
     WebHooks) - include_mirror_side=True, not the old JSM-only default,
     so both directions of attachment sync actually get triggered.
  3. Run allowed_project_keys_env_value_for(CLIENT_PAIRS,
     include_mirror_side=True) and set it as the AllowedProjectKeys SAM
     parameter, then `sam deploy`.
  4. Complete the rest of the checklist in
     docs/phase5-scaling-to-additional-pairs.md (native automation rules,
     service-account permissions, etc. - out of scope for this module).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ClientPair:
    """One JSM<->Jira Software project pair.

    jsm_key: the JSM (service desk) project key - always in scope for the
      webhook/JQL filter and ALLOWED_PROJECT_KEYS.
    jira_key: the paired Jira Software (Kanban) project key. Through Phase
      7, never referenced by the webhook, JQL filter, or
      ALLOWED_PROJECT_KEYS (resolved at runtime per-issue via the "JSM
      Mirror" link instead - see jsm_mirror_link.py). As of Phase 8
      (bidirectional attachment sync), this key ALSO needs to be in the
      webhook/allowlist scope - see jql_filter_for()'s include_mirror_side
      parameter - so a mirror-side attachment's webhook delivery isn't
      filtered out before it ever reaches the Lambda.
    client_name: human-readable label, for humans reading this file only -
      not used in any generated JQL/env value.
    """

    jsm_key: str
    jira_key: str
    client_name: str


# The registered pairs - the 9 real, live production client pairs (Phase 8
# cutover). Matches the same set already deployed in mirror_create.py's
# MIRROR_MAP; kept as two lists (not one shared constant) deliberately -
# this module is JQL/allowlist-focused documentation, MIRROR_MAP is
# routing/epic config, and they answer different questions even though the
# underlying pairs are the same. The internal TSRC/TSR2/TSR3 <-> TMIR/TMIR2/
# TMIR3 test pairs used during Phase 3-7 development have been retired from
# this registry - they were never real client data and were not part of
# MIRROR_MAP.
CLIENT_PAIRS: list[ClientPair] = [
    ClientPair(jsm_key="AS", jira_key="AMC", client_name="AMC"),
    ClientPair(jsm_key="BS", jira_key="BC", client_name="Bellonacare"),
    ClientPair(jsm_key="BSUP", jira_key="BP", client_name="Bupa"),
    ClientPair(jsm_key="CS", jira_key="CHE", client_name="Chelsea"),
    ClientPair(jsm_key="GSP", jira_key="GLO", client_name="GlobalPay"),
    ClientPair(jsm_key="KMS", jira_key="KM", client_name="Kip McGrath"),
    ClientPair(jsm_key="SS", jira_key="SCN", client_name="Scene to Believe"),
    ClientPair(jsm_key="UOFM", jira_key="UOM", client_name="University of Melbourne"),
    ClientPair(jsm_key="OUAS", jira_key="OUA", client_name="Open University Australia"),
]


def validate_pairs(pairs: list[ClientPair]) -> None:
    """Raise ValueError if the registry is internally inconsistent.

    Checks both directions of the documented one-to-one constraint: no JSM
    key registered twice, and no Jira key claimed by more than one JSM key
    (the architecture is one-to-one per userMemories - two source projects
    both mirroring into the same target is a misconfiguration, not a valid
    setup).
    """
    jsm_keys = [pair.jsm_key for pair in pairs]
    seen_jsm: set[str] = set()
    for key in jsm_keys:
        if key in seen_jsm:
            raise ValueError(f"duplicate JSM key in registry: {key!r}")
        seen_jsm.add(key)

    jira_keys = [pair.jira_key for pair in pairs]
    seen_jira: set[str] = set()
    for key in jira_keys:
        if key in seen_jira:
            raise ValueError(f"duplicate Jira key in registry: {key!r}")
        seen_jira.add(key)


def _keys_for(pairs: list[ClientPair], include_mirror_side: bool) -> list[str]:
    """Shared key-list builder for jql_filter_for/allowed_project_keys_env_value_for.

    include_mirror_side=False (default): JSM-side keys only - unchanged
    Phase 3-7 behavior/scope.
    include_mirror_side=True (Phase 8): both sides, interleaved per pair
    (jsm_key then jira_key) so the generated list stays readable pair-by-
    pair rather than all-JSM-then-all-Jira. Needed because
    attachment_sync.sync_new_attachment now tries both link directions
    (see src/attachment_sync.py) - the webhook itself must fire for the
    mirror project too, or a mirror-side attachment never reaches this
    Lambda at all. See tests/test_phase5b_client_pairs.py for the concrete
    regression check against the real, currently-deployed webhook JQL.
    """
    if include_mirror_side:
        keys: list[str] = []
        for pair in pairs:
            keys.append(pair.jsm_key)
            keys.append(pair.jira_key)
        return keys
    return [pair.jsm_key for pair in pairs]


def jql_filter_for(pairs: list[ClientPair], include_mirror_side: bool = False) -> str:
    """Return the JQL filter string to paste into the Jira webhook config.

    Raises ValueError on an empty pairs list - an empty JQL filter would
    match every project on the site, which is never the intended state.
    """
    if not pairs:
        raise ValueError("pairs must not be empty")
    validate_pairs(pairs)
    keys = ", ".join(_keys_for(pairs, include_mirror_side))
    return f"project in ({keys})"


def allowed_project_keys_env_value_for(
    pairs: list[ClientPair], include_mirror_side: bool = False
) -> str:
    """Return the comma-separated value for the AllowedProjectKeys SAM
    parameter / ALLOWED_PROJECT_KEYS env var, generated from the same list
    used for jql_filter_for() - the two are guaranteed to match because
    they're derived from one input, not maintained by hand in two places.
    """
    if not pairs:
        raise ValueError("pairs must not be empty")
    validate_pairs(pairs)
    return ",".join(_keys_for(pairs, include_mirror_side))


if __name__ == "__main__":
    # Run directly (`python src/client_pairs.py`) to print the values to
    # paste into the Jira webhook JQL filter and the AllowedProjectKeys SAM
    # parameter after adding/removing a ClientPair entry above.
    validate_pairs(CLIENT_PAIRS)
    print(f"JQL filter (JSM-side only, Phase 3-7 scope):\n  {jql_filter_for(CLIENT_PAIRS)}\n")
    print(
        "JQL filter (bidirectional, Phase 8 - use this one):\n  "
        f"{jql_filter_for(CLIENT_PAIRS, include_mirror_side=True)}\n"
    )
    print(
        f"AllowedProjectKeys (JSM-side only):\n"
        f"  {allowed_project_keys_env_value_for(CLIENT_PAIRS)}\n"
    )
    print(
        "AllowedProjectKeys (bidirectional, Phase 8 - use this one):\n  "
        f"{allowed_project_keys_env_value_for(CLIENT_PAIRS, include_mirror_side=True)}"
    )
