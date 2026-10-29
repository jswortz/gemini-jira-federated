"""Unit tests for ADK Agent tools wrapping the Discovery Engine Federated MCP connector."""

from unittest.mock import MagicMock, patch
import pytest

from jira_federated_agent import agent


def test_agent_tools_registered():
    """Verifies that all expected Option A MCP tools are registered on root_agent."""
    tool_names = [t.__name__ for t in agent.root_agent.tools]
    expected = [
        "check_jira_oauth_status",
        "complete_jira_oauth_consent",
        "list_jira_projects",
        "search_jira_issues",
        "get_jira_issue",
        "create_jira_comment",
        "create_jira_issue",
        "list_jira_comments",
        "ask_gemini_enterprise_jira",
    ]
    for exp in expected:
        assert exp in tool_names, f"Missing tool {exp} in root_agent.tools"


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
