"""Config-driven mirror issue creation + linking.

Replaces the native "Auto-create mirror" automation rule's Create + Branch +
Link steps, which were confirmed (Aug 17-19, live testing) to intermittently
fail at the Branch step - 100% reproducible on new blocks (GLO, CHE, SCN,
JJST), root cause unconfirmed but consistent with a Jira Cloud search-index
dependency the Branch step relies on. This module avoids that dependency
entirely: create_issue() returns the new key directly from the API response,
so there's no search/lookup step to race against.

JSM_MIRROR_LINK_TYPE_ID = "10012".

TEST CONFIGURATION: mapped to the JJST-family test pair (client_pairs.py's
existing test registry), not production KM/BP/BC, until this replacement
path is validated end-to-end. Swap MIRROR_MAP to the KM/BP/BC values (kept
in comments below) once confirmed reliable.
"""

from __future__ import annotations

from typing import Any, TypedDict

JSM_MIRROR_LINK_TYPE_ID = "10012"


class MirrorTarget(TypedDict, total=False):
    target_project_id: str
    task_issuetype_id: str
    sr_epic_key: str  # used when source issuetype == "Service Request"
    bf_epic_key: str  # used otherwise, if the client splits SR/BF
    flat_epic_key: str  # used instead of sr/bf split, if the client has one epic
    account_field_id: str  # customfield_10108 - omit entirely for targets without it
    account_option_id: str


# --- TEST CONFIG: JTT/JT2/JT3 -> JJST/JJST2/JJST3 ---
# No epic parent, no Account field - confirmed via getJiraIssueTypeMetaWithFields
# that JJST doesn't have customfield_10108 configured, and parent isn't required.
MIRROR_MAP: dict[str, MirrorTarget] = {
    "JTT": {
        "target_project_id": "12719",  # JJST
        "task_issuetype_id": "11440",  # JJST's own Task ID (team-managed project)
    },
    "JT2": {
        "target_project_id": "12720",  # JJST2
        "task_issuetype_id": "11446",
    },
    "JT3": {
        "target_project_id": "12721",  # JJST3
        "task_issuetype_id": "11452",
    },
}

# --- PRODUCTION CONFIG (KM/BP/BC) - swap in once JJST test path is confirmed ---
# MIRROR_MAP: dict[str, MirrorTarget] = {
#     "JTT": {
#         "target_project_id": "11313",       # KM
#         "task_issuetype_id": "10121",
#         "sr_epic_key": "KM-178",
#         "bf_epic_key": "KM-179",
#         "account_field_id": "customfield_10108",
#         "account_option_id": "3",
#     },
#     "JT2": {
#         "target_project_id": "11279",       # BP
#         "task_issuetype_id": "10121",
#         "sr_epic_key": "BP-150",
#         "bf_epic_key": "BP-151",
#         "account_field_id": "customfield_10108",
#         "account_option_id": "2",
#     },
#     "JT3": {
#         "target_project_id": "11447",       # BC
#         "task_issuetype_id": "10121",
#         "flat_epic_key": "BC-33",
#         "account_field_id": "customfield_10108",
#         "account_option_id": "36",
#     },
# }


def resolve_epic(cfg: MirrorTarget, source_issuetype_name: str) -> str | None:
    """Picks the right parent epic for this ticket, or None if the target
    doesn't use epic parenting at all (current case for JJST-family test
    targets - none of the epic keys are set)."""
    if "flat_epic_key" in cfg:
        return cfg["flat_epic_key"]
    if source_issuetype_name == "Service Request":
        return cfg.get("sr_epic_key")
    return cfg.get("bf_epic_key")


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
        # DIRECTION NOTE (Aug 19, real test JTT-114/JJST-9): empirically
        # confirmed that new_key must be passed as inward_issue_key, and
        # source_issue_key as outward_issue_key, for
        # jsm_mirror_link.find_mirror_issue_key() to successfully find the
        # link from the JSM-ticket side afterward. This is the OPPOSITE of
        # what the link type's own inward/outward LABEL TEXT would suggest
        # ("is mirrored by" is shown on the JSM ticket, which reads like
        # JSM should be inward) - the label text describes UI display
        # wording, not the API's inwardIssue/outwardIssue field semantics.
        # Matching the pre-existing, already-working consumer's actual
        # contract (jsm_mirror_link.py) was treated as authoritative over
        # the "expected" reading of the label text or general API docs.
        inward_issue_key=new_key,  # Jira Software side
        outward_issue_key=source_issue_key,  # JSM side
    )

    return new_key
