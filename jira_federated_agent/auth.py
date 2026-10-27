"""OAuth2 authentication utilities for ADK Web and Discovery Engine Federated Connectors."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import subprocess
from typing import Any

from fastapi.openapi.models import OAuth2
from fastapi.openapi.models import OAuthFlowAuthorizationCode
from fastapi.openapi.models import OAuthFlows
import google.auth
import google.auth.transport.requests
from google.oauth2.credentials import Credentials as GoogleOAuthCredentials
from google.adk.auth.auth_credential import AuthCredential
from google.adk.auth.auth_credential import AuthCredentialTypes
from google.adk.auth.auth_credential import OAuth2Auth
from google.adk.auth.auth_tool import AuthConfig
from google.adk.tools.tool_context import ToolContext

logger = logging.getLogger(__name__)

CREDENTIAL_KEY = "jira_federated_google_oauth"
STATE_TOKEN_KEY = "temp:jira_federated_oauth_token"


def build_adk_oauth_config(
    client_id: str | None = None,
    client_secret: str | None = None,
    authorization_uri: str = "https://accounts.google.com/o/oauth2/v2/auth",
    token_uri: str = "https://oauth2.googleapis.com/token",
) -> AuthConfig:
    """Builds an ADK AuthConfig for interactive 3-Legged OAuth2 in `adk web`."""
    resolved_client_id = client_id or os.getenv("OAUTH_CLIENT_ID", "")
    resolved_client_secret = client_secret or os.getenv("OAUTH_CLIENT_SECRET", "")

    return AuthConfig(
        auth_scheme=OAuth2(
            flows=OAuthFlows(
                authorizationCode=OAuthFlowAuthorizationCode(
                    authorizationUrl=authorization_uri,
                    tokenUrl=token_uri,
                    scopes={
                        "https://www.googleapis.com/auth/cloud-platform": (
                            "Access Google Cloud Discovery Engine and Federated Jira Connector"
                        ),
                    },
                )
            )
        ),
        raw_auth_credential=AuthCredential(
            auth_type=AuthCredentialTypes.OAUTH2,
            oauth2=OAuth2Auth(
                client_id=resolved_client_id,
                client_secret=resolved_client_secret,
            ),
        ),
        credential_key=CREDENTIAL_KEY,
    )


def extract_token_from_tool_context(tool_context: ToolContext | Any | None) -> str | None:
    """Extracts an OAuth2 access token from ADK ToolContext if present."""
    if tool_context is None:
        return None

    # 1. Check explicit state key
    state = getattr(tool_context, "state", None)
    if isinstance(state, dict) and state.get(STATE_TOKEN_KEY):
        return str(state[STATE_TOKEN_KEY])

    # 2. Check ADK AuthConfig exchange response if interactive OAuth was used
    if hasattr(tool_context, "get_auth_response"):
        try:
            auth_cfg = build_adk_oauth_config()
            auth_resp = tool_context.get_auth_response(auth_cfg)
            if auth_resp and auth_resp.oauth2 and auth_resp.oauth2.access_token:
                token = auth_resp.oauth2.access_token
                if isinstance(state, dict):
                    state[STATE_TOKEN_KEY] = token
                return token
        except Exception:
            logger.debug("No exchanged ADK AuthConfig credential in ToolContext.")

    return None


def load_gcloud_user_oauth_credentials(
    account: str, quota_project_id: str = "wortz-project-352116"
) -> GoogleOAuthCredentials | None:
    """Loads end-user OAuth2 credentials from local gcloud sqlite credential store in memory."""
    db_path = os.path.expanduser("~/.config/gcloud/credentials.db")
    if not os.path.exists(db_path):
        return None

    try:
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT value FROM credentials WHERE account_id = ?", (account,)
            ).fetchone()
        finally:
            conn.close()

        if not row:
            return None

        data = json.loads(row[0])
        if data.get("type") != "authorized_user":
            return None

        creds = GoogleOAuthCredentials(
            token=None,
            refresh_token=data.get("refresh_token"),
            token_uri=data.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=data.get("client_id"),
            client_secret=data.get("client_secret"),
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
            quota_project_id=quota_project_id,
        )
        creds.refresh(google.auth.transport.requests.Request())
        return creds
    except Exception as exc:
        logger.debug("Could not refresh gcloud SQLite OAuth credential: %s", exc)
        return None


def resolve_user_oauth_token(
    tool_context: ToolContext | Any | None = None,
    account: str | None = None,
    project_id: str = "wortz-project-352116",
) -> tuple[str | None, str]:
    """Resolves the end-user's OAuth2 access token across ADK Web, env, and gcloud OAuth.

    Returns:
        tuple[token, source_description]
    """
    # 1. Check ADK ToolContext (from interactive OAuth flow in adk web)
    ctx_token = extract_token_from_tool_context(tool_context)
    if ctx_token:
        return ctx_token, "adk_web:ToolContext"

    # 2. If interactive OAuth is forced and OAuth client credentials exist, request via ADK UI
    if (
        tool_context is not None
        and os.getenv("ADK_INTERACTIVE_OAUTH", "false").lower() == "true"
        and os.getenv("OAUTH_CLIENT_ID")
        and os.getenv("OAUTH_CLIENT_SECRET")
        and hasattr(tool_context, "request_credential")
    ):
        tool_context.request_credential(build_adk_oauth_config())
        return None, "adk_web:pending_oauth_consent"

    # 3. Check explicit environment variable override
    env_token = os.getenv("GOOGLE_OAUTH_ACCESS_TOKEN", "").strip()
    if env_token:
        return env_token, "env:GOOGLE_OAUTH_ACCESS_TOKEN"

    # 4. Load and refresh OAuth2 user credentials for the configured account
    target_account = account or os.getenv(
        "OAUTH_USER_ACCOUNT", "admin@jwortz.altostrat.com"
    )
    creds = load_gcloud_user_oauth_credentials(
        account=target_account, quota_project_id=project_id
    )
    if creds and creds.token:
        return creds.token, f"oauth_user:{target_account}"

    # 5. Fallback to gcloud CLI print-access-token for the specific user account
    try:
        proc = subprocess.run(
            ["gcloud", "auth", "print-access-token", target_account],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        token = proc.stdout.strip()
        if token:
            return token, f"gcloud_cli:{target_account}"
    except Exception as exc:
        logger.warning("Failed to obtain OAuth token via gcloud CLI: %s", exc)

    return None, "unauthenticated"


def configure_vertex_ai_user_credentials(
    account: str | None = None,
    project_id: str = "wortz-project-352116",
) -> None:
    """Ensures google.auth.default() uses the authorized user's OAuth credentials for Vertex AI.

    On multi-account workstations where ~/.config/gcloud/application_default_credentials.json
    is bound to a different identity, this bridges google.auth.default() in memory to the
    target OAuth user account without writing any credential files to disk.
    """
    target_account = account or os.getenv(
        "OAUTH_USER_ACCOUNT", "admin@jwortz.altostrat.com"
    )
    creds = load_gcloud_user_oauth_credentials(
        account=target_account, quota_project_id=project_id
    )
    if creds is None:
        return

    original_default = google.auth.default

    def _patched_default(
        scopes: Any = None,
        request: Any = None,
        quota_project_id: str | None = None,
        default_scopes: Any = None,
    ) -> tuple[Any, str]:
        try:
            if not creds.valid:
                creds.refresh(request or google.auth.transport.requests.Request())
            return creds, (quota_project_id or project_id)
        except Exception:
            return original_default(
                scopes=scopes,
                request=request,
                quota_project_id=quota_project_id,
                default_scopes=default_scopes,
            )

    google.auth.default = _patched_default
