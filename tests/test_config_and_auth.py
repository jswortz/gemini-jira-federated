"""Unit tests for configuration, input validation, JQL building, and OAuth."""

from unittest.mock import MagicMock, patch
import pytest

from jira_federated_agent.config import (
    ConnectorConfig,
    build_safe_jql,
    validate_issue_key,
    validate_project_key,
)
from jira_federated_agent.auth import (
    build_adk_oauth_config,
    extract_token_from_tool_context,
    resolve_user_oauth_token,
)


def test_connector_config_defaults():
    cfg = ConnectorConfig()
    assert cfg.project_id == "wortz-project-352116"
    assert cfg.project_number == "679926387543"
    assert cfg.location == "global"
    assert cfg.engine_id == "ge-jira-vpcsc-app"
    assert cfg.collection_id == "jira-federated_1782320633397"
    assert (
        cfg.data_connector_name
        == "projects/679926387543/locations/global/collections/jira-federated_1782320633397/dataConnector"
    )
    assert len(cfg.entity_data_stores) == 10
    assert (
        "projects/679926387543/locations/global/collections/default_collection/dataStores/jira-federated_1782320633397_issue"
        in cfg.entity_data_stores
    )


def test_validate_issue_key():
    assert validate_issue_key("ccs-50") == "CCS-50"
    assert validate_issue_key(" GEAP-3 ") == "GEAP-3"
    assert validate_issue_key("10286") == "10286"
    with pytest.raises(ValueError, match="Invalid Jira issue key"):
        validate_issue_key("CCS-50; DROP TABLE")
    with pytest.raises(ValueError, match="Invalid Jira issue key"):
        validate_issue_key("")


def test_validate_project_key():
    assert validate_project_key("ccs") == "CCS"
    assert validate_project_key("GEAP") == "GEAP"
    with pytest.raises(ValueError, match="Invalid Jira project key"):
        validate_project_key("CCS OR 1=1")


def test_build_safe_jql():
    # Free-text keyword search
    jql = build_safe_jql(query="Snowflake migration")
    assert jql == 'text ~ "Snowflake migration"'

    # Combined filters
    jql = build_safe_jql(
        query="BigQuery",
        project_key="ccs",
        status="To Do",
        issue_type="Task",
    )
    assert 'project = "CCS"' in jql
    assert 'status = "To Do"' in jql
    assert 'issuetype = "Task"' in jql
    assert 'text ~ "BigQuery"' in jql

    # Strips ORDER BY if accidentally passed in raw JQL
    jql = build_safe_jql(jql='project = "CCS" ORDER BY created DESC')
    assert jql == 'project = "CCS"'

    # Escapes quotes in keyword query to prevent JQL injection
    jql = build_safe_jql(query='test "quoted" value')
    assert jql == 'text ~ "test \\"quoted\\" value"'


def test_extract_token_from_tool_context():
    ctx = MagicMock()
    ctx.state = {"temp:jira_federated_oauth_token": "ctx-token-123"}
    assert extract_token_from_tool_context(ctx) == "ctx-token-123"


def test_resolve_user_oauth_token_from_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_OAUTH_ACCESS_TOKEN", "env-oauth-token-xyz")
    token, source = resolve_user_oauth_token(tool_context=None)
    assert token == "env-oauth-token-xyz"
    assert source == "env:GOOGLE_OAUTH_ACCESS_TOKEN"


def test_build_adk_oauth_config():
    auth_cfg = build_adk_oauth_config(
        client_id="test-client-id",
        client_secret="test-client-secret",
        authorization_uri="https://accounts.google.com/o/oauth2/v2/auth",
    )
    assert auth_cfg.credential_key == "jira_federated_google_oauth"
    assert auth_cfg.raw_auth_credential.oauth2.client_id == "test-client-id"
