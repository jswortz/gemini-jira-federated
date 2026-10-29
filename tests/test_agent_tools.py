"""Unit tests for ADK Agent tools and DiscoveryEngineMcpToolset integration."""

from unittest.mock import MagicMock, patch
import pytest

from jira_federated_agent import agent
from jira_federated_agent.mcp_toolset import DiscoveryEngineMcpToolset


def test_agent_tools_registered():
    """Verifies that the agent has the DiscoveryEngineMcpToolset registered."""
    tool_types = [type(t) for t in agent.root_agent.tools]
    assert DiscoveryEngineMcpToolset in tool_types
    assert len(agent.root_agent.tools) == 1


@pytest.mark.asyncio
async def test_agent_toolset_provides_mcp_tools():
    """Verifies that the agent's toolset dynamically resolves Jira MCP tools."""
    toolset = next(t for t in agent.root_agent.tools if isinstance(t, DiscoveryEngineMcpToolset))
    tools = await toolset.get_tools()
    tool_names = [t.name for t in tools]
    assert "search_issues" in tool_names
    assert "get_issue" in tool_names
    assert "list_projects" in tool_names
    assert "create_comment" in tool_names
    assert "create_issue" in tool_names


@pytest.mark.asyncio
async def test_agent_toolset_executes_mcp_tools():
    """Verifies that discovered MCP tools execute via invoke_tool when authorized."""
    toolset = next(t for t in agent.root_agent.tools if isinstance(t, DiscoveryEngineMcpToolset))
    tools = await toolset.get_tools()
    tool_map = {t.name: t for t in tools}

    # 1. Google token path
    with patch.object(toolset.client, "invoke_mcp_tool", return_value={"status": "success", "data": {"issues": [{"key": "GEAP-3"}]}}) as mock_invoke, \
         patch("jira_federated_agent.mcp_toolset.resolve_user_oauth_token", return_value=("mock-google-token-xyz", "test")):
        res = await tool_map["search_issues"].run_async(args={"jql": "project = CCS"})
        assert res["status"] == "success"
        mock_invoke.assert_called_once_with(
            access_token="mock-google-token-xyz",
            tool_name="search_issues",
            arguments={"jql": "project = CCS"},
        )

    # 2. Atlassian token path (from Gemini Enterprise)
    with patch.object(toolset.client, "_get_atlassian_cloud_id", return_value="cloud-123"), \
         patch.object(toolset.client, "_search_issues_atlassian_rest", return_value={"status": "success", "source": "atlassian_cloud_rest", "issues": [{"key": "CCS-50"}]}) as mock_atlassian, \
         patch("jira_federated_agent.mcp_toolset.resolve_user_oauth_token", return_value=("atlassian-3lo-jwt-token", "test")):
        res2 = await tool_map["search_issues"].run_async(args={"jql": "project = CCS"})
        assert res2["status"] == "success"
        assert res2["source"] == "atlassian_cloud_rest"
        mock_atlassian.assert_called_once()


@pytest.mark.asyncio
async def test_agent_toolset_handles_unauthorized_user():
    """Verifies that MCP tools intercept unauthorized users and return authorization guidance."""
    toolset = next(t for t in agent.root_agent.tools if isinstance(t, DiscoveryEngineMcpToolset))
    tools = await toolset.get_tools()
    tool_map = {t.name: t for t in tools}

    with patch.object(toolset.client, "invoke_tool", return_value={"status": "error", "message": "401 Unauthorized"}), \
         patch.object(toolset.client, "check_oauth_status", return_value={"authorized": False, "authorization_uri": "https://auth.atlassian.com/authorize?custom"}), \
         patch("jira_federated_agent.mcp_toolset.resolve_user_oauth_token", return_value=("fake-google-token", "test")):
        res = await tool_map["get_issue"].run_async(args={"issueIdOrKey": "GEAP-3"})
        assert res["status"] == "unauthorized"
        assert "https://auth.atlassian.com/authorize?custom" in res["message"]


def test_check_jira_oauth_status_tool():
    with patch.object(agent, "resolve_user_oauth_token", return_value=("fake-google-token", "test")), \
         patch.object(agent._CLIENT, "check_oauth_status", return_value={"authorized": True, "auth_state": "AUTHORIZED"}):
        res = agent.check_jira_oauth_status()
        assert res["authorized"] is True
        assert res["auth_state"] == "AUTHORIZED"


def test_complete_jira_oauth_consent_tool():
    with patch.object(agent, "resolve_user_oauth_token", return_value=("fake-google-token", "test")), \
         patch.object(agent._CLIENT, "complete_oauth_consent", return_value={"status": "success"}):
        res = agent.complete_jira_oauth_consent(
            redirect_url="https://vertexaisearch.cloud.google.com/oauth-redirect?code=xyz"
        )
        assert res["status"] == "success"
