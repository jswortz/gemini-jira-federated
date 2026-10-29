"""Unit tests for ADK Agent tools and google.adk.tools.mcp_tool.McpToolset integration."""

from unittest.mock import MagicMock, patch
import pytest

from google.adk.tools.mcp_tool import McpToolset
from jira_federated_agent import agent


def test_agent_tools_registered():
    """Verifies that the agent has the built-in google.adk.tools.mcp_tool.McpToolset registered."""
    tool_types = [type(t) for t in agent.root_agent.tools]
    assert McpToolset in tool_types

    tool_names = [getattr(t, "__name__", getattr(t, "name", str(t))) for t in agent.root_agent.tools]
    assert "check_jira_oauth_status" in tool_names
    assert "complete_jira_oauth_consent" in tool_names


@pytest.mark.asyncio
async def test_agent_toolset_provides_mcp_tools():
    """Verifies that the agent's McpToolset dynamically resolves Jira MCP tools."""
    toolset = next(t for t in agent.root_agent.tools if isinstance(t, McpToolset))
    tools = await toolset.get_tools()
    tool_names = [t.name for t in tools]
    assert "search_issues" in tool_names
    assert "get_issue" in tool_names
    assert "list_projects" in tool_names
    assert "create_comment" in tool_names
    assert "create_issue" in tool_names
    await toolset.close()


def test_search_jira_issues_tool():
    with patch.object(agent, "resolve_user_oauth_token", return_value=("fake-google-token", "test")), \
         patch.object(agent._CLIENT, "search_issues", return_value={"status": "success", "count": 1, "issues": [{"key": "GEAP-3"}]}):
        res = agent.search_jira_issues(query="test", max_results=5)
        assert res["status"] == "success"
        assert res["issues"][0]["key"] == "GEAP-3"


def test_get_jira_issue_tool():
    with patch.object(agent, "resolve_user_oauth_token", return_value=("fake-google-token", "test")), \
         patch.object(agent._CLIENT, "get_issue", return_value={"status": "success", "issue": {"key": "GEAP-3", "title": "Test Issue"}}):
        res = agent.get_jira_issue(issue_key="GEAP-3")
        assert res["status"] == "success"
        assert res["issue"]["title"] == "Test Issue"


def test_create_jira_comment_tool():
    with patch.object(agent, "resolve_user_oauth_token", return_value=("fake-google-token", "test")), \
         patch.object(agent._CLIENT, "create_comment", return_value={"status": "success", "comment_id": 10034}):
        res = agent.create_jira_comment(issue_key="GEAP-3", comment_body="Adding comment")
        assert res["status"] == "success"
        assert res["comment_id"] == 10034


def test_list_jira_comments_tool():
    with patch.object(agent, "resolve_user_oauth_token", return_value=("fake-google-token", "test")), \
         patch.object(agent._CLIENT, "list_comments", return_value={"status": "success", "comments": [{"id": 10033}]}):
        res = agent.list_jira_comments(issue_key="GEAP-3")
        assert res["status"] == "success"
        assert res["comments"][0]["id"] == 10033


def test_create_jira_issue_tool():
    with patch.object(agent, "resolve_user_oauth_token", return_value=("fake-google-token", "test")), \
         patch.object(agent._CLIENT, "create_issue", return_value={"status": "success", "issue_key": "GEAP-10"}):
        res = agent.create_jira_issue(
            project_key="GEAP",
            summary="New task from tool",
            issue_type="Task",
            description="Details",
        )
        assert res["status"] == "success"
        assert res["issue_key"] == "GEAP-10"


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
