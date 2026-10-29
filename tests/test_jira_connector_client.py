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
                        "name": client.config.data_connector_name,
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
                            "id": client.config.collection_id,
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
                    "url": f"{client.config.jira_instance_uri}/browse/GEAP-3",
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
        assert issue["url"] == f"{client.config.jira_instance_uri}/browse/GEAP-3"
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
                        "ItemURL": f"{client.config.jira_instance_uri}/jira/software/c/projects/CCS/issues",
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


def test_invoke_mcp_tools_list():
    client = JiraFederatedConnectorClient(config=ConnectorConfig())
    mcp_response = {
        "result": {
            "tools": [
                {"name": "search_issues", "description": "Searches for Jira issues."},
                {"name": "get_issue", "description": "Retrieves issue details."},
                {"name": "create_comment", "description": "Creates a comment."},
            ]
        }
    }
    with patch.object(
        client._session, "request", return_value=_mock_response(200, mcp_response)
    ) as mock_req:
        res = client.list_mcp_tools(access_token="google-user-oauth-token")
        assert res["status"] == "success"
        assert len(res["tools"]) == 3
        assert res["tools"][0]["name"] == "search_issues"
        call_kwargs = mock_req.call_args[1]
        assert call_kwargs["json"]["method"] == "tools/list"


