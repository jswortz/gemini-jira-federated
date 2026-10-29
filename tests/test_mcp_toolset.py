"""Unit tests for DiscoveryEngineMcpToolset and DiscoveryEngineConnectorTool."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from google.adk.tools.base_toolset import BaseToolset
from google.genai import types

from jira_federated_agent.config import ConnectorConfig
from jira_federated_agent.jira_connector_client import JiraFederatedConnectorClient
from jira_federated_agent.mcp_toolset import (
    DiscoveryEngineConnectorTool,
    DiscoveryEngineMcpToolset,
)


@pytest.fixture
def mock_connector_client():
    client = MagicMock(spec=JiraFederatedConnectorClient)
    client.config = ConnectorConfig(
        project_id="test-proj",
        project_number="123456789",
        jira_instance_uri="https://test-jira.atlassian.net",
    )
    client.list_mcp_tools.return_value = [
        {
            "name": "search_issues",
            "description": "Searches for Jira issues using JQL query string.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "jql": {
                        "type": "string",
                        "description": "The JQL query string to search for issues.",
                    }
                },
                "required": ["jql"],
            },
        },
        {
            "name": "get_issue",
            "description": "Gets details of a single Jira issue by issue key or ID.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "issueIdOrKey": {
                        "type": "string",
                        "description": "Jira issue key (e.g. CCS-50) or numeric ID.",
                    }
                },
                "required": ["issueIdOrKey"],
            },
        },
        {
            "name": "list_projects",
            "description": "Lists Jira projects accessible to the user.",
            "inputSchema": {
                "type": "object",
                "properties": {},
            },
        },
    ]
    client.check_oauth_status.return_value = {
        "authorized": True,
        "auth_state": "AUTHORIZED",
        "has_active_3lo_token": True,
    }
    return client


@pytest.mark.asyncio
async def test_toolset_get_tools_dynamic_discovery(mock_connector_client):
    toolset = DiscoveryEngineMcpToolset(client=mock_connector_client)
    assert isinstance(toolset, BaseToolset)

    tools = await toolset.get_tools()
    assert len(tools) == 3
    tool_names = [t.name for t in tools]
    assert "search_issues" in tool_names
    assert "get_issue" in tool_names
    assert "list_projects" in tool_names

    # Check function declaration schema
    search_tool = next(t for t in tools if t.name == "search_issues")
    decl = search_tool._get_declaration()
    assert isinstance(decl, types.FunctionDeclaration)
    assert decl.name == "search_issues"
    assert "JQL query string" in decl.description
    assert decl.parameters_json_schema["type"] == "object"
    assert "jql" in decl.parameters_json_schema["properties"]


@pytest.mark.asyncio
async def test_toolset_filtering(mock_connector_client):
    toolset = DiscoveryEngineMcpToolset(
        client=mock_connector_client,
        tool_filter=["search_issues"],
    )
    tools = await toolset.get_tools()
    assert len(tools) == 1
    assert tools[0].name == "search_issues"


@pytest.mark.asyncio
async def test_connector_tool_run_async_success(mock_connector_client):
    mock_connector_client.invoke_tool.return_value = {
        "status": "success",
        "tool": "search_issues",
        "issues": [{"key": "CCS-50", "summary": "Fix billing pipeline"}],
    }

    tool = DiscoveryEngineConnectorTool(
        name="search_issues",
        description="Searches Jira issues",
        input_schema={"type": "object", "properties": {"jql": {"type": "string"}}},
        client=mock_connector_client,
    )

    ctx = MagicMock()
    ctx.state = {"temp:jira_federated_oauth_token": "google-oauth-token-123"}

    result = await tool.run_async(
        args={"jql": 'project = "CCS"'},
        tool_context=ctx,
    )
    assert result["status"] == "success"
    assert len(result["issues"]) == 1
    mock_connector_client.invoke_tool.assert_called_once_with(
        access_token="google-oauth-token-123",
        tool_name="search_issues",
        arguments={"jql": 'project = "CCS"'},
    )


@pytest.mark.asyncio
async def test_connector_tool_run_async_unauthorized(mock_connector_client):
    mock_connector_client.invoke_tool.return_value = {
        "status": "error",
        "message": "401 Unauthorized: Atlassian 3LO token missing or expired.",
    }
    mock_connector_client.check_oauth_status.return_value = {
        "authorized": False,
        "auth_state": "UNAUTHORIZED",
        "authorization_uri": "https://auth.atlassian.com/authorize?prompt=consent",
    }

    tool = DiscoveryEngineConnectorTool(
        name="search_issues",
        description="Searches Jira issues",
        input_schema={"type": "object", "properties": {"jql": {"type": "string"}}},
        client=mock_connector_client,
    )

    ctx = MagicMock()
    ctx.state = {"temp:jira_federated_oauth_token": "google-oauth-token-123"}

    result = await tool.run_async(
        args={"jql": 'project = "CCS"'},
        tool_context=ctx,
    )
    assert result["status"] == "unauthorized"
    assert "https://auth.atlassian.com" in result["authorization_uri"]
    assert "Please authorize Jira Cloud" in result["message"]
    mock_connector_client.invoke_tool.assert_called_once()


@pytest.mark.asyncio
async def test_connector_tool_run_async_error_handling(mock_connector_client):
    mock_connector_client.invoke_tool.return_value = {
        "status": "error",
        "message": "JQL parse error: unexpected token",
    }

    tool = DiscoveryEngineConnectorTool(
        name="search_issues",
        description="Searches Jira issues",
        input_schema={"type": "object", "properties": {"jql": {"type": "string"}}},
        client=mock_connector_client,
    )

    ctx = MagicMock()
    ctx.state = {"temp:jira_federated_oauth_token": "google-oauth-token-123"}

    result = await tool.run_async(
        args={"jql": "INVALID JQL SYNTAX"},
        tool_context=ctx,
    )
    assert result["status"] == "error"
    assert "JQL parse error" in result["message"]
