#!/usr/bin/env python3
"""Configures an Atlassian 3LO Auth Provider in Google Cloud using Secret Manager.

Implements Pattern 2:
1. Stores or retrieves Atlassian Jira OAuth Client ID and Secret in Google Cloud Secret Manager.
2. Grants Secret Manager Secret Accessor role to the Discovery Engine and Agent Engine service agents.
3. Creates or updates the Discovery Engine Authorization resource (`authorizations/jira-oauth-provider`).
4. Binds the Authorization to the Gemini Enterprise registered agent (`authorizationConfig.toolAuthorizations`).

Usage:
  # With explicit credentials (creates/updates Secret Manager and provisions Auth Provider):
  uv run python scripts/setup_jira_auth_provider.py \\
    --client-id="YOUR_ATLASSIAN_CLIENT_ID" \\
    --client-secret="YOUR_ATLASSIAN_CLIENT_SECRET"

  # Or using existing secrets in Secret Manager:
  uv run python scripts/setup_jira_auth_provider.py

  # Dry-run preview:
  uv run python scripts/setup_jira_auth_provider.py --dry-run
"""

from __future__ import annotations

import argparse
import copy
import getpass
import json
import logging
import os
import sys
from typing import Any

from google.api_core import exceptions as google_exceptions
from google.cloud import secretmanager
import requests

# Add root directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from jira_federated_agent.auth import configure_vertex_ai_user_credentials
from jira_federated_agent.config import ConnectorConfig

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("setup_jira_auth_provider")

DEFAULT_CLIENT_ID_SECRET = "jira_oauth_client"
DEFAULT_CLIENT_SECRET_SECRET = "jira_oauth_secret"
DEFAULT_AUTH_PROVIDER_ID = "jira-oauth-provider"
ATLASSIAN_REDIRECT_URI = "https://vertexaisearch.cloud.google.com/oauth-redirect"
ATLASSIAN_AUTH_URI = (
    "https://auth.atlassian.com/authorize?audience=api.atlassian.com"
    f"&redirect_uri={requests.utils.quote(ATLASSIAN_REDIRECT_URI, safe='')}"
    "&response_type=code&prompt=consent"
)
ATLASSIAN_TOKEN_URI = "https://auth.atlassian.com/oauth/token"
DEFAULT_SCOPES = [
    "offline_access",
    "read:jira-user",
    "read:jira-work",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Setup Atlassian Jira OAuth Provider for Gemini Enterprise using Secret Manager."
    )
    config = ConnectorConfig()
    parser.add_argument(
        "--project-id",
        default=config.project_id or os.getenv("PROJECT_ID", ""),
        help="Google Cloud Project ID (default: %(default)s)",
    )
    parser.add_argument(
        "--project-number",
        default=config.project_number or os.getenv("PROJECT_NUMBER", ""),
        help="Google Cloud Project Number (default: %(default)s)",
    )
    parser.add_argument(
        "--location",
        default=config.location or "global",
        help="Discovery Engine Location (default: %(default)s)",
    )
    parser.add_argument(
        "--engine-id",
        default=config.engine_id or "grocery-workshop-engine",
        help="Gemini Enterprise Engine ID (default: %(default)s)",
    )
    parser.add_argument(
        "--agent-id",
        default=os.getenv("GEMINI_ENTERPRISE_AGENT_ID", ""),
        help="Gemini Enterprise Agent ID (default: %(default)s)",
    )
    parser.add_argument(
        "--authorization-id",
        default=os.getenv("JIRA_AUTHORIZATION_ID", DEFAULT_AUTH_PROVIDER_ID),
        help="Discovery Engine Authorization Resource ID (default: %(default)s)",
    )
    parser.add_argument(
        "--client-id-secret-name",
        default=DEFAULT_CLIENT_ID_SECRET,
        help="Secret Manager secret name for Jira OAuth Client ID (default: %(default)s)",
    )
    parser.add_argument(
        "--client-secret-secret-name",
        default=DEFAULT_CLIENT_SECRET_SECRET,
        help="Secret Manager secret name for Jira OAuth Client Secret (default: %(default)s)",
    )
    parser.add_argument(
        "--client-id",
        default=os.getenv("JIRA_OAUTH_CLIENT_ID", ""),
        help="Atlassian OAuth Client ID (optional; if omitted, reads from Secret Manager or prompts)",
    )
    parser.add_argument(
        "--client-secret",
        default=os.getenv("JIRA_OAUTH_CLIENT_SECRET", ""),
        help="Atlassian OAuth Client Secret (optional; if omitted, reads from Secret Manager or prompts)",
    )
    parser.add_argument(
        "--account",
        default=config.oauth_user_account or os.getenv("OAUTH_USER_ACCOUNT", ""),
        help="Google OAuth user account for authentication (default: %(default)s)",
    )
    parser.add_argument(
        "--scopes",
        nargs="+",
        default=DEFAULT_SCOPES,
        help="OAuth scopes to request (default: %(default)s)",
    )
    parser.add_argument(
        "--skip-agent-binding",
        action="store_true",
        help="Skip binding the authorization to the Gemini Enterprise agent",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview actions without making changes in Secret Manager or Discovery Engine",
    )
    return parser.parse_args()


