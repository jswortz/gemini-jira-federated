"""FastMCP Standard Server Bridge for Gemini Enterprise Federated Jira Connector.

Allows standard MCP clients (including google.adk.tools.mcp_tool.McpToolset with StdioConnectionParams,
Claude Desktop, Cursor, and any MCP client) to connect to Discovery Engine's Federated Jira Connector.
OAuth 3LO tokens are securely retrieved from the environment or Google Auth Manager.
"""

from __future__ import annotations

import json
from typing import Any, Optional
from mcp.server.fastmcp import FastMCP

from .auth import resolve_user_oauth_token
from .jira_connector_client import JiraFederatedConnectorClient

mcp = FastMCP("jira-federated-mcp")
client = JiraFederatedConnectorClient()


def _get_token() -> str:
    token, _ = resolve_user_oauth_token()
    if not token:
        raise ValueError(
            "No Google Cloud access token available. Please set GOOGLE_OAUTH_ACCESS_TOKEN or run with gcloud auth."
        )
    return token


@mcp.tool()
def search_issues(jql: str) -> str:
    """Searches Jira issues using a JQL query string via Gemini Enterprise Federated Connector."""
    token = _get_token()
    res = client.invoke_mcp_tool(access_token=token, tool_name="search_issues", arguments={"jql": jql})
    return json.dumps(res, indent=2)


@mcp.tool()
def get_issue(issueIdOrKey: str) -> str:
    """Retrieves full details of a Jira issue by its key (e.g. CCS-50) or numeric ID."""
    token = _get_token()
    res = client.invoke_mcp_tool(access_token=token, tool_name="get_issue", arguments={"issueIdOrKey": issueIdOrKey})
    return json.dumps(res, indent=2)


@mcp.tool()
def list_projects() -> str:
    """Lists all Jira projects accessible to the authenticated user."""
    token = _get_token()
    res = client.invoke_mcp_tool(access_token=token, tool_name="list_projects", arguments={})
    return json.dumps(res, indent=2)


@mcp.tool()
def create_comment(issueIdOrKey: str, comment: str) -> str:
    """Creates a new comment on a Jira issue."""
    token = _get_token()
    res = client.invoke_mcp_tool(
        access_token=token,
        tool_name="create_comment",
        arguments={"issueIdOrKey": issueIdOrKey, "comment": comment},
    )
    return json.dumps(res, indent=2)


@mcp.tool()
def create_issue(projectKey: str, summary: str, issueType: str = "Task", description: str = "") -> str:
    """Creates a new Jira issue in the specified project."""
    token = _get_token()
    res = client.invoke_mcp_tool(
        access_token=token,
        tool_name="create_issue",
        arguments={
            "projectKey": projectKey,
            "summary": summary,
            "issueType": issueType,
            "description": description,
        },
    )
    return json.dumps(res, indent=2)


@mcp.tool()
def check_oauth_status() -> str:
    """Checks the user's 3LO Jira OAuth status in Google Auth Manager."""
    token = _get_token()
    res = client.check_oauth_status(access_token=token)
    return json.dumps(res, indent=2)


@mcp.tool()
def complete_oauth_consent(redirect_url: str) -> str:
    """Completes the 3-Legged OAuth (3LO) consent handshake for the Jira Federated Connector using the redirect URL."""
    token = _get_token()
    res = client.complete_oauth_consent(access_token=token, full_redirect_uri=redirect_url)
    return json.dumps(res, indent=2)


if __name__ == "__main__":
    mcp.run()
