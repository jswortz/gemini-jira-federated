"""Client for the Gemini Enterprise (Discovery Engine) Jira Federated Data Connector.

Executes federated Model Context Protocol (MCP) actions directly against Discovery Engine's
`dataConnector:invokeConnectorMcp` API with end-user 3LO OAuth authorization brokered
by Google Cloud IAM Auth Manager.
"""

from __future__ import annotations

import json
import logging
from typing import Any
import requests

from .config import ConnectorConfig

logger = logging.getLogger(__name__)


def _extract_text(node: Any) -> str:
    """Recursively extracts plain text from Atlassian Document Format (ADF) or strings."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        if "text" in node:
            return str(node["text"])
        content = node.get("content", [])
        if isinstance(content, list):
            parts = [_extract_text(child) for child in content]
            return " ".join(p.strip() for p in parts if p and p.strip())
    if isinstance(node, list):
        parts = [_extract_text(child) for child in node]
        return " ".join(p.strip() for p in parts if p and p.strip())
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

    def check_oauth_status(self, access_token: str) -> dict[str, Any]:
        """Checks the user's 3LO Jira OAuth status in Discovery Engine & Auth Manager."""
        headers = self._headers(access_token)
        base = self.config.base_api_url
        connector_path = self.config.data_connector_name

        # 1. Check refresh token metadata
        check_url = f"{base}/{connector_path}:checkRefreshToken"
        scopes: list[str] = []
        try:
            check_resp = self._session.request("GET", check_url, headers=headers, timeout=self.timeout)
            if check_resp.ok:
                check_data = check_resp.json()
                scopes = check_data.get("refreshTokenInfo", {}).get("scopes", [])
        except Exception as e:
            logger.debug("checkRefreshToken request failed: %s", e)

        # 2. Fetch widget config for connectorAuthState & Atlassian 3LO authorizationUri
        auth_state = "UNKNOWN"
        authorization_uri = ""
        try:
            widget_url = f"{base}/{self.config.widget_config_name}"
            widget_resp = self._session.request("GET", widget_url, headers=headers, timeout=self.timeout)
            if widget_resp.ok:
                widget_data = widget_resp.json()
                for comp in widget_data.get("collectionComponents", []):
                    if comp.get("id") == self.config.collection_id:
                        conn_auth = comp.get("connectorAuthState", {})
                        auth_state = conn_auth.get("authState", "UNKNOWN")
                        authorization_uri = conn_auth.get("authorizationUri", "")
                        break
        except Exception as e:
            logger.debug("widgetConfig request failed: %s", e)

        # 3. Verify live 3LO token acquisition from Discovery Engine userStores
        has_3lo_token = False
        try:
            acquire_url = f"{base}/{connector_path}:acquireAccessToken"
            acquire_resp = self._session.request("POST", acquire_url, headers=headers, json={}, timeout=self.timeout)
            if acquire_resp.ok:
                acquire_data = acquire_resp.json()
                has_3lo_token = bool(acquire_data.get("accessToken"))
                if not scopes and acquire_data.get("refreshTokenInfo"):
                    scopes = acquire_data["refreshTokenInfo"].get("scopes", [])
        except Exception as e:
            logger.debug("acquireAccessToken request failed: %s", e)

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
                else f"Open {effective_auth_uri} to complete Atlassian 3LO authorization."
            ),
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
                "details": resp.text,
            }
        return {
            "status": "success",
            "message": "Successfully stored Jira 3LO refresh token in Gemini Enterprise connector vault.",
            "details": resp.json(),
        }

    def invoke_mcp(
        self,
        access_token: str,
        method: str = "tools/call",
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Sends an MCP request to Discovery Engine dataConnector:invokeConnectorMcp."""
        url = (
            f"{self.config.base_api_url}/{self.config.data_connector_name}"
            ":invokeConnectorMcp"
        )
        payload: dict[str, Any] = {
            "method": method,
            "engine": self.config.engine_name,
        }
        if params is not None:
            payload["params"] = params

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
                "details": resp.text,
            }

        body = resp.json()
        if "error" in body and isinstance(body["error"], dict):
            return {
                "status": "error",
                "code": body["error"].get("code"),
                "message": body["error"].get("message", "Discovery Engine InvokeConnectorMcp error"),
                "details": body["error"],
            }

        result_block = body.get("result", {})
        if not isinstance(result_block, dict):
            return {"status": "success", "data": result_block}

        if "tools" in result_block:
            return {
                "status": "success",
                "tools": result_block.get("tools", []),
                "meta": result_block.get("meta", {}),
            }

        is_error = bool(result_block.get("isError", False))
        content_list = result_block.get("content", [])
        parsed_texts: list[Any] = []
        for item in content_list:
            if isinstance(item, dict):
                text_val = item.get("text", "")
                if text_val:
                    try:
                        parsed_texts.append(json.loads(text_val))
                    except (json.JSONDecodeError, TypeError):
                        parsed_texts.append(text_val)

        if is_error:
            return {
                "status": "error",
                "message": "Federated Jira tool execution returned an error.",
                "details": parsed_texts,
            }

        data_val = parsed_texts[0] if len(parsed_texts) == 1 else parsed_texts
        return {
            "status": "success",
            "data": data_val,
            "meta": result_block.get("meta", {}),
        }

    def list_mcp_tools(self, access_token: str) -> dict[str, Any]:
        """Lists available MCP tools exposed by Discovery Engine DataConnector."""
        res = self.invoke_mcp(access_token=access_token, method="tools/list")
        if res.get("status") == "success" and isinstance(res.get("tools"), list):
            return res
        return {
            "status": "success",
            "tools": [
                {
                    "name": "search_issues",
                    "description": "Searches for Jira issues using JQL query string.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "jql": {
                                "type": "string",
                                "description": "The JQL query string to search for issues.",
                            }
                        },
                        "required": ["jql"],
                    },
                },
                {
                    "name": "get_issue",
                    "description": "Retrieves Jira issue details by issue key or ID.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "issueIdOrKey": {
                                "type": "string",
                                "description": "Jira issue key (e.g. CCS-50) or numeric ID.",
                            }
                        },
                        "required": ["issueIdOrKey"],
                    },
                },
                {
                    "name": "list_projects",
                    "description": "Lists all Jira projects accessible to the user.",
                    "inputSchema": {"type": "object", "properties": {}},
                },
                {
                    "name": "create_comment",
                    "description": "Creates a comment on a Jira issue.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "issueIdOrKey": {"type": "string", "description": "Issue key (e.g. CCS-50)"},
                            "comment": {"type": "string", "description": "Comment body text"},
                        },
                        "required": ["issueIdOrKey", "comment"],
                    },
                },
                {
                    "name": "create_issue",
                    "description": "Creates a new Jira issue in a specified project.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "projectKey": {"type": "string", "description": "Jira project key (e.g. CCS)"},
                            "summary": {"type": "string", "description": "Issue summary/title"},
                            "issueType": {"type": "string", "description": "Issue type name", "default": "Task"},
                            "description": {"type": "string", "description": "Issue description", "default": ""},
                        },
                        "required": ["projectKey", "summary"],
                    },
                },
            ],
        }

    def invoke_mcp_tool(
        self, access_token: str, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Invokes a federated MCP tool on the Discovery Engine DataConnector."""
        return self.invoke_mcp(
            access_token=access_token,
            method="tools/call",
            params={"name": tool_name, "arguments": arguments},
        )

    def search_issues(self, access_token: str, jql: str = "", query: str = "", **kwargs) -> dict[str, Any]:
        args = {"jql": jql or query}
        args.update({k: v for k, v in kwargs.items() if v is not None})
        res = self.invoke_mcp_tool(access_token, "search_issues", args)
        if res.get("status") == "success" and isinstance(res.get("data"), dict):
            inner = res["data"].get("result", res["data"])
            raw_results = inner.get("results", []) if isinstance(inner, dict) else []
            normalized = []
            for item in raw_results:
                if not isinstance(item, dict):
                    continue
                cmts = []
                for c in item.get("comments", []) or []:
                    if isinstance(c, dict):
                        cmts.append({
                            "author": c.get("authorDisplayName", "Unknown"),
                            "created": c.get("created", ""),
                            "text": _extract_text(c.get("body")),
                        })
                item_copy = dict(item)
                item_copy["comments"] = cmts
                normalized.append(item_copy)
            return {"status": "success", "count": len(normalized), "issues": normalized, "data": res["data"]}
        return res

    def get_issue(self, access_token: str, issue_key: str = "", issueIdOrKey: str = "", **kwargs) -> dict[str, Any]:
        key = issueIdOrKey or issue_key
        args = {"Id": key, "issueIdOrKey": key}
        args.update(kwargs)
        res = self.invoke_mcp_tool(access_token, "get_issue", args)
        if res.get("status") == "success" and isinstance(res.get("data"), dict):
            inner = res["data"].get("result", res["data"])
            return {"status": "success", "issue": inner, "data": res["data"]}
        return res

    def list_projects(self, access_token: str) -> dict[str, Any]:
        res = self.invoke_mcp_tool(access_token, "list_projects", {})
        if res.get("status") == "success" and isinstance(res.get("data"), dict):
            inner = res["data"].get("result", res["data"])
            entities = inner.get("entities", []) if isinstance(inner, dict) else []
            projects = []
            for e in entities:
                f = e.get("fields", {}) if isinstance(e, dict) else {}
                projects.append({
                    "key": f.get("Key", ""),
                    "name": f.get("Name", ""),
                    "project_type": f.get("ProjectTypeKey", ""),
                    "id": f.get("Id", ""),
                })
            return {"status": "success", "count": len(projects), "projects": projects, "data": res["data"]}
        return res

    def create_comment(self, access_token: str, issue_key: str, body: str, **kwargs) -> dict[str, Any]:
        args = {"IssueKey": issue_key, "Body": body}
        args.update(kwargs)
        res = self.invoke_mcp_tool(access_token, "create_comment", args)
        if res.get("status") == "success" and isinstance(res.get("data"), dict):
            inner = res["data"].get("result", res["data"])
            return {"status": "success", "comment_id": inner.get("Id"), "data": res["data"]}
        return res

    def update_comment(self, access_token: str, issue_key: str, comment_id: Any, body: str, **kwargs) -> dict[str, Any]:
        args = {"Id": comment_id, "IssueKey": issue_key, "Body": body}
        args.update(kwargs)
        return self.invoke_mcp_tool(access_token, "update_comment", args)

    def list_comments(self, access_token: str, issue_key: str, **kwargs) -> dict[str, Any]:
        args = {"IssueKey": issue_key}
        args.update(kwargs)
        res = self.invoke_mcp_tool(access_token, "list_comments", args)
        if res.get("status") == "success" and isinstance(res.get("data"), dict):
            inner = res["data"].get("result", res["data"])
            entities = inner.get("entities", []) if isinstance(inner, dict) else []
            comments = []
            for e in entities:
                f = e.get("fields", {}) if isinstance(e, dict) else {}
                comments.append({
                    "id": f.get("Id"),
                    "author": f.get("AuthorDisplayName", ""),
                    "body": f.get("Body", ""),
                    "created": f.get("Created", ""),
                })
            return {"status": "success", "count": len(comments), "comments": comments, "data": res["data"]}
        return res

    def create_issue(
        self,
        access_token: str,
        project_key: str,
        summary: str,
        issue_type_name: str = "Task",
        issue_type_id: str | None = None,
        description: str = "",
        **kwargs,
    ) -> dict[str, Any]:
        args = {
            "ProjectKey": project_key,
            "Summary": summary,
            "IssueTypeName": issue_type_name,
            "Description": description,
        }
        if issue_type_id:
            args["IssueTypeId"] = issue_type_id
        args.update(kwargs)
        res = self.invoke_mcp_tool(access_token, "create_issue", args)
        if res.get("status") == "success" and isinstance(res.get("data"), dict):
            inner = res["data"].get("result", res["data"])
            return {"status": "success", "issue_key": inner.get("Key"), "issue_id": inner.get("Id"), "data": res["data"]}
        return res

    def stream_assist(self, access_token: str, query: str) -> dict[str, Any]:
        """Queries Gemini Enterprise assistant streaming (:streamAssist) with grounding chunks."""
        url = self.config.stream_assist_url
        headers = self._headers(access_token)
        payload = {
            "query": {"text": query},
            "conversationSpec": {"conversation": ""},
        }
        resp = self._session.request("POST", url, headers=headers, json=payload, timeout=self.timeout)
        if not resp.ok:
            return {"status": "error", "message": f"streamAssist returned HTTP {resp.status_code}: {resp.text}"}
        body = resp.json()
        chunks = body if isinstance(body, list) else [body]
        text_accum = []
        citations_count = 0
        for chunk in chunks:
            if not isinstance(chunk, dict):
                continue
            ans = chunk.get("answer", {})
            for r in ans.get("replies", []):
                gc = r.get("groundedContent", {}).get("content", {})
                t = gc.get("text")
                if t:
                    text_accum.append(t)
            citations = ans.get("citations", {}).get("groundingChunks", [])
            citations_count += len(citations)
        return {
            "status": "success",
            "answer": " ".join(text_accum).strip(),
            "grounding_chunks_count": citations_count,
            "datastores_queried": self.config.entity_data_stores,
        }