def load_deployment_metadata_agent_id() -> str | None:
    """Loads agent ID from deployment_metadata.json if present."""
    metadata_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "deployment_metadata.json")
    )
    if os.path.exists(metadata_path):
        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                agent_full_name = data.get("gemini_enterprise_agent_id", "")
                if agent_full_name:
                    return agent_full_name.split("/")[-1]
        except Exception:
            pass
    return None


def get_or_create_secret(
    client: secretmanager.SecretManagerServiceClient,
    project_id: str,
    secret_name: str,
    payload_value: str = "",
    dry_run: bool = False,
) -> str:
    """Retrieves secret payload from Secret Manager, or creates/adds version if provided."""
    parent = f"projects/{project_id}"
    secret_path = f"projects/{project_id}/secrets/{secret_name}"
    latest_version_path = f"{secret_path}/versions/latest"

    # 1. If payload_value is provided, ensure secret exists and add version
    if payload_value:
        if dry_run:
            logger.info("[DRY-RUN] Would create/update secret %s with value (len=%d)", secret_name, len(payload_value))
            return payload_value

        try:
            client.get_secret(name=secret_path)
            logger.info("Secret %s already exists. Adding new secret version...", secret_name)
        except google_exceptions.NotFound:
            logger.info("Creating secret %s in project %s...", secret_name, project_id)
            client.create_secret(
                request={
                    "parent": parent,
                    "secret_id": secret_name,
                    "secret": {"replication": {"automatic": {}}},
                }
            )

        logger.info("Adding version to secret %s...", secret_name)
        client.add_secret_version(
            request={
                "parent": secret_path,
                "payload": {"data": payload_value.encode("utf-8")},
            }
        )
        return payload_value

    # 2. If payload_value not provided, attempt to read existing secret
    try:
        logger.info("Fetching existing secret %s from Secret Manager...", secret_name)
        response = client.access_secret_version(name=latest_version_path)
        secret_value = response.payload.data.decode("utf-8").strip()
        logger.info("Successfully fetched %s (len=%d) from Secret Manager.", secret_name, len(secret_value))
        return secret_value
    except google_exceptions.NotFound:
        logger.warning("Secret %s not found in project %s.", secret_name, project_id)
        return ""