def test_get_issue_via_mcp():
    client = JiraFederatedConnectorClient(config=ConnectorConfig())
    inner_payload = {
        "result": {
            "key": "GEAP-3",
            "issue_key": "GEAP-3",
            "title": "VPC-SC connector test",
            "status": "In Progress",
            "priority": "High",
            "project_key": "GEAP",
            "project_name": "GEAP",
            "creator_name": "Jeremy Wortz",
            "reporter_name": "Jeremy Wortz",
            "created": "2026-08-25T16:18:21Z",
            "updated": "2026-08-25T16:37:39Z",
            "url": f"{client.config.jira_instance_uri}/browse/GEAP-3",
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
    ) as mock_req:
        res = client.get_issue(access_token="google-user-oauth-token", issue_key="GEAP-3")
        assert res["status"] == "success"
        issue = res["issue"]
        assert issue["key"] == "GEAP-3"
        assert issue["title"] == "VPC-SC connector test"
        assert issue["status"] == "In Progress"
        call_kwargs = mock_req.call_args[1]
        assert call_kwargs["json"]["method"] == "tools/call"
        assert call_kwargs["json"]["params"]["name"] == "get_issue"
        assert call_kwargs["json"]["params"]["arguments"]["Id"] == "GEAP-3"


def test_create_comment_via_mcp():
    client = JiraFederatedConnectorClient(config=ConnectorConfig())
    inner_payload = {
        "result": {
            "Id": 10034,
            "IssueId": 10286,
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
    ) as mock_req:
        res = client.create_comment(
            access_token="google-user-oauth-token",
            issue_key="GEAP-3",
            body="Test automated comment",
        )
        assert res["status"] == "success"
        assert res["comment_id"] == 10034
        call_kwargs = mock_req.call_args[1]
        assert call_kwargs["json"]["params"]["name"] == "create_comment"
        assert call_kwargs["json"]["params"]["arguments"]["IssueKey"] == "GEAP-3"
        assert call_kwargs["json"]["params"]["arguments"]["Body"] == "Test automated comment"


def test_update_comment_via_mcp():
    client = JiraFederatedConnectorClient(config=ConnectorConfig())
    inner_payload = {
        "result": {
            "Id": 10034,
            "IssueKey": "GEAP-3",
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
    ) as mock_req:
        res = client.update_comment(
            access_token="google-user-oauth-token",
            issue_key="GEAP-3",
            comment_id=10034,
            body="Updated comment text",
        )
        assert res["status"] == "success"
        call_kwargs = mock_req.call_args[1]
        assert call_kwargs["json"]["params"]["name"] == "update_comment"
        assert call_kwargs["json"]["params"]["arguments"]["Id"] == 10034


def test_list_comments_via_mcp():
    client = JiraFederatedConnectorClient(config=ConnectorConfig())
    inner_payload = {
        "result": {
            "entities": [
                {
                    "fields": {
                        "Id": 10033,
                        "IssueKey": "GEAP-3",
                        "AuthorDisplayName": "Jeremy Wortz",
                        "AuthorEmail": "user@example.com",
                        "Body": "Existing comment on issue",
                        "Created": "2026-08-25 16:24:07.87",
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
        res = client.list_comments(access_token="google-user-oauth-token", issue_key="GEAP-3")
        assert res["status"] == "success"
        assert len(res["comments"]) == 1
        assert res["comments"][0]["author"] == "Jeremy Wortz"
        assert res["comments"][0]["body"] == "Existing comment on issue"


def test_create_issue_via_mcp():
    client = JiraFederatedConnectorClient(config=ConnectorConfig())
    inner_payload = {
        "result": {
            "Id": 10050,
            "Key": "GEAP-10",
            "self": f"{client.config.jira_instance_uri}/rest/api/2/issue/10050",
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
    ) as mock_req:
        res = client.create_issue(
            access_token="google-user-oauth-token",
            project_key="GEAP",
            summary="New bug ticket from agent",
            issue_type_name="Bug",
            issue_type_id="10043",
            description="Detailed repro steps",
        )
        assert res["status"] == "success"
        assert res["issue_key"] == "GEAP-10"
        call_kwargs = mock_req.call_args[1]
        assert call_kwargs["json"]["params"]["name"] == "create_issue"
        assert call_kwargs["json"]["params"]["arguments"]["ProjectKey"] == "GEAP"
        assert call_kwargs["json"]["params"]["arguments"]["Summary"] == "New bug ticket from agent"
        assert call_kwargs["json"]["params"]["arguments"]["IssueTypeId"] == "10043"


def test_invoke_mcp_tool_handles_error():
    client = JiraFederatedConnectorClient(config=ConnectorConfig())
    mcp_error_response = {
        "error": {
            "code": 403,
            "message": "Permission denied on data connector",
        }
    }
    with patch.object(
        client._session, "request", return_value=_mock_response(403, mcp_error_response)
    ):
        res = client.invoke_mcp_tool(
            access_token="google-user-oauth-token",
            tool_name="get_issue",
            arguments={"Id": "GEAP-3"},
        )
        assert res["status"] == "error"
        assert "403" in res["message"] or "Permission denied" in res.get("details", "")


def test_invoke_tool_with_google_token_routes_to_mcp():
    client = JiraFederatedConnectorClient(config=ConnectorConfig())
    with patch.object(
        client, "invoke_mcp_tool", return_value={"status": "success", "data": {"issues": [{"key": "GEAP-1"}]}}
    ) as mock_mcp:
        res = client.invoke_tool(
            access_token="mock-google-token-xyz",
            tool_name="search_issues",
            arguments={"jql": "project = GEAP"},
        )
        assert res["status"] == "success"
        mock_mcp.assert_called_once_with(
            access_token="mock-google-token-xyz",
            tool_name="search_issues",
            arguments={"jql": "project = GEAP"},
        )


def test_invoke_tool_with_atlassian_token_routes_to_atlassian_rest():
    client = JiraFederatedConnectorClient(config=ConnectorConfig())
    with patch.object(client, "_get_atlassian_cloud_id", return_value="cloud-999"), \
         patch.object(
             client,
             "_search_issues_atlassian_rest",
             return_value={"status": "success", "source": "atlassian_cloud_rest", "issues": [{"key": "CCS-10"}]},
         ) as mock_rest:
        res = client.invoke_tool(
            access_token="atlassian-3lo-token-jwt",
            tool_name="search_issues",
            arguments={"jql": "project = CCS"},
        )
        assert res["status"] == "success"
        assert res["source"] == "atlassian_cloud_rest"
        mock_rest.assert_called_once_with(
            access_token="atlassian-3lo-token-jwt",
            cloud_id="cloud-999",
            safe_jql="project = CCS",
            max_results=20,
        )


def test_invoke_tool_fallback_to_atlassian_rest_when_mcp_fails():
    client = JiraFederatedConnectorClient(config=ConnectorConfig())
    with patch.object(client, "invoke_mcp_tool", return_value={"status": "error", "message": "401 Unauthorized"}), \
         patch.object(client, "_get_atlassian_cloud_id", return_value="cloud-999"), \
         patch.object(
             client,
             "_get_issue_atlassian_rest",
             return_value={"status": "success", "source": "atlassian_cloud_rest", "issue": {"key": "CCS-10"}},
         ) as mock_rest:
        res = client.invoke_tool(
            access_token="mock-google-token-xyz",
            tool_name="get_issue",
            arguments={"issueIdOrKey": "CCS-10"},
        )
        assert res["status"] == "success"
        assert res["source"] == "atlassian_cloud_rest"
        mock_rest.assert_called_once_with(
            access_token="mock-google-token-xyz",
            cloud_id="cloud-999",
            issue_key="CCS-10",
        )

