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