def grant_secret_accessor_role(
    client: secretmanager.SecretManagerServiceClient,
    project_id: str,
    secret_name: str,
    member: str,
    dry_run: bool = False,
) -> None:
    """Grants roles/secretmanager.secretAccessor to a service account or service agent."""
    secret_path = f"projects/{project_id}/secrets/{secret_name}"
    if dry_run:
        logger.info("[DRY-RUN] Would grant roles/secretmanager.secretAccessor on %s to %s", secret_name, member)
        return

    try:
        policy = client.get_iam_policy(request={"resource": secret_path})
        role = "roles/secretmanager.secretAccessor"

        # Check if already granted
        for binding in policy.bindings:
            if binding.role == role and member in binding.members:
                logger.info("IAM: %s already has %s on %s.", member, role, secret_name)
                return

        # Add member to binding
        found = False
        for binding in policy.bindings:
            b_role = getattr(binding, "role", None) or (binding.get("role") if isinstance(binding, dict) else None)
            if b_role == role:
                if hasattr(binding, "members"):
                    binding.members.append(member)
                elif isinstance(binding, dict) and "members" in binding:
                    binding["members"].append(member)
                found = True
                break
        if not found:
            if hasattr(policy.bindings, "add"):
                policy.bindings.add(role=role, members=[member])
            else:
                try:
                    from google.iam.v1 import policy_pb2
                    policy.bindings.append(policy_pb2.Binding(role=role, members=[member]))
                except Exception:
                    policy.bindings.append({"role": role, "members": [member]})

        client.set_iam_policy(request={"resource": secret_path, "policy": policy})
        logger.info("IAM: Successfully granted %s on %s to %s.", role, secret_name, member)
    except Exception as exc:
        logger.warning("Could not update IAM policy on %s: %s", secret_name, exc)


def get_google_access_token(account: str, project_id: str) -> str:
    """Obtains a valid Google OAuth access token using credentials."""
    import google.auth
    import google.auth.transport.requests

    configure_vertex_ai_user_credentials(account=account, project_id=project_id)
    creds, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    auth_req = google.auth.transport.requests.Request()
    if not creds.valid:
        creds.refresh(auth_req)
    return str(creds.token)


def get_or_create_discovery_engine_authorization(
    access_token: str,
    project_number: str,
    location: str,
    authorization_id: str,
    client_id: str,
    client_secret: str,
    scopes: list[str],
    dry_run: bool = False,
) -> dict[str, Any]:
    """Creates or verifies the Discovery Engine Authorization resource."""
    base_url = (
        "https://discoveryengine.googleapis.com/v1alpha"
        if location == "global"
        else f"https://{location}-discoveryengine.googleapis.com/v1alpha"
    )
    auth_name = f"projects/{project_number}/locations/{location}/authorizations/{authorization_id}"
    get_url = f"{base_url}/{auth_name}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "x-goog-user-project": project_number,
        "Content-Type": "application/json",
    }

    # 1. Check if authorization already exists
    logger.info("Checking if Discovery Engine Authorization %s exists...", auth_name)
    get_resp = requests.get(get_url, headers=headers, timeout=30)
    payload = {
        "displayName": "Jira 3LO Auth Provider",
        "serverSideOauth2": {
            "clientId": client_id,
            "clientSecret": client_secret,
            "tokenUri": ATLASSIAN_TOKEN_URI,
            "authorizationUri": ATLASSIAN_AUTH_URI,
            "scopes": scopes,
            "pkceVerificationEnabled": False,
        },
    }

    if get_resp.ok:
        logger.info("Discovery Engine Authorization %s already exists. Checking if update required...", auth_name)
        existing_data = get_resp.json()
        existing_oauth = existing_data.get("serverSideOauth2", {})
        if (
            existing_oauth.get("authorizationUri") != ATLASSIAN_AUTH_URI
            or existing_oauth.get("scopes") != scopes
            or existing_oauth.get("clientId") != client_id
        ):
            if dry_run:
                logger.info("[DRY-RUN] Would update Authorization via PATCH %s?updateMask=serverSideOauth2", get_url)
                return {"name": auth_name, "serverSideOauth2": payload["serverSideOauth2"]}
            logger.info("Updating existing Discovery Engine Authorization %s...", auth_name)
            patch_url = f"{get_url}?updateMask=serverSideOauth2"
            patch_resp = requests.patch(patch_url, headers=headers, json=payload, timeout=30)
            if not patch_resp.ok:
                raise RuntimeError(
                    f"Failed to update Discovery Engine Authorization: HTTP {patch_resp.status_code} - {patch_resp.text}"
                )
            logger.info("Successfully updated Discovery Engine Authorization %s.", auth_name)
            return patch_resp.json()

        logger.info("Discovery Engine Authorization %s is up to date.", auth_name)
        return existing_data

    # 2. Create the authorization resource
    create_url = f"{base_url}/projects/{project_number}/locations/{location}/authorizations?authorizationId={authorization_id}"

    if dry_run:
        masked_payload = copy.deepcopy(payload)
        if "serverSideOauth2" in masked_payload and "clientSecret" in masked_payload["serverSideOauth2"]:
            masked_payload["serverSideOauth2"]["clientSecret"] = "******"
        logger.info("[DRY-RUN] Would create Authorization via POST %s with payload:", create_url)
        logger.info(json.dumps(masked_payload, indent=2))
        return {"name": auth_name, "serverSideOauth2": payload["serverSideOauth2"]}

    logger.info("Creating Discovery Engine Authorization %s...", auth_name)
    post_resp = requests.post(create_url, headers=headers, json=payload, timeout=30)
    if not post_resp.ok:
        raise RuntimeError(
            f"Failed to create Discovery Engine Authorization: HTTP {post_resp.status_code} - {post_resp.text}"
        )

    logger.info("Successfully created Discovery Engine Authorization %s.", auth_name)
    return post_resp.json()


