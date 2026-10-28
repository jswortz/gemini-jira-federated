"""Client for the Gemini Enterprise (Discovery Engine) Jira Federated Data Connector."""

from __future__ import annotations

import json
import logging
from typing import Any
import requests

try:
    from jira_federated_agent.config import (
        ConnectorConfig,
        build_safe_jql,
        validate_issue_key,
    )
except ImportError:
    try:
        from .config import (
            ConnectorConfig,
            build_safe_jql,
            validate_issue_key,
        )
    except ImportError:
        from config import (
            ConnectorConfig,
            build_safe_jql,
            validate_issue_key,
        )

logger = logging.getLogger(__name__)


def _extract_adf_text(node: Any) -> str:
    """Recursively extracts plain text from Atlassian Document Format (ADF) JSON."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        parts = [_extract_adf_text(child) for child in node]
        return " ".join(p for p in parts if p)
    if isinstance(node, dict):
        if node.get("type") == "text":
            return str(node.get("text", ""))
        if node.get("type") == "hardBreak":
            return "\n"
        content = node.get("content")
        if isinstance(content, list):
            parts = [_extract_adf_text(child) for child in content]
            sep = "\n" if node.get("type") in ("doc", "paragraph", "listItem") else " "
            return sep.join(p.strip() for p in parts if p and p.strip())
    return ""


class JiraFederatedConnectorClient:
    """Interacts with the Gemini Enterprise Federated Jira Connector over HTTPS."""

    def __init__(self, config: ConnectorConfig | None = None, timeout: float = 45.0):
        self.config = config or ConnectorConfig()
        self.timeout = timeout
        self._session = requests.Session()

    def _headers(self, access_token: str) -> dict[str, str]:
        if not access_token or not access_token.strip():
            raise ValueError("Missing OAuth2 access token.")
        return {
            "Authorization": f"Bearer {access_token.strip()}",
            "x-goog-user-project": self.config.project_id,
            "Content-Type": "application/json",
        }

    def _atlassian_headers(self, access_token: str) -> dict[str, str]:
        if not access_token or not access_token.strip():
            raise ValueError("Missing OAuth2 access token.")
        return {
            "Authorization": f"Bearer {access_token.strip()}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _get_atlassian_cloud_id(self, access_token: str) -> str | None:
        """Fetches accessible resources from Atlassian OAuth endpoint to find cloudId."""
        try:
            resp = self._session.get(
                "https://api.atlassian.com/oauth/token/accessible-resources",
                headers=self._atlassian_headers(access_token),
                timeout=self.timeout,
            )
            if not resp.ok:
                return None
            resources = resp.json()
            if not isinstance(resources, list) or not resources:
                return None
            target = (self.config.jira_instance_uri or "").rstrip("/")
            for r in resources:
                if isinstance(r, dict) and r.get("url", "").rstrip("/") == target:
                    return r.get("id")
            return resources[0].get("id") if isinstance(resources[0], dict) else None
        except Exception:
            return None

    def _search_issues_atlassian_rest(
        self,
        access_token: str,
        cloud_id: str,
        safe_jql: str = "",
        max_results: int = 20,
    ) -> dict[str, Any]:
        """Queries Atlassian Cloud REST API directly using an Atlassian 3LO token."""
        url = f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/search"
        params: dict[str, Any] = {
            "maxResults": max_results,
            "fields": [
                "summary",
                "status",
                "issuetype",
                "priority",
                "project",
                "assignee",
                "reporter",
                "creator",
                "created",
                "updated",
                "comment",
                "description",
            ],
        }
        if safe_jql:
            params["jql"] = safe_jql

        resp = self._session.get(
            url,
            headers=self._atlassian_headers(access_token),
            params=params,
            timeout=self.timeout,
        )
        if not resp.ok:
            return {
                "status": "error",
                "http_status": resp.status_code,
                "message": f"Atlassian Jira REST API returned HTTP {resp.status_code}.",
            }
        data = resp.json()
        raw_issues = data.get("issues", [])
        normalized: list[dict[str, Any]] = []
        for issue in raw_issues:
            if not isinstance(issue, dict):
                continue
            fields = issue.get("fields", {}) or {}
            comments_out: list[dict[str, str]] = []
            c_block = fields.get("comment", {}) or {}
            for c in c_block.get("comments", []) if isinstance(c_block, dict) else []:
                if isinstance(c, dict):
                    author = c.get("author", {}) if isinstance(c.get("author"), dict) else {}
                    comments_out.append(
                        {
                            "author": author.get("displayName", "Unknown"),
                            "created": c.get("created", ""),
                            "text": _extract_adf_text(c.get("body")),
                        }
                    )
            proj = fields.get("project", {}) if isinstance(fields.get("project"), dict) else {}
            stat = fields.get("status", {}) if isinstance(fields.get("status"), dict) else {}
            itype = fields.get("issuetype", {}) if isinstance(fields.get("issuetype"), dict) else {}
            prio = fields.get("priority", {}) if isinstance(fields.get("priority"), dict) else {}
            assignee = fields.get("assignee", {}) if isinstance(fields.get("assignee"), dict) else {}
            reporter = fields.get("reporter", {}) if isinstance(fields.get("reporter"), dict) else {}
            creator = fields.get("creator", {}) if isinstance(fields.get("creator"), dict) else {}
            key = issue.get("key", "")
            normalized.append(
                {
                    "key": key,
                    "issue_id": issue.get("id", ""),
                    "title": fields.get("summary", ""),
                    "status": stat.get("name", ""),
                    "priority": prio.get("name", ""),
                    "issue_type": itype.get("name", ""),
                    "project_key": proj.get("key", ""),
                    "project_name": proj.get("name", ""),
                    "assignee": assignee.get("displayName") or assignee.get("emailAddress") or "Unassigned",
                    "reporter": reporter.get("displayName") or reporter.get("emailAddress") or "",
                    "creator": creator.get("displayName") or creator.get("emailAddress") or "",
                    "created": fields.get("created", ""),
                    "updated": fields.get("updated", ""),
                    "description": _extract_adf_text(fields.get("description")),
                    "url": f"{self.config.jira_instance_uri.rstrip('/')}/browse/{key}",
                    "comments": comments_out,
                }
            )
        return {
            "status": "success",
            "source": "atlassian_cloud_rest",
            "jql_executed": safe_jql or "(all issues ordered by created DESC)",
            "count": len(normalized),
            "issues": normalized,
        }

    def _get_issue_atlassian_rest(
        self, access_token: str, cloud_id: str, issue_key: str
    ) -> dict[str, Any]:
        """Fetches full details of a single Jira issue directly from Atlassian Cloud REST API."""
        search_res = self._search_issues_atlassian_rest(
            access_token=access_token,
            cloud_id=cloud_id,
            safe_jql=f'key = "{issue_key}"',
            max_results=1,
        )
        if search_res.get("status") == "success" and search_res.get("issues"):
            return {
                "status": "success",
                "source": "atlassian_cloud_rest",
                "issue": search_res["issues"][0],
            }
        return {
            "status": "error",
            "message": f"Issue '{issue_key}' not found or not accessible.",
        }

    def _list_projects_atlassian_rest(
        self, access_token: str, cloud_id: str, query: str = ""
    ) -> dict[str, Any]:
        """Lists Jira projects directly from Atlassian Cloud REST API."""
        url = f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/project/search"
        params: dict[str, Any] = {"maxResults": 50}
        if query:
            params["query"] = query.strip()
        resp = self._session.get(
            url,
            headers=self._atlassian_headers(access_token),
            params=params,
            timeout=self.timeout,
        )
        if not resp.ok:
            return {
                "status": "error",
                "http_status": resp.status_code,
                "message": f"Atlassian Projects API returned HTTP {resp.status_code}.",
            }
        data = resp.json()
        raw_projs = data.get("values", [])
        normalized: list[dict[str, Any]] = []
        for p in raw_projs:
            if isinstance(p, dict):
                normalized.append(
                    {
                        "key": p.get("key", ""),
                        "name": p.get("name", ""),
                        "project_type": p.get("projectTypeKey", ""),
                        "id": p.get("id", ""),
                    }
                )
        return {
            "status": "success",
            "source": "atlassian_cloud_rest",
            "count": len(normalized),
            "projects": normalized,
        }

    def check_oauth_status(self, access_token: str) -> dict[str, Any]:
        """Checks the user's 3LO Jira OAuth status."""
        try:
            headers = self._headers(access_token)
            base = self.config.base_api_url
            connector_path = self.config.data_connector_name

            # 1. Check refresh token metadata
            check_url = f"{base}/{connector_path}:checkRefreshToken"
            check_resp = self._session.request(
                "GET", check_url, headers=headers, timeout=self.timeout
            )
            if check_resp.ok:
                check_data = check_resp.json()
                scopes = check_data.get("refreshTokenInfo", {}).get("scopes", [])

                # 2. Fetch widget config for connectorAuthState & Atlassian 3LO authorizationUri
                widget_url = f"{base}/{self.config.widget_config_name}"
                widget_resp = self._session.request(
                    "GET", widget_url, headers=headers, timeout=self.timeout
                )
                auth_state = "UNKNOWN"
                authorization_uri = ""
                if widget_resp.ok:
                    widget_data = widget_resp.json()
                    for comp in widget_data.get("collectionComponents", []):
                        if comp.get("id") == self.config.collection_id:
                            conn_auth = comp.get("connectorAuthState", {})
                            auth_state = conn_auth.get("authState", "UNKNOWN")
                            authorization_uri = conn_auth.get("authorizationUri", "")
                            break

                # 3. Verify live 3LO token acquisition from Discovery Engine userStores
                acquire_url = f"{base}/{connector_path}:acquireAccessToken"
                acquire_resp = self._session.request(
                    "POST", acquire_url, headers=headers, json={}, timeout=self.timeout
                )
                acquire_data = acquire_resp.json() if acquire_resp.ok else {}
                has_3lo_token = bool(acquire_data.get("accessToken"))
                if not scopes and acquire_data.get("refreshTokenInfo"):
                    scopes = acquire_data["refreshTokenInfo"].get("scopes", [])

                authorized = bool(has_3lo_token or auth_state == "AUTHORIZED")
                effective_auth_uri = authorization_uri or self.config.default_atlassian_auth_uri
                return {
                    "authorized": authorized,
                    "auth_state": auth_state,
                    "has_active_3lo_token": has_3lo_token,
                    "scopes": scopes,
                    "connector": connector_path,
                    "engine": self.config.engine_name,
                    "jira_instance_uri": self.config.jira_instance_uri,
                    "console_url": self.config.console_connector_url,
                    "authorization_uri": effective_auth_uri,
                    "instructions_if_unauthorized": (
                        None
                        if authorized
                        else (
                            f"Open {effective_auth_uri} to complete Atlassian 3LO authorization."
                        )
                    ),
                }
        except Exception:
            pass

        # Direct Atlassian 3LO verification
        cloud_id = self._get_atlassian_cloud_id(access_token)
        if cloud_id:
            return {
                "authorized": True,
                "auth_type": "atlassian_3lo",
                "cloud_id": cloud_id,
                "user_has_stored_refresh_token": True,
                "scopes": ["offline_access", "read:jira-user", "read:jira-work", "read:issue:jira"],
                "message": "User is authenticated with Atlassian Jira Cloud 3LO.",
            }
        return {
            "authorized": False,
            "auth_type": "atlassian_3lo",
            "user_has_stored_refresh_token": False,
            "authorization_uri": self.config.default_atlassian_auth_uri,
            "message": "Atlassian OAuth token is invalid or expired. Re-authentication required.",
        }

    def complete_oauth_consent(
        self, access_token: str, full_redirect_uri: str
    ) -> dict[str, Any]:
        """Stores the user's 3LO refresh token in Discovery Engine after OAuth redirect."""
        cleaned_uri = (full_redirect_uri or "").strip()
        if not cleaned_uri.startswith("https://"):
            raise ValueError(
                "Invalid redirect URI. Expected https://vertexaisearch.cloud.google.com/oauth-redirect?code=..."
            )
        url = (
            f"{self.config.base_api_url}/{self.config.data_connector_name}"
            ":acquireAndStoreRefreshToken"
        )
        resp = self._session.request(
            "POST",
            url,
            headers=self._headers(access_token),
            json={"fullRedirectUri": cleaned_uri},
            timeout=self.timeout,
        )
        if not resp.ok:
            return {
                "status": "error",
                "http_status": resp.status_code,
                "message": "Failed to exchange OAuth authorization code with Discovery Engine.",
            }
        return {
            "status": "success",
            "message": "Successfully stored Jira 3LO refresh token in Gemini Enterprise connector vault.",
            "details": resp.json(),
        }

    def invoke_mcp_tool(
        self, access_token: str, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Invokes a federated MCP tool on the Discovery Engine DataConnector."""
        url = (
            f"{self.config.base_api_url}/{self.config.data_connector_name}"
            ":invokeConnectorMcp"
        )
        payload = {
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
            "engine": self.config.engine_name,
        }
        resp = self._session.request(
            "POST",
            url,
            headers=self._headers(access_token),
            json=payload,
            timeout=self.timeout,
        )
        if not resp.ok:
            return {
                "status": "error",
                "http_status": resp.status_code,
                "message": f"Discovery Engine InvokeConnectorMcp returned HTTP {resp.status_code}.",
            }

        body = resp.json()
        result_block = body.get("result", {})
        is_error = bool(result_block.get("isError", False))
        content_list = result_block.get("content", [])
        parsed_texts: list[Any] = []
        for item in content_list:
            text_val = item.get("text", "")
            if text_val:
                try:
                    parsed_texts.append(json.loads(text_val))
                except json.JSONDecodeError:
                    parsed_texts.append(text_val)

        if is_error:
            return {
                "status": "error",
                "message": "Federated Jira tool execution returned an error.",
                "details": parsed_texts,
            }

        return {
            "status": "success",
            "data": parsed_texts[0] if len(parsed_texts) == 1 else parsed_texts,
            "meta": result_block.get("meta", {}),
        }

    def search_issues(
        self,
        access_token: str,
        query: str = "",
        jql: str = "",
        project_key: str = "",
        status: str = "",
        issue_type: str = "",
        max_results: int = 20,
        sort_by: str = "created DESC",
    ) -> dict[str, Any]:
        """Searches Jira issues live through the Gemini Enterprise Federated Connector."""
        safe_jql = build_safe_jql(
            query=query,
            jql=jql,
            project_key=project_key,
            status=status,
            issue_type=issue_type,
        )
        capped_results = max(1, min(int(max_results), 50))

        args: dict[str, Any] = {
            "expanded_view": False,
            "maxResults": capped_results,
            "sort_by": sort_by,
        }
        if safe_jql:
            args["query"] = safe_jql

        # 1. Try Discovery Engine Federated Connector MCP
        mcp_res = self.invoke_mcp_tool(access_token, "search_issues", args)
        if mcp_res.get("status") != "success":
            # 2. Fallback to direct Atlassian 3LO REST if token is Atlassian
            cloud_id = self._get_atlassian_cloud_id(access_token)
            if cloud_id:
                return self._search_issues_atlassian_rest(
                    access_token=access_token,
                    cloud_id=cloud_id,
                    safe_jql=safe_jql,
                    max_results=capped_results,
                )
            return mcp_res

        raw_data = mcp_res.get("data", {})
        inner_result = (
            raw_data.get("result", raw_data) if isinstance(raw_data, dict) else {}
        )
        raw_issues = (
            inner_result.get("results", [])
            if isinstance(inner_result, dict)
            else []
        )

        normalized_issues: list[dict[str, Any]] = []
        for item in raw_issues:
            if not isinstance(item, dict):
                continue
            comments_out: list[dict[str, str]] = []
            for c in item.get("comments", []) or []:
                if isinstance(c, dict):
                    comments_out.append(
                        {
                            "author": c.get("authorDisplayName", "Unknown"),
                            "created": c.get("created", ""),
                            "text": _extract_adf_text(c.get("body")),
                        }
                    )
            issue_key = item.get("key") or item.get("issue_key") or ""
            normalized_issues.append(
                {
                    "key": issue_key,
                    "issue_id": item.get("issue_id", ""),
                    "title": item.get("title", ""),
                    "status": item.get("status", ""),
                    "priority": item.get("priority", ""),
                    "issue_type": item.get("issue_type", ""),
                    "project_key": item.get("project_key", ""),
                    "project_name": item.get("project_name", ""),
                    "assignee": item.get("assignee_name")
                    or item.get("assignee_email")
                    or "Unassigned",
                    "reporter": item.get("reporter_name")
                    or item.get("reporter_email")
                    or "",
                    "creator": item.get("creator_name")
                    or item.get("creator_email")
                    or "",
                    "created": item.get("created", ""),
                    "updated": item.get("updated", ""),
                    "description": _extract_adf_text(item.get("description")),
                    "url": item.get("url")
                    or f"{self.config.jira_instance_uri}/browse/{issue_key}",
                    "comments": comments_out,
                }
            )

        return {
            "status": "success",
            "connector": self.config.data_connector_name,
            "jql_executed": safe_jql or "(all issues ordered by created DESC)",
            "count": len(normalized_issues),
            "issues": normalized_issues,
        }

    def get_issue(self, access_token: str, issue_key: str) -> dict[str, Any]:
        """Retrieves full details for a single Jira issue by key (e.g. 'GEAP-3' or 'CCS-50')."""
        valid_key = validate_issue_key(issue_key)

        # 1. First query compact/expanded search for normalized fields + comments
        search_res = self.search_issues(
            access_token=access_token,
            jql=f'key = "{valid_key}"',
            max_results=1,
        )
        if search_res.get("status") == "success" and search_res.get("issues"):
            return {
                "status": "success",
                "connector": self.config.data_connector_name,
                "issue": search_res["issues"][0],
            }

        # 2. Try direct get_issue tool
        mcp_res = self.invoke_mcp_tool(access_token, "get_issue", {"Id": valid_key})
        if mcp_res.get("status") == "success":
            return mcp_res

        # 3. Fallback to direct Atlassian 3LO REST
        cloud_id = self._get_atlassian_cloud_id(access_token)
        if cloud_id:
            return self._get_issue_atlassian_rest(
                access_token=access_token,
                cloud_id=cloud_id,
                issue_key=valid_key,
            )
        return mcp_res

    def list_projects(
        self, access_token: str, query: str = ""
    ) -> dict[str, Any]:
        """Lists or searches Jira projects accessible through the Federated Connector."""
        if query and query.strip():
            mcp_res = self.invoke_mcp_tool(
                access_token,
                "search_projects",
                {"query": query.strip(), "maxResults": 50},
            )
        else:
            mcp_res = self.invoke_mcp_tool(
                access_token, "list_projects", {"page_size": 50}
            )

        if mcp_res.get("status") != "success":
            cloud_id = self._get_atlassian_cloud_id(access_token)
            if cloud_id:
                return self._list_projects_atlassian_rest(
                    access_token=access_token,
                    cloud_id=cloud_id,
                    query=query,
                )
            return mcp_res

        raw_data = mcp_res.get("data", {})
        inner = raw_data.get("result", raw_data) if isinstance(raw_data, dict) else {}
        entities = (
            inner.get("entities")
            or inner.get("results")
            or (inner if isinstance(inner, list) else [])
        )

        projects: list[dict[str, Any]] = []
        for entry in entities:
            if not isinstance(entry, dict):
                continue
            fields = entry.get("fields", entry)
            key = fields.get("Key") or fields.get("key") or ""
            projects.append(
                {
                    "id": fields.get("Id") or fields.get("id"),
                    "key": key,
                    "name": fields.get("Name") or fields.get("name") or "",
                    "project_type": fields.get("ProjectTypeKey")
                    or fields.get("projectTypeKey")
                    or "",
                    "lead": fields.get("LeadDisplayName")
                    or fields.get("leadDisplayName")
                    or "",
                    "url": fields.get("ItemURL")
                    or f"{self.config.jira_instance_uri}/jira/software/c/projects/{key}/issues",
                }
            )

        return {
            "status": "success",
            "connector": self.config.data_connector_name,
            "count": len(projects),
            "projects": projects,
        }

    def stream_assist(
        self,
        access_token: str,
        query: str,
        data_store_specs: list[str] | None = None,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        """Queries the Gemini Enterprise native :streamAssist assistant API.

        Queries across all 10 per-entity data stores using the caller's OAuth token,
        leveraging Gemini Enterprise's built-in federated retrieval, grounding attribution
        tokens, and answer synthesis.
        """
        if not query or not query.strip():
            raise ValueError("Missing query for stream_assist.")

        # Must attach all 10 entity datastores to prevent silent zero results
        specs = [
            {"dataStore": ds}
            for ds in (data_store_specs or self.config.entity_data_stores)
        ]

        body: dict[str, Any] = {
            "query": {"parts": [{"text": query.strip()}]},
            "answerGenerationMode": "NORMAL",
            "toolsSpec": {
                "vertexAiSearchSpec": {"dataStoreSpecs": specs},
                "toolRegistry": "default_tool_registry",
            },
            "assistSkippingMode": "REQUEST_ASSIST",
            "languageCode": "en-US",
        }

        url = self.config.stream_assist_url
        resp = self._session.request(
            "POST",
            url,
            headers=self._headers(access_token),
            json=body,
            timeout=timeout,
        )

        if not resp.ok:
            return {
                "status": "error",
                "http_status": resp.status_code,
                "message": f"Discovery Engine StreamAssist returned HTTP {resp.status_code}.",
                "details": resp.text,
            }

        # Parse streaming chunks
        answer_text_parts: list[str] = []
        grounding_chunks: list[dict[str, Any]] = []

        try:
            chunks = resp.json()
            if not isinstance(chunks, list):
                chunks = [chunks]
        except Exception:
            chunks = []
            for line in resp.text.splitlines():
                line = line.strip()
                if line:
                    try:
                        chunks.append(json.loads(line))
                    except Exception:
                        pass

        for c in chunks:
            if not isinstance(c, dict):
                continue
            for reply in c.get("answer", {}).get("replies", []):
                text = (
                    reply.get("groundedContent", {})
                    .get("content", {})
                    .get("text", "")
                )
                if text:
                    answer_text_parts.append(text)
            for chunk in (
                c.get("answer", {}).get("citations", {}).get("groundingChunks", [])
                or []
            ):
                if isinstance(chunk, dict):
                    grounding_chunks.append(chunk)

        return {
            "status": "success",
            "query": query.strip(),
            "answer": "".join(answer_text_parts),
            "grounding_chunks_count": len(grounding_chunks),
            "grounding_chunks": grounding_chunks,
            "datastores_queried": [s["dataStore"] for s in specs],
        }
