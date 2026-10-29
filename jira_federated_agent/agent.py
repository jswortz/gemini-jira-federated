"""ADK RAG Agent over the Gemini Enterprise Jira Federated Data Connector.

Uses DiscoveryEngineMcpToolset to connect directly in-process to the Jira MCP server,
executing federated Model Context Protocol (MCP) actions against Discovery Engine's
dataConnector:invokeConnectorMcp endpoint.
End-user Atlassian 3-Legged OAuth (3LO) tokens are securely brokered by Google Cloud IAM Auth Manager.
"""

from __future__ import annotations

import logging
from typing import Any

from google.adk.agents import LlmAgent

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

# Pure in-process Discovery Engine MCP Toolset:
# Dynamically discovers MCP tools directly from Gemini Enterprise Federated Connector
# and invokes :invokeConnectorMcp in-process with 3LO OAuth credentials brokered by Google Auth Manager.
jira_toolset = DiscoveryEngineMcpToolset(client=_CLIENT)


# Programmatic convenience functions
def check_jira_oauth_status() -> dict[str, Any]:
    token, _ = resolve_user_oauth_token(account=_CONFIG.oauth_user_account, project_id=_CONFIG.project_id)
    return _CLIENT.check_oauth_status(access_token=token or "")


def complete_jira_oauth_consent(redirect_url: str) -> dict[str, Any]:
    token, _ = resolve_user_oauth_token(account=_CONFIG.oauth_user_account, project_id=_CONFIG.project_id)
    return _CLIENT.complete_oauth_consent(access_token=token or "", full_redirect_uri=redirect_url)


AGENT_INSTRUCTION = """You are an expert Jira Engineering Assistant powered by Gemini Enterprise Federated Jira Connector.
You help engineers and managers inspect, track, search, comment on, and manage their Jira issues and projects.

You have access to native Jira MCP tools provided dynamically by DiscoveryEngineMcpToolset:
- `search_issues`: Search Jira issues using JQL query strings (e.g. `project = "CCS"`, `statusCategory != Done`, `order by created DESC`).
- `get_issue`: Retrieve details of an issue by key (e.g. `CCS-50`, `GEAP-3`) or ID.
- `list_projects`: List Jira projects accessible to the user.
- `create_comment`: Post comments on issues.
- `create_issue`: Create new issues in a project.

OPERATIONAL RULES:
- Immediately invoke the appropriate tool (`search_issues`, `get_issue`, `list_projects`, etc.) to answer user requests.
- When listing issues, present them in a clear Markdown table with Key (hyperlinked), Title, Status, Priority, and Assignee.
- Always include direct links to Jira issues when citing them.
"""

jira_federated_agent = LlmAgent(
    model=_CONFIG.model,
    name="jira_federated_agent",
    instruction=AGENT_INSTRUCTION,
    tools=[
        jira_toolset,
    ],
)

root_agent = jira_federated_agent
