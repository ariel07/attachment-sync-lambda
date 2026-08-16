"""Thin Jira REST API v3 client for the attachment-sync Lambda.

Deliberately minimal: only the three operations this Lambda needs (get
issue fields, download attachment content, upload attachment). Not a
general-purpose Jira SDK.

Endpoints and requirements verified against official Atlassian docs (fetched
live during Phase 3, not from training memory):
  https://developer.atlassian.com/cloud/jira/platform/rest/v3/
  https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-attachments/
"""

from __future__ import annotations

from typing import Any, Protocol

DEFAULT_TIMEOUT_SECONDS = 25  # stays under typical Lambda timeout budgets


class _HttpSession(Protocol):
    """Structural type for the session dependency - satisfied by both
    requests.Session and the FakeSession used in tests. No inheritance
    required, just matching method signatures (duck typing, explicitly
    documented rather than implicit)."""

    def get(self, url: str, **kwargs: Any) -> Any: ...
    def post(self, url: str, **kwargs: Any) -> Any: ...
    def delete(self, url: str, **kwargs: Any) -> Any: ...


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
