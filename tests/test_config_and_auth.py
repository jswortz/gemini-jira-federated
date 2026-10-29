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
    cfg.validate()
    assert cfg.project_id
    assert cfg.project_number
    assert cfg.location == "global"
    assert cfg.engine_id
    assert cfg.collection_id
    assert cfg.data_connector_name.startswith("projects/")


def test_connector_config_custom_env(monkeypatch):
    monkeypatch.setenv("DISCOVERY_ENGINE_PROJECT_ID", "custom-proj-999")
    monkeypatch.setenv("DISCOVERY_ENGINE_PROJECT_NUMBER", "999999999")
    monkeypatch.setenv("DISCOVERY_ENGINE_LOCATION", "us-central1")
    monkeypatch.setenv("DISCOVERY_ENGINE_ID", "custom-engine")
    monkeypatch.setenv("JIRA_CONNECTOR_COLLECTION_ID", "custom-connector")
    monkeypatch.setenv("JIRA_INSTANCE_URI", "https://custom.atlassian.net")
    monkeypatch.setenv("OAUTH_USER_ACCOUNT", "custom@example.com")

    cfg = ConnectorConfig()
    cfg.validate()
    assert cfg.project_id == "custom-proj-999"
    assert cfg.project_number == "999999999"
    assert cfg.location == "us-central1"
    assert cfg.engine_id == "custom-engine"
    assert cfg.collection_id == "custom-connector"
    assert cfg.jira_instance_uri == "https://custom.atlassian.net"
    assert cfg.oauth_user_account == "custom@example.com"
    assert (
        cfg.data_connector_name
        == "projects/999999999/locations/us-central1/collections/custom-connector/dataConnector"
    )
    assert cfg.base_api_url == "https://us-central1-discoveryengine.googleapis.com/v1alpha"


def test_connector_config_validation_failure(monkeypatch):
    monkeypatch.delenv("DISCOVERY_ENGINE_PROJECT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    cfg = ConnectorConfig(project_id="")
    with pytest.raises(ValueError, match="Missing required environment variables"):
        cfg.validate()


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
