"""Discovery Engine Federated MCP Toolset for Google ADK.

Dynamically discovers and wraps Model Context Protocol (MCP) tools exposed
by Discovery Engine's Jira Federated Data Connector into native ADK BaseTools.
The LLM directly receives the tool definitions and schemas (e.g. search_issues with JQL,
get_issue with issueIdOrKey, list_projects) without requiring hand-coded wrapper functions.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.base_toolset import BaseToolset
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from .auth import resolve_user_oauth_token
from .config import ConnectorConfig
from .jira_connector_client import JiraFederatedConnectorClient

logger = logging.getLogger(__name__)


class DiscoveryEngineConnectorTool(BaseTool):
    """ADK Tool dynamically backed by an MCP tool on Discovery Engine's Jira Connector."""

    def __init__(
        self,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        client: JiraFederatedConnectorClient,
    ):
        super().__init__(name=name, description=description)
        self.input_schema = input_schema or {"type": "object", "properties": {}}
        self.client = client

    def _get_declaration(self) -> types.FunctionDeclaration:
        """Exposes the MCP JSON schema to Gemini as a native function declaration."""
        return types.FunctionDeclaration(
            name=self.name,
            description=self.description,
            parameters_json_schema=self.input_schema,
        )

    async def run_async(
        self,
        *,
        args: dict[str, Any],
        tool_context: Optional[ToolContext] = None,
    ) -> Any:
        """Executes the tool via Discovery Engine :invokeConnectorMcp."""
        access_token, token_source = resolve_user_oauth_token(tool_context=tool_context)
        if not access_token:
            return {
                "status": "error",
                "message": (
                    "No Google Cloud access token found for authentication. "
                    "Please provide an authorized user session token."
                ),
            }

        # Verify end-user 3LO OAuth authorization status in Auth Manager
        auth_status = self.client.check_oauth_status(access_token=access_token)
        if not auth_status.get("authorized", False):
            auth_uri = auth_status.get("authorization_uri") or self.client.config.default_atlassian_auth_uri
            return {
                "status": "unauthorized",
                "message": (
                    "I cannot retrieve or modify your Jira data because you are not authorized to access Jira. "
                    f"Please authorize Jira Cloud by visiting this URL: {auth_uri}\n"
                    "After you authorize, you will be redirected to a URL starting with "
                    "https://vertexaisearch.cloud.google.com/oauth-redirect?code=.... "
                    "Please paste that full URL back here so I can complete the consent handshake."
                ),
                "authorization_uri": auth_uri,
            }

        # Forward execution to Discovery Engine invokeConnectorMcp
        try:
            return self.client.invoke_mcp_tool(
                access_token=access_token,
                tool_name=self.name,
                arguments=args or {},
            )
        except Exception as e:
            logger.error("Failed to execute MCP tool %s: %s", self.name, e)
            return {
                "status": "error",
                "message": f"Execution of {self.name} failed: {e}",
            }


class DiscoveryEngineMcpToolset(BaseToolset):
    """ADK Toolset that dynamically queries Discovery Engine for federated Jira MCP tools."""

    def __init__(
        self,
        client: Optional[JiraFederatedConnectorClient] = None,
        tool_filter: Optional[list[str]] = None,
        tool_name_prefix: Optional[str] = None,
    ):
        super().__init__(tool_filter=tool_filter, tool_name_prefix=tool_name_prefix)
        self.client = client or JiraFederatedConnectorClient()
        self._cached_tools: Optional[list[BaseTool]] = None

    async def get_tools(
        self,
        readonly_context: Optional[ReadonlyContext] = None,
    ) -> list[BaseTool]:
        """Dynamically discovers all MCP tools from Discovery Engine."""
        if self._cached_tools is not None:
            return [t for t in self._cached_tools if self._is_tool_selected(t, readonly_context)]

        access_token, _ = resolve_user_oauth_token()
        try:
            mcp_tool_defs = self.client.list_mcp_tools(access_token=access_token or "")
        except Exception as e:
            logger.warning("Failed to list MCP tools from Discovery Engine: %s. Using standard defaults.", e)
            mcp_tool_defs = []

        # If Discovery Engine returned tools, wrap them
        tools: list[BaseTool] = []
        for defn in mcp_tool_defs:
            name = defn.get("name")
            if not name:
                continue
            desc = defn.get("description", "")
            schema = defn.get("inputSchema", {})
            tool = DiscoveryEngineConnectorTool(
                name=name,
                description=desc,
                input_schema=schema,
                client=self.client,
            )
            tools.append(tool)

        self._cached_tools = tools
        return [t for t in tools if self._is_tool_selected(t, readonly_context)]
