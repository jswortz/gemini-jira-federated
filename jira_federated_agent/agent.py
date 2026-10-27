"""ADK RAG Agent over the Gemini Enterprise Jira Federated Data Connector."""

from __future__ import annotations

from typing import Any

from google.adk.agents import LlmAgent
from google.adk.tools.tool_context import ToolContext

from jira_federated_agent.auth import (
    configure_vertex_ai_user_credentials,
    resolve_user_oauth_token,
)
from jira_federated_agent.config import ConnectorConfig
from jira_federated_agent.jira_connector_client import JiraFederatedConnectorClient

# Bridge google.auth.default() in memory to the configured OAuth user account
# so Vertex AI (Gemini) and Discovery Engine work seamlessly in `adk web`.
_CONFIG = ConnectorConfig()
configure_vertex_ai_user_credentials(
    account=_CONFIG.oauth_user_account,
    project_id=_CONFIG.project_id,
)
_CLIENT = JiraFederatedConnectorClient(config=_CONFIG)


def check_jira_oauth_status(
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Checks the user's OAuth authentication status for the Gemini Enterprise Jira Federated Connector.

    Verifies both:
    1. The user's Google OAuth2 identity token (via ADK Web OAuth or local gcloud user OAuth).
    2. The user's linked Atlassian 3LO OAuth refresh/access token inside Discovery Engine's
       `jira-federated_1782320633397` connector vault.

    If the user has not yet authorized Jira Cloud, returns the `authorization_uri`
    so the user can click it and complete 3-Legged OAuth consent.
    """
    token, auth_source = resolve_user_oauth_token(
        tool_context=tool_context,
        account=_CONFIG.oauth_user_account,
        project_id=_CONFIG.project_id,
    )
    if not token:
        return {
            "authorized": False,
            "auth_source": auth_source,
            "message": (
                "Pending user OAuth authentication. Please complete the OAuth login "
                "prompt or authenticate via gcloud."
            ),
        }

    status = _CLIENT.check_oauth_status(access_token=token)
    status["google_oauth_source"] = auth_source
    status["google_oauth_user"] = _CONFIG.oauth_user_account
    return status


def complete_jira_oauth_consent(
    redirect_url: str,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Completes the 3-Legged OAuth (3LO) consent handshake for the Jira Federated Connector.

    Args:
        redirect_url: The full redirect URL (starting with
            `https://vertexaisearch.cloud.google.com/oauth-redirect?code=...`)
            that the user was redirected to after authorizing Jira Cloud.
    """
    token, auth_source = resolve_user_oauth_token(
        tool_context=tool_context,
        account=_CONFIG.oauth_user_account,
        project_id=_CONFIG.project_id,
    )
    if not token:
        return {
            "status": "error",
            "auth_source": auth_source,
            "message": "No Google OAuth token available to store the connector refresh token.",
        }
    return _CLIENT.complete_oauth_consent(
        access_token=token, full_redirect_uri=redirect_url
    )


def list_jira_projects(
    query: str = "",
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Lists or searches Jira projects through the Gemini Enterprise Jira Federated Connector.

    Args:
        query: Optional search string to filter projects by key or name (e.g. 'CCS' or 'GEAP').
    """
    token, auth_source = resolve_user_oauth_token(
        tool_context=tool_context,
        account=_CONFIG.oauth_user_account,
        project_id=_CONFIG.project_id,
    )
    if not token:
        return {
            "status": "auth_required",
            "auth_source": auth_source,
            "message": "User OAuth authentication is required before querying Jira projects.",
        }
    return _CLIENT.list_projects(access_token=token, query=query)


def search_jira_issues(
    query: str = "",
    project_key: str = "",
    status: str = "",
    issue_type: str = "",
    jql: str = "",
    max_results: int = 20,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Searches live Jira issues over the configured Gemini Enterprise Federated Jira Connector.

    Args:
        query: Natural language keyword or phrase to search across Jira issue summaries,
            descriptions, and comments (e.g. 'Snowflake', 'VPC-SC', 'Career Compass').
            Leave empty to list the most recent Jira issues across all projects.
        project_key: Optional Jira project key filter (e.g. 'CCS' or 'GEAP').
        status: Optional Jira status filter (e.g. 'To Do', 'In Progress', 'Done').
        issue_type: Optional Jira issue type filter (e.g. 'Task', 'Bug', 'Epic', 'Story').
        jql: Optional explicit JQL filter string (e.g. `project = "CCS" AND priority = "Medium"`).
            Do not include `ORDER BY` in `jql`.
        max_results: Maximum number of issues to return (1 to 50, default 20).
    """
    token, auth_source = resolve_user_oauth_token(
        tool_context=tool_context,
        account=_CONFIG.oauth_user_account,
        project_id=_CONFIG.project_id,
    )
    if not token:
        return {
            "status": "auth_required",
            "auth_source": auth_source,
            "message": "User OAuth authentication is required before searching Jira issues.",
        }
    return _CLIENT.search_issues(
        access_token=token,
        query=query,
        jql=jql,
        project_key=project_key,
        status=status,
        issue_type=issue_type,
        max_results=max_results,
    )


def get_jira_issue(
    issue_key: str,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Retrieves full details, description, and comments for a specific Jira issue key.

    Args:
        issue_key: The Jira issue key (e.g. 'GEAP-3', 'GEAP-2', 'CCS-68', 'CCS-50').
    """
    token, auth_source = resolve_user_oauth_token(
        tool_context=tool_context,
        account=_CONFIG.oauth_user_account,
        project_id=_CONFIG.project_id,
    )
    if not token:
        return {
            "status": "auth_required",
            "auth_source": auth_source,
            "message": "User OAuth authentication is required before fetching a Jira issue.",
        }
    return _CLIENT.get_issue(access_token=token, issue_key=issue_key)


def ask_gemini_enterprise_jira(
    question: str,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Queries Gemini Enterprise's native assistant service (:streamAssist) over all 10 federated Jira data stores.

    Leverages Gemini Enterprise's built-in query rewriting, multi-entity blended search,
    grounding attribution tokens, and answer synthesis across issues, comments, projects,
    attachments, epics, stories, bugs, tasks, worklogs, and boards.

    Args:
        question: Natural language question (e.g. 'What is the status of the Snowflake migration?'
            or 'What comments does GEAP-3 have?').
    """
    token, auth_source = resolve_user_oauth_token(
        tool_context=tool_context,
        account=_CONFIG.oauth_user_account,
        project_id=_CONFIG.project_id,
    )
    if not token:
        return {
            "status": "auth_required",
            "auth_source": auth_source,
            "message": "User OAuth authentication is required before querying Gemini Enterprise.",
        }
    return _CLIENT.stream_assist(access_token=token, query=question)


AGENT_INSTRUCTION = f"""You are a Grounded Jira Assistant powered by Google ADK and the Gemini Enterprise Federated Jira Data Connector.

### Connected Data Source
- **GCP Project**: `{_CONFIG.project_id}` (`{_CONFIG.project_number}`)
- **Gemini Enterprise App / Engine**: `{_CONFIG.engine_id}`
- **Federated Connector Collection**: `{_CONFIG.collection_id}` (`THIRD_PARTY_FEDERATED`)
- **Data Connector Resource**: `{_CONFIG.data_connector_name}`
- **Atlassian Jira Cloud Instance**: `{_CONFIG.jira_instance_uri}`
- **Active Retrieval Mode**: `{_CONFIG.retrieval_mode}`

### Operational Rules
1. **Always Ground Responses in Live Federated Data**:
   - Use `search_jira_issues`, `get_jira_issue`, and `list_jira_projects` to retrieve live Jira tickets and projects from the federated connector.
   - For high-level synthesis questions requiring blended answers across all 10 entities (issues, comments, boards, projects), use `ask_gemini_enterprise_jira`.
   - If a user asks to "list all Jira issues" or "what Jira issues can you see?", call `search_jira_issues(query="", max_results=20)` with an empty `query` to retrieve the latest issues across all projects.
2. **OAuth Verification & Consent Handling**:
   - When asked about authentication status or if a tool reports an authorization error, call `check_jira_oauth_status()`.
   - If the user is not yet authorized in the connector vault, share the `authorization_uri` from `check_jira_oauth_status()` and offer to complete the flow via `complete_jira_oauth_consent(redirect_url)` once they paste the callback URL.
3. **Clear Citations**:
   - Format Jira issues in a clean Markdown table or structured bullet list including the **Issue Key** (as a clickable link `[KEY]({_CONFIG.jira_instance_uri.rstrip('/')}/browse/KEY)`), **Title/Summary**, **Project**, **Type**, **Status**, **Priority**, **Reporter/Assignee**, and any relevant **Description** or **Comments**.
"""

root_agent = LlmAgent(
    name="jira_federated_agent",
    model=_CONFIG.model,
    description=(
        "RAG ADK agent over the Gemini Enterprise Jira Federated Data Connector "
        f"({_CONFIG.collection_id}) in {_CONFIG.project_id} using OAuth."
    ),
    instruction=AGENT_INSTRUCTION,
    tools=[
        check_jira_oauth_status,
        complete_jira_oauth_consent,
        list_jira_projects,
        search_jira_issues,
        get_jira_issue,
        ask_gemini_enterprise_jira,
    ],
)
