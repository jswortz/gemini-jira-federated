"""ADK RAG Agent over the Gemini Enterprise Jira Federated Data Connector.

Uses google.adk.tools.mcp_tool.McpToolset to connect directly to the Jira MCP server,
executing federated Model Context Protocol (MCP) actions against Discovery Engine's
dataConnector:invokeConnectorMcp endpoint.
End-user Atlassian 3-Legged OAuth (3LO) tokens are securely brokered by Google Cloud IAM Auth Manager.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters

from .auth import configure_vertex_ai_user_credentials, resolve_user_oauth_token
from .config import ConnectorConfig
from .jira_connector_client import JiraFederatedConnectorClient
from .mcp_toolset import DiscoveryEngineMcpToolset

logger = logging.getLogger(__name__)

# Bridge google.auth.default() in memory to the configured OAuth user account
_CONFIG = ConnectorConfig()
configure_vertex_ai_user_credentials(
    account=_CONFIG.oauth_user_account,
    project_id=_CONFIG.project_id,
)
_CLIENT = JiraFederatedConnectorClient(config=_CONFIG)


def get_jira_mcp_toolset() -> McpToolset | DiscoveryEngineMcpToolset:
    """Returns the Jira MCP toolset.

    Uses the built-in google.adk.tools.mcp_tool.McpToolset with StdioConnectionParams
    by default, connecting to the FastMCP server that proxies to Discovery Engine invokeConnectorMcp.
    If JIRA_MCP_TRANSPORT='inprocess', returns the in-process DiscoveryEngineMcpToolset.
    """
    transport = os.getenv("JIRA_MCP_TRANSPORT", "builtin").lower()
    if transport == "inprocess":
        return DiscoveryEngineMcpToolset(client=_CLIENT)
    return McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command=sys.executable,
                args=["-m", "jira_federated_agent.mcp_server"],
            ),
            timeout=30,
        )
    )


# Built-in google.adk.tools.mcp_tool.McpToolset
jira_toolset = get_jira_mcp_toolset()


# Programmatic convenience functions
def check_jira_oauth_status() -> dict[str, Any]:
    token, _ = resolve_user_oauth_token(account=_CONFIG.oauth_user_account, project_id=_CONFIG.project_id)
    return _CLIENT.check_oauth_status(access_token=token or "")


def complete_jira_oauth_consent(redirect_url: str) -> dict[str, Any]:
    token, _ = resolve_user_oauth_token(account=_CONFIG.oauth_user_account, project_id=_CONFIG.project_id)
    return _CLIENT.complete_oauth_consent(access_token=token or "", full_redirect_uri=redirect_url)


def search_jira_issues(query: str = "", jql: str = "", max_results: int = 20, **kwargs) -> dict[str, Any]:
    token, _ = resolve_user_oauth_token()
    return _CLIENT.search_issues(access_token=token or "", jql=jql, query=query, max_results=max_results, **kwargs)


def get_jira_issue(issue_key: str) -> dict[str, Any]:
    token, _ = resolve_user_oauth_token()
    return _CLIENT.get_issue(access_token=token or "", issue_key=issue_key)


def list_jira_projects() -> dict[str, Any]:
    token, _ = resolve_user_oauth_token()
    return _CLIENT.list_projects(access_token=token or "")


def create_jira_comment(issue_key: str, comment_body: str) -> dict[str, Any]:
    token, _ = resolve_user_oauth_token()
    return _CLIENT.create_comment(access_token=token or "", issue_key=issue_key, body=comment_body)


def list_jira_comments(issue_key: str) -> dict[str, Any]:
    token, _ = resolve_user_oauth_token()
    return _CLIENT.list_comments(access_token=token or "", issue_key=issue_key)


def create_jira_issue(project_key: str, summary: str, issue_type: str = "Task", description: str = "", **kwargs) -> dict[str, Any]:
    token, _ = resolve_user_oauth_token()
    return _CLIENT.create_issue(
        access_token=token or "",
        project_key=project_key,
        summary=summary,
        issue_type_name=issue_type,
        description=description,
        **kwargs,
    )


AGENT_INSTRUCTION = """You are an expert Jira Engineering Assistant powered by Gemini Enterprise Federated Jira Connector.
You help engineers and managers inspect, track, search, comment on, and manage their Jira issues and projects.

You have access to native Jira MCP tools provided dynamically by the built-in google.adk.tools.mcp_tool.McpToolset:
- `search_issues`: Search Jira issues using JQL query strings (e.g. `project = "CCS"`, `assignee = currentUser()`, `statusCategory != Done`).
- `get_issue`: Retrieve details of an issue by key (e.g. `CCS-50`, `GEAP-3`) or ID.
- `list_projects`: List Jira projects accessible to the user.
- `create_comment`: Post comments on issues.
- `create_issue`: Create new issues in a project.
- `check_oauth_status`: Check if the user is authorized with 3LO in Auth Manager.
- `complete_oauth_consent`: Complete 3LO consent with the redirect URL.

SECURITY & 3LO ACCESS CONTROL:
- Every Jira action executes with the caller's delegated 3-Legged OAuth (3LO) credentials brokered by Google Cloud IAM Auth Manager.
- If an action indicates the user is unauthorized, guide the user to click the returned `authorization_uri` and paste back the redirect URL to complete `complete_oauth_consent`.

PRESENTATION GUIDELINES:
- When listing issues, present them in a clear Markdown table with Key (hyperlinked), Title, Status, Priority, and Assignee.
- Always include direct links to Jira issues when citing them.
"""

jira_federated_agent = LlmAgent(
    model=_CONFIG.model,
    name="jira_federated_agent",
    instruction=AGENT_INSTRUCTION,
    tools=[
        jira_toolset,
        check_jira_oauth_status,
        complete_jira_oauth_consent,
    ],
)

root_agent = jira_federated_agent
