"""Thin Jira REST API v3 client for the attachment-sync Lambda.

Deliberately minimal: only the operations this Lambda needs (get issue
fields, download attachment content, upload attachment, delete attachment,
create issue, create issue link). Not a general-purpose Jira SDK.

Endpoints and requirements verified against official Atlassian docs (fetched
live during Phase 3, not from training memory):
  https://developer.atlassian.com/cloud/jira/platform/rest/v3/
  https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-attachments/

create_issue/create_issue_link added to support mirror_create.py, replacing
the native "Auto-create mirror" automation rule's Create + Branch + Link
steps (Branch step confirmed unreliable - see mirror_create.py docstring).

description field on create_issue uses Atlassian Document Format (ADF), not
a plain string - confirmed live (Aug 19) after a real 400 Bad Request when
a plain string was sent. Jira API v3's rich-text fields (description,
comment body, etc.) all require ADF; this repo's other methods never hit
this because none of them set description on create before now.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 25  # stays under typical Lambda timeout budgets


class _HttpSession(Protocol):
    """Structural type for the session dependency - satisfied by both
    requests.Session and the FakeSession used in tests. No inheritance
    required, just matching method signatures (duck typing, explicitly
    documented rather than implicit)."""

    def get(self, url: str, **kwargs: Any) -> Any: ...
    def post(self, url: str, **kwargs: Any) -> Any: ...
    def delete(self, url: str, **kwargs: Any) -> Any: ...


def _raise_for_status_with_body_logged(response: Any, context: str) -> None:
    """Wraps response.raise_for_status(), logging the response body first.

    Added after a real 400 Bad Request (Aug 19) came through CloudWatch with
    no detail beyond "400 Client Error: Bad Request for url: ..." - the
    actual reason (an ADF-format violation) had to be guessed rather than
    read, since raise_for_status() alone discards the response body. This
    wrapper is used by the two mirror-creation methods only (create_issue,
    create_issue_link) - the four pre-existing methods are left untouched,
    matching their original behavior exactly.
    """
    if response.status_code >= 400:
        logger.error(
            "%s failed: HTTP %s | response body: %s",
            context,
            response.status_code,
            getattr(response, "text", "<no body captured>"),
        )
    response.raise_for_status()


class JiraClient:
    def __init__(
        self,
        base_url: str,
        email: str,
        api_token: str,
        session: _HttpSession | None = None,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._auth = (email, api_token)
        self._timeout = timeout
        if session is not None:
            self._session = session
        else:
            # Imported lazily so this module can be unit-tested without
            # requests installed at all, if a caller only exercises the
            # injected-session path.
            import requests

            self._session = requests.Session()

    def get_issue(self, issue_key: str, fields: list[str]) -> dict[str, Any]:
        """GET /rest/api/3/issue/{key}?fields=field1,field2,..."""
        url = f"{self.base_url}/rest/api/3/issue/{issue_key}"
        response = self._session.get(
            url,
            auth=self._auth,
            params={"fields": ",".join(fields)},
            timeout=self._timeout,
        )
        response.raise_for_status()
        return response.json()

    def delete_attachment(self, attachment_id: str) -> None:
        """DELETE /rest/api/3/attachment/{id}

        Removes an attachment by id. Confirmed against official Atlassian
        docs (Phase 6): 204 No Content on success (empty body - nothing to
        return), 403 if attachments are disabled or the caller lacks
        delete permission on the containing project, 404 if the id doesn't
        exist or isn't accessible. All non-2xx responses are surfaced via
        raise_for_status(), same convention as every other method on this
        client - this method does not decide whether a 404 should be
        treated as an idempotent no-op; that policy decision belongs to the
        caller (see docs/phase6-attachment-delete-sync.md, open
        question #4).
        """
        url = f"{self.base_url}/rest/api/3/attachment/{attachment_id}"
        response = self._session.delete(
            url,
            auth=self._auth,
            timeout=self._timeout,
        )
        response.raise_for_status()
        return None

    def download_attachment(self, content_url: str) -> bytes:
        """GET the attachment's `content` URL (from fields.attachment[].content).
        Returns raw bytes - caller is responsible for re-uploading them."""
        response = self._session.get(
            content_url,
            auth=self._auth,
            timeout=self._timeout,
        )
        response.raise_for_status()
        return response.content

    def upload_attachment(
        self,
        issue_key: str,
        filename: str,
        content: bytes,
        mime_type: str,
    ) -> Any:
        """POST /rest/api/3/issue/{key}/attachments

        Requires X-Atlassian-Token: no-check (documented XSRF-bypass header
        for this endpoint) and multipart/form-data with field name "file" -
        both confirmed from official docs, not inferred.
        """
        url = f"{self.base_url}/rest/api/3/issue/{issue_key}/attachments"
        response = self._session.post(
            url,
            auth=self._auth,
            headers={"X-Atlassian-Token": "no-check"},
            files={"file": (filename, content, mime_type)},
            timeout=self._timeout,
        )
        response.raise_for_status()
        return response.json()

    def create_issue(
        self,
        project_id: str,
        issuetype_id: str,
        summary: str,
        description: str = "",
        parent_key: str | None = None,
        account_field_id: str | None = None,
        account_option_id: str | None = None,
    ) -> str:
        """POST /rest/api/3/issue - creates an issue, returns its key.

        description is converted to Atlassian Document Format (ADF) when
        non-empty, and OMITTED entirely when empty - Jira API v3 rejects a
        plain string here with a 400 (confirmed live, Aug 19). See module
        docstring.

        account_field_id/account_option_id are optional since not every
        target project has the Tempo Account custom field (e.g. JJST-family
        test projects don't - confirmed via getJiraIssueTypeMetaWithFields).
        parent_key is optional for the same reason (test targets don't
        require an epic parent).
        """
        fields: dict[str, object] = {
            "project": {"id": project_id},
            "issuetype": {"id": issuetype_id},
            "summary": summary,
        }
        if description:
            fields["description"] = {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": description}],
                    }
                ],
            }
        if parent_key:
            fields["parent"] = {"key": parent_key}
        if account_field_id and account_option_id:
            fields[account_field_id] = {"id": account_option_id}

        url = f"{self.base_url}/rest/api/3/issue"
        response = self._session.post(
            url,
            auth=self._auth,
            json={"fields": fields},
            timeout=self._timeout,
        )
        _raise_for_status_with_body_logged(response, f"create_issue(project_id={project_id})")
        return response.json()["key"]

    def create_issue_link(
        self,
        link_type_id: str,
        inward_issue_key: str,
        outward_issue_key: str,
    ) -> None:
        """POST /rest/api/3/issueLink

        outward_issue_key is the issue described by the link type's OUTWARD
        label. Confirmed live against KM-225's real issuelinks: KM-225
        (Jira Software side) uses the outward label "mirrors"; JTT-106 (JSM
        side) uses the inward label "is mirrored by".
        """
        url = f"{self.base_url}/rest/api/3/issueLink"
        response = self._session.post(
            url,
            auth=self._auth,
            json={
                "type": {"id": link_type_id},
                "inwardIssue": {"key": inward_issue_key},
                "outwardIssue": {"key": outward_issue_key},
            },
            timeout=self._timeout,
        )
        _raise_for_status_with_body_logged(
            response, f"create_issue_link({inward_issue_key} <-> {outward_issue_key})"
        )
        return None
