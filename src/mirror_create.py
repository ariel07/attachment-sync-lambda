"""Config-driven mirror issue creation + linking.

Replaces the native "Auto-create mirror" automation rule's Create + Branch +
Link steps
"""

from __future__ import annotations

from typing import Any, TypedDict

JSM_MIRROR_LINK_TYPE_ID = "10012"


class MirrorTarget(TypedDict, total=False):
    target_project_id: str
    task_issuetype_id: str
    sr_epic_key: str  # source issuetype == "Service Request"
    bf_epic_key: str  # source issuetype == "Incident Request" ("Break/Fix")
    cr_epic_key: str  # source issuetype == "Change Request"
    account_field_id: str  # customfield_10108
    account_option_id: str


# Source JSM project key -> mirror target config. Source project IDs
# (all confirmed via getVisibleJiraProjects, Aug 19):
#   AS=10982  BS=10988  BSUP=11281  CS=10986  GSP=10990
#   KMS=10981  SS=10987  UOFM=10991  OUAS=11577
MIRROR_MAP: dict[str, MirrorTarget] = {
    "AS": {  # -> AMC (AAMC)
        "target_project_id": "11378",
        "task_issuetype_id": "10121",
        "sr_epic_key": "AMC-393",
        "bf_epic_key": "AMC-394",
        "cr_epic_key": "AMC-395",
        "account_field_id": "customfield_10108",
        "account_option_id": "34",
    },
    "BS": {  # -> BC (Bellonacare)
        "target_project_id": "11447",
        "task_issuetype_id": "10121",
        "sr_epic_key": "BC-36",
        "bf_epic_key": "BC-37",
        "cr_epic_key": "BC-38",
        "account_field_id": "customfield_10108",
        "account_option_id": "36",
    },
    "BSUP": {  # -> BP (Bupa)
        "target_project_id": "11279",
        "task_issuetype_id": "10121",
        "sr_epic_key": "BP-150",
        "bf_epic_key": "BP-151",
        "cr_epic_key": "BP-168",
        "account_field_id": "customfield_10108",
        "account_option_id": "2",
    },
    "CS": {  # -> CHE (Chelsea)
        "target_project_id": "11311",
        "task_issuetype_id": "10121",
        "sr_epic_key": "CHE-89",
        "bf_epic_key": "CHE-99",
        "cr_epic_key": "CHE-124",
        "account_field_id": "customfield_10108",
        "account_option_id": "7",
    },
    "GSP": {  # -> GLO (GlobalPay)
        "target_project_id": "11316",
        "task_issuetype_id": "10121",
        "sr_epic_key": "GLO-228",
        "bf_epic_key": "GLO-229",
        "cr_epic_key": "GLO-232",
        "account_field_id": "customfield_10108",
        "account_option_id": "1",
    },
    "KMS": {  # -> KM (Kip McGrath)
        "target_project_id": "11313",
        "task_issuetype_id": "10121",
        "sr_epic_key": "KM-178",
        "bf_epic_key": "KM-179",
        "cr_epic_key": "KM-231",
        "account_field_id": "customfield_10108",
        "account_option_id": "3",
    },
    "SS": {  # -> SCN (Scene to Believe/STB)
        "target_project_id": "11312",
        "task_issuetype_id": "10121",
        "sr_epic_key": "SCN-442",
        "bf_epic_key": "SCN-443",
        "cr_epic_key": "SCN-470",
        "account_field_id": "customfield_10108",
        "account_option_id": "5",
    },
    "UOFM": {  # -> UOM (University of Melbourne)
        "target_project_id": "11345",
        "task_issuetype_id": "10121",
        "sr_epic_key": "UOM-420",
        "bf_epic_key": "UOM-272",
        "cr_epic_key": "UOM-421",
        "account_field_id": "customfield_10108",
        "account_option_id": "26",
    },
    "OUAS": {  # -> OUA (Open University Australia)
        "target_project_id": "11610",
        "task_issuetype_id": "10121",
        "sr_epic_key": "OUA-316",
        "bf_epic_key": "OUA-315",
        "cr_epic_key": "OUA-317",
        "account_field_id": "customfield_10108",
        "account_option_id": "41",
    },
}


def resolve_epic(cfg: MirrorTarget, source_issuetype_name: str) -> str | None:
    """Three-way match on the source ticket's issue type. Returns None
    (no parent set, rather than guessing) for any issue type outside the
    three confirmed categories - safer than silently defaulting to one
    category for an unexpected type."""
    if source_issuetype_name == "Service Request":
        return cfg.get("sr_epic_key")
    if source_issuetype_name == "Incident Request":
        return cfg.get("bf_epic_key")
    if source_issuetype_name == "Change Request":
        return cfg.get("cr_epic_key")
    return None


def create_mirror(
    jira_client: Any,
    source_issue_key: str,
    source_project_key: str,
    source_issuetype_name: str,
    summary: str,
    description: str = "",
) -> str | None:
    """Creates the mirror issue and links it back to the source, in one
    synchronous call chain - no search/branch step, no race condition.

    Returns the new mirror issue's key, or None if source_project_key isn't
    configured in MIRROR_MAP (not an error - just not a mirrored project).

    Idempotency: caller is responsible for checking whether source_issue_key
    already has a JSM Mirror link before calling this, to guard against the
    webhook's confirmed double-fire behavior.
    """
    cfg = MIRROR_MAP.get(source_project_key)
    if cfg is None:
        return None

    epic_key = resolve_epic(cfg, source_issuetype_name)

    new_key = jira_client.create_issue(
        project_id=cfg["target_project_id"],
        issuetype_id=cfg["task_issuetype_id"],
        summary=summary,
        description=description,
        parent_key=epic_key,
        account_field_id=cfg.get("account_field_id"),
        account_option_id=cfg.get("account_option_id"),
    )

    jira_client.create_issue_link(
        link_type_id=JSM_MIRROR_LINK_TYPE_ID,
        # DIRECTION NOTE (Aug 19, real test TSRC-114/TMIR-9): empirically
        # confirmed that new_key must be passed as inward_issue_key, and
        # source_issue_key as outward_issue_key, for
        # jsm_mirror_link.find_mirror_issue_key() to successfully find the
        # link from the JSM-ticket side afterward. Opposite of what the
        # link type's own label text would suggest.
        inward_issue_key=new_key,
        outward_issue_key=source_issue_key,
    )

    return new_key
