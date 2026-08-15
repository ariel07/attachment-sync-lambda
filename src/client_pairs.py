"""Client-pair registry - single source of truth for JSM<->Jira project pairs.

See tests/test_phase5b_client_pairs.py module docstring for full design
rationale. This is a documentation/tooling source of truth for humans
keeping the webhook's JQL filter and the deployed ALLOWED_PROJECT_KEYS value
in sync - it is NOT read at runtime by handler.py/lambda_handler(). The
Lambda's actual runtime behavior is still driven only by the deployed
ALLOWED_PROJECT_KEYS env var (see project_scope.py), same as Phase 5.

To onboard a new pair:
  1. Add a ClientPair entry below.
  2. Run jql_filter_for(CLIENT_PAIRS) and paste the result into the Jira
     webhook's JQL filter (Settings > System > WebHooks).
  3. Run allowed_project_keys_env_value_for(CLIENT_PAIRS) and set it as the
     AllowedProjectKeys SAM parameter, then `sam deploy`.
  4. Complete the rest of the checklist in
     docs/phase5-scaling-to-additional-pairs.md (native automation rules,
     service-account permissions, etc. - out of scope for this module).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ClientPair:
    """One JSM<->Jira Software project pair.

    jsm_key: the JSM (service desk) project key - what the webhook/JQL
      filter and ALLOWED_PROJECT_KEYS scope on.
    jira_key: the paired Jira Software (Kanban) project key - never
      referenced by the webhook, JQL filter, or ALLOWED_PROJECT_KEYS;
      resolved at runtime per-issue via the "JSM Mirror" link instead (see
      jsm_mirror_link.py). Kept here purely for documentation/traceability
      of which pairs exist.
    client_name: human-readable label, for humans reading this file only -
      not used in any generated JQL/env value.
    """

    jsm_key: str
    jira_key: str
    client_name: str


# The registered pairs. JTT/JJST is the internal test pair; production
# client pairs are added here as they're onboarded (see docs/phase5-
# scaling-to-additional-pairs.md for the full per-pair checklist beyond
# just this registry entry).
CLIENT_PAIRS: list[ClientPair] = [
    ClientPair(jsm_key="JTT", jira_key="JJST", client_name="iCXeed internal test pair"),
    ClientPair(jsm_key="JT2", jira_key="JJST2", client_name="iCXeed internal test pair 2"),
    ClientPair(jsm_key="JT3", jira_key="JJST3", client_name="iCXeed internal test pair 3"),
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


def jql_filter_for(pairs: list[ClientPair]) -> str:
    """Return the JQL filter string to paste into the Jira webhook config.

    Raises ValueError on an empty pairs list - an empty JQL filter would
    match every project on the site, which is never the intended state.
    """
    if not pairs:
        raise ValueError("pairs must not be empty")
    validate_pairs(pairs)
    keys = ", ".join(pair.jsm_key for pair in pairs)
    return f"project in ({keys})"


def allowed_project_keys_env_value_for(pairs: list[ClientPair]) -> str:
    """Return the comma-separated value for the AllowedProjectKeys SAM
    parameter / ALLOWED_PROJECT_KEYS env var, generated from the same list
    used for jql_filter_for() - the two are guaranteed to match because
    they're derived from one input, not maintained by hand in two places.
    """
    if not pairs:
        raise ValueError("pairs must not be empty")
    validate_pairs(pairs)
    return ",".join(pair.jsm_key for pair in pairs)


if __name__ == "__main__":
    # Run directly (`python src/client_pairs.py`) to print the two values
    # to paste into the Jira webhook JQL filter and the AllowedProjectKeys
    # SAM parameter after adding/removing a ClientPair entry above.
    validate_pairs(CLIENT_PAIRS)
    print(f"JQL filter:\n  {jql_filter_for(CLIENT_PAIRS)}\n")
    print(f"AllowedProjectKeys:\n  {allowed_project_keys_env_value_for(CLIENT_PAIRS)}")
