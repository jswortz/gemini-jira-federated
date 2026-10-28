"""Live integration tests against the configured Gemini Enterprise Jira Federated Connector."""

import pytest

from jira_federated_agent.auth import resolve_user_oauth_token
from jira_federated_agent.config import ConnectorConfig
from jira_federated_agent.jira_connector_client import JiraFederatedConnectorClient


@pytest.mark.integration
def test_live_oauth_and_federated_jira_search():
    cfg = ConnectorConfig()
    token, source = resolve_user_oauth_token()
    if not token:
        pytest.skip(
            f"No valid Google OAuth user token found for '{cfg.oauth_user_account}'. "
            "Skipping live integration test in unauthenticated/sandboxed test runner."
        )

    client = JiraFederatedConnectorClient(config=cfg)

    # 1. Verify OAuth status against the configured connector
    oauth_status = client.check_oauth_status(access_token=token)
    assert oauth_status["authorized"] is True
    assert oauth_status["has_active_3lo_token"] is True

    # 2. Verify listing Jira projects over the federated connector
    projects_res = client.list_projects(access_token=token)
    assert projects_res["status"] == "success"
    assert len(projects_res["projects"]) > 0

    # 3. Verify searching Jira issues over the federated connector
    issues_res = client.search_issues(access_token=token, max_results=10)
    assert issues_res["status"] == "success"
    assert issues_res["count"] > 0

    # 4. Verify native MCP tools catalog inspection
    tools_res = client.list_mcp_tools(access_token=token)
    assert tools_res["status"] == "success"
    tool_names = [t.get("name") for t in tools_res.get("tools", [])]
    assert "search_issues" in tool_names
    assert "get_issue" in tool_names
    assert "create_comment" in tool_names

    # 5. Verify live get_issue via MCP
    issue_res = client.get_issue(access_token=token, issue_key="GEAP-3")
    assert issue_res["status"] == "success"
    assert issue_res["issue"]["key"] == "GEAP-3"

    # 6. Verify live list_comments via MCP
    comments_res = client.list_comments(access_token=token, issue_key="GEAP-3")
    assert comments_res["status"] == "success"
    assert len(comments_res["comments"]) > 0
