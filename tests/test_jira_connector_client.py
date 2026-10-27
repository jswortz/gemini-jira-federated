"""Unit tests for Discovery Engine Jira Federated Connector client."""

import json
from unittest.mock import MagicMock, patch

from jira_federated_agent.config import ConnectorConfig
from jira_federated_agent.jira_connector_client import JiraFederatedConnectorClient


def _mock_response(status_code: int, payload: dict):
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = 200 <= status_code < 300
    resp.json.return_value = payload
    resp.text = json.dumps(payload)
    return resp


def test_check_oauth_status_authorized():
    client = JiraFederatedConnectorClient(config=ConnectorConfig())
    with patch.object(client._session, "request") as mock_req:
        mock_req.side_effect = [
            # 1. checkRefreshToken
            _mock_response(
                200,
                {
                    "refreshTokenInfo": {
                        "name": "projects/wortz-project-352116/locations/global/collections/jira-federated_1782320633397/dataConnector",
                        "scopes": ["read:jira-work", "offline_access"],
                    }
                },
            ),
            # 2. widgetConfig
            _mock_response(
                200,
                {
                    "collectionComponents": [
                        {
                            "id": "jira-federated_1782320633397",
                            "connectorAuthState": {
                                "authState": "AUTHORIZED",
                                "authorizationUri": "https://auth.atlassian.com/authorize?client_id=test",
                            },
                        }
                    ]
                },
            ),
            # 3. acquireAccessToken
            _mock_response(
                200,
                {
                    "accessToken": "atlassian-3lo-jwt-token",
                    "refreshTokenInfo": {"scopes": ["read:jira-work"]},
                },
            ),
        ]

        result = client.check_oauth_status(access_token="google-user-oauth-token")
        assert result["authorized"] is True
        assert result["auth_state"] == "AUTHORIZED"
        assert result["has_active_3lo_token"] is True
        assert "read:jira-work" in result["scopes"]


def test_search_issues_parses_mcp_payload():
    client = JiraFederatedConnectorClient(config=ConnectorConfig())
    inner_payload = {
        "result": {
            "nextPageToken": None,
            "results": [
                {
                    "key": "GEAP-3",
                    "title": "VPC-SC connector test (updated)",
                    "status": "In Progress",
                    "priority": "High",
                    "issue_type": "Task",
                    "project_key": "GEAP",
                    "project_name": "GEAP",
                    "reporter_name": "Jeremy Wortz",
                    "created": "2026-08-25T11:18:21.461-0500",
                    "updated": "2026-08-25T11:37:39.243-0500",
                    "url": "https://jwortz.atlassian.net/browse/GEAP-3",
                    "comments": [
                        {
                            "authorDisplayName": "Jeremy Wortz",
                            "body": {
                                "type": "doc",
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [
                                            {
                                                "type": "text",
                                                "text": "Automated test comment from Gemini Enterprise behind VPC-SC.",
                                            }
                                        ],
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
        }
    }
    mcp_response = {
        "result": {
            "isError": False,
            "content": [{"type": "text", "text": json.dumps(inner_payload)}],
        }
    }

    with patch.object(
        client._session, "request", return_value=_mock_response(200, mcp_response)
    ):
        res = client.search_issues(
            access_token="google-user-oauth-token",
            query="VPC-SC",
            max_results=10,
        )
        assert res["status"] == "success"
        assert res["count"] == 1
        issue = res["issues"][0]
        assert issue["key"] == "GEAP-3"
        assert issue["title"] == "VPC-SC connector test (updated)"
        assert issue["url"] == "https://jwortz.atlassian.net/browse/GEAP-3"
        assert (
            "Automated test comment from Gemini Enterprise behind VPC-SC."
            in issue["comments"][0]["text"]
        )


def test_list_projects_parses_entities():
    client = JiraFederatedConnectorClient(config=ConnectorConfig())
    inner_payload = {
        "result": {
            "entities": [
                {
                    "fields": {
                        "Id": 10000,
                        "Key": "CCS",
                        "Name": "Grocery-store",
                        "ProjectTypeKey": "software",
                        "LeadDisplayName": "Jeremy Wortz",
                        "ItemURL": "https://jwortz.atlassian.net/jira/software/c/projects/CCS/issues",
                    }
                }
            ]
        }
    }
    mcp_response = {
        "result": {
            "isError": False,
            "content": [{"type": "text", "text": json.dumps(inner_payload)}],
        }
    }
    with patch.object(
        client._session, "request", return_value=_mock_response(200, mcp_response)
    ):
        res = client.list_projects(access_token="google-user-oauth-token")
        assert res["status"] == "success"
        assert res["projects"][0]["key"] == "CCS"
        assert res["projects"][0]["name"] == "Grocery-store"
