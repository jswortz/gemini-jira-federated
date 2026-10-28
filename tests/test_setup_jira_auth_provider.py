"""Unit tests for scripts/setup_jira_auth_provider.py."""

from unittest.mock import MagicMock, patch
from google.api_core import exceptions as google_exceptions
import pytest

from scripts.setup_jira_auth_provider import (
    bind_authorization_to_agent,
    get_or_create_discovery_engine_authorization,
    get_or_create_secret,
    grant_secret_accessor_role,
    load_deployment_metadata_agent_id,
)


def test_load_deployment_metadata_agent_id():
    agent_id = load_deployment_metadata_agent_id()
    assert agent_id == "16003540595574963813"


def test_get_or_create_secret_fetch_existing():
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.payload.data = b"my-client-id-value\n"
    mock_client.access_secret_version.return_value = mock_resp

    res = get_or_create_secret(mock_client, "test-proj", "jira-client-id")
    assert res == "my-client-id-value"
    mock_client.access_secret_version.assert_called_once_with(
        name="projects/test-proj/secrets/jira-client-id/versions/latest"
    )


def test_get_or_create_secret_not_found():
    mock_client = MagicMock()
    mock_client.access_secret_version.side_effect = google_exceptions.NotFound("not found")

    res = get_or_create_secret(mock_client, "test-proj", "jira-client-id")
    assert res == ""


def test_get_or_create_secret_create_new():
    mock_client = MagicMock()
    mock_client.get_secret.side_effect = google_exceptions.NotFound("not found")

    res = get_or_create_secret(
        mock_client, "test-proj", "jira-client-id", payload_value="secret-val"
    )
    assert res == "secret-val"
    mock_client.create_secret.assert_called_once()
    mock_client.add_secret_version.assert_called_once()


def test_grant_secret_accessor_role():
    mock_client = MagicMock()
    mock_policy = MagicMock()
    mock_binding_list = MagicMock()
    mock_policy.bindings = mock_binding_list
    mock_binding_list.__iter__.return_value = []
    mock_client.get_iam_policy.return_value = mock_policy

    grant_secret_accessor_role(
        mock_client, "test-proj", "jira-secret", "serviceAccount:test@sa.com"
    )
    mock_binding_list.add.assert_called_once_with(
        role="roles/secretmanager.secretAccessor", members=["serviceAccount:test@sa.com"]
    )
    mock_client.set_iam_policy.assert_called_once()


@patch("requests.get")
def test_get_or_create_discovery_engine_authorization_existing(mock_get):
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {
        "name": "projects/123/locations/global/authorizations/jira-oauth-provider"
    }
    mock_get.return_value = mock_resp

    res = get_or_create_discovery_engine_authorization(
        access_token="fake-token",
        project_number="123",
        location="global",
        authorization_id="jira-oauth-provider",
        client_id="cid",
        client_secret="sec",
        scopes=["read:jira-work"],
    )
    assert res["name"] == "projects/123/locations/global/authorizations/jira-oauth-provider"


@patch("requests.post")
@patch("requests.get")
def test_get_or_create_discovery_engine_authorization_create_new(mock_get, mock_post):
    mock_get_resp = MagicMock()
    mock_get_resp.ok = False
    mock_get.return_value = mock_get_resp

    mock_post_resp = MagicMock()
    mock_post_resp.ok = True
    mock_post_resp.json.return_value = {
        "name": "projects/123/locations/global/authorizations/jira-oauth-provider",
        "displayName": "Jira 3LO Auth Provider",
    }
    mock_post.return_value = mock_post_resp

    res = get_or_create_discovery_engine_authorization(
        access_token="fake-token",
        project_number="123",
        location="global",
        authorization_id="jira-oauth-provider",
        client_id="cid",
        client_secret="sec",
        scopes=["read:jira-work"],
    )
    assert res["displayName"] == "Jira 3LO Auth Provider"
    mock_post.assert_called_once()


@patch("requests.patch")
@patch("requests.get")
def test_bind_authorization_to_agent(mock_get, mock_patch):
    mock_get_resp = MagicMock()
    mock_get_resp.ok = True
    mock_get_resp.json.return_value = {
        "name": "projects/123/locations/global/.../agents/agent-1",
        "authorizationConfig": {"toolAuthorizations": []},
    }
    mock_get.return_value = mock_get_resp

    mock_patch_resp = MagicMock()
    mock_patch_resp.ok = True
    mock_patch_resp.json.return_value = {
        "authorizationConfig": {
            "toolAuthorizations": ["projects/123/locations/global/authorizations/jira-auth"]
        }
    }
    mock_patch.return_value = mock_patch_resp

    res = bind_authorization_to_agent(
        access_token="token",
        project_number="123",
        location="global",
        engine_id="test-engine",
        agent_id="agent-1",
        authorization_name="projects/123/locations/global/authorizations/jira-auth",
    )
    assert "projects/123/locations/global/authorizations/jira-auth" in res["authorizationConfig"]["toolAuthorizations"]
    mock_patch.assert_called_once()