def bind_authorization_to_agent(
    access_token: str,
    project_number: str,
    location: str,
    engine_id: str,
    agent_id: str,
    authorization_name: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Updates the Gemini Enterprise registered agent to bind the authorization in toolAuthorizations."""
    base_url = (
        "https://discoveryengine.googleapis.com/v1alpha"
        if location == "global"
        else f"https://{location}-discoveryengine.googleapis.com/v1alpha"
    )
    agent_name = (
        f"projects/{project_number}/locations/{location}/collections/default_collection"
        f"/engines/{engine_id}/assistants/default_assistant/agents/{agent_id}"
    )
    url = f"{base_url}/{agent_name}?updateMask=authorizationConfig"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "x-goog-user-project": project_number,
        "Content-Type": "application/json",
    }

    # Fetch current agent definition
    logger.info("Fetching agent details for %s...", agent_id)
    get_resp = requests.get(f"{base_url}/{agent_name}", headers=headers, timeout=30)
    if not get_resp.ok:
        raise RuntimeError(
            f"Failed to fetch agent {agent_id}: HTTP {get_resp.status_code} - {get_resp.text}"
        )

    agent_data = get_resp.json()
    existing_auth_config = agent_data.get("authorizationConfig", {})
    existing_tools = existing_auth_config.get("toolAuthorizations", [])

    if authorization_name in existing_tools:
        logger.info("Agent %s is already bound to %s.", agent_id, authorization_name)
        return agent_data

    # Update toolAuthorizations
    updated_tools = list(set(existing_tools + [authorization_name]))
    payload = {
        "authorizationConfig": {
            "toolAuthorizations": updated_tools,
        }
    }

    if dry_run:
        logger.info("[DRY-RUN] Would update agent via PATCH %s with payload:", url)
        logger.info(json.dumps(payload, indent=2))
        return payload

    logger.info("Binding authorization %s to agent %s...", authorization_name, agent_id)
    patch_resp = requests.patch(url, headers=headers, json=payload, timeout=30)
    if not patch_resp.ok:
        raise RuntimeError(
            f"Failed to update agent authorizationConfig: HTTP {patch_resp.status_code} - {patch_resp.text}"
        )

    logger.info("Successfully bound authorization to Gemini Enterprise Agent %s.", agent_id)
    return patch_resp.json()


def main() -> None:
    args = parse_args()
    logger.info("Starting Jira 3LO Auth Provider Setup (Pattern 2)...")
    logger.info("Target Project: %s (Number: %s)", args.project_id, args.project_number)

    # 1. Configure authentication
    logger.info("Authenticating with Google Cloud account: %s", args.account)
    token = get_google_access_token(args.account, args.project_id)
    sm_client = secretmanager.SecretManagerServiceClient()

    # 2. Resolve Client ID & Secret from args, env, or Secret Manager
    client_id = args.client_id
    client_secret = args.client_secret

    if not client_id:
        client_id = get_or_create_secret(
            sm_client, args.project_id, args.client_id_secret_name, dry_run=args.dry_run
        )
        if not client_id and not args.dry_run:
            client_id = input(f"Enter Atlassian OAuth Client ID (will be stored in Secret Manager as {args.client_id_secret_name}): ").strip()
            if client_id:
                get_or_create_secret(
                    sm_client, args.project_id, args.client_id_secret_name, payload_value=client_id, dry_run=args.dry_run
                )

    if not client_secret:
        client_secret = get_or_create_secret(
            sm_client, args.project_id, args.client_secret_secret_name, dry_run=args.dry_run
        )
        if not client_secret and not args.dry_run:
            client_secret = getpass.getpass(f"Enter Atlassian OAuth Client Secret (will be stored in Secret Manager as {args.client_secret_secret_name}): ").strip()
            if client_secret:
                get_or_create_secret(
                    sm_client, args.project_id, args.client_secret_secret_name, payload_value=client_secret, dry_run=args.dry_run
                )

    if not client_id or not client_secret:
        if args.dry_run:
            logger.info("[DRY-RUN] Using placeholder client_id and client_secret for preview.")
            client_id = client_id or "dry-run-client-id.apps.atlassian.com"
            client_secret = client_secret or "dry-run-client-secret-12345"
        else:
            logger.error("Missing Atlassian OAuth Client ID or Client Secret. Cannot proceed.")
            sys.exit(1)

    # 3. Grant IAM permissions on the Secret Manager secrets
    discovery_engine_sa = f"serviceAccount:service-{args.project_number}@gcp-sa-discoveryengine.iam.gserviceaccount.com"
    compute_sa = f"serviceAccount:{args.project_number}-compute@developer.gserviceaccount.com"

    for secret_name in (args.client_id_secret_name, args.client_secret_secret_name):
        grant_secret_accessor_role(sm_client, args.project_id, secret_name, discovery_engine_sa, dry_run=args.dry_run)
        grant_secret_accessor_role(sm_client, args.project_id, secret_name, compute_sa, dry_run=args.dry_run)

    # 4. Create Discovery Engine Authorization
    auth_res = get_or_create_discovery_engine_authorization(
        access_token=token,
        project_number=args.project_number,
        location=args.location,
        authorization_id=args.authorization_id,
        client_id=client_id,
        client_secret=client_secret,
        scopes=args.scopes,
        dry_run=args.dry_run,
    )
    auth_name = auth_res.get(
        "name",
        f"projects/{args.project_number}/locations/{args.location}/authorizations/{args.authorization_id}",
    )

    # 5. Bind authorization to the registered agent in Gemini Enterprise
    agent_id = args.agent_id or load_deployment_metadata_agent_id()
    if not args.skip_agent_binding and agent_id:
        bind_authorization_to_agent(
            access_token=token,
            project_number=args.project_number,
            location=args.location,
            engine_id=args.engine_id,
            agent_id=agent_id,
            authorization_name=auth_name,
            dry_run=args.dry_run,
        )

    # 6. Print Summary and Atlassian App Configuration Instructions
    print("\n" + "=" * 80)
    print("✅ JIRA OAUTH AUTH PROVIDER SETUP COMPLETE")
    print("=" * 80)
    print(f"Secret Manager Client ID Secret:     projects/{args.project_id}/secrets/{args.client_id_secret_name}")
    print(f"Secret Manager Client Secret Secret: projects/{args.project_id}/secrets/{args.client_secret_secret_name}")
    print(f"Discovery Engine Authorization:      {auth_name}")
    print(f"Bound to Gemini Enterprise Agent:    {agent_id}")
    print("-" * 80)
    print("CRITICAL: CONFIGURE ATLASSIAN DEVELOPER CONSOLE")
    print("In your Atlassian App (https://developer.atlassian.com/console/myapps):")
    print("1. Go to 'Authorization' -> 'OAuth 2.0 (3LO)' -> 'Configure'")
    print(f"2. Add this Callback URL: {ATLASSIAN_REDIRECT_URI}")
    print("3. Ensure the following Permissions (Scopes) are added under 'Jira API':")
    for s in args.scopes:
        print(f"   - {s}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
