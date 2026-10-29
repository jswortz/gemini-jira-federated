#!/usr/bin/env python3
"""Deploys or updates the jira_federated_agent on Vertex AI Agent Engine."""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import sys

from google.adk.cli import cli_deploy

from jira_federated_agent.auth import configure_vertex_ai_user_credentials
from jira_federated_agent.config import ConnectorConfig

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy Jira Federated Agent to Vertex AI Agent Engine")
    parser.add_argument("--reasoning-engine-id", default=None, help="Existing Reasoning Engine ID to update")
    parser.add_argument("--region", default="us-central1", help="Vertex AI region (default: us-central1)")
    parser.add_argument("--env-file", default=".env", help="Path to env file (default: .env)")
    args = parser.parse_args()

    config = ConnectorConfig()
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    agent_folder = os.path.join(repo_root, "jira_federated_agent")
    metadata_path = os.path.join(repo_root, "deployment_metadata.json")

    # Read reasoning engine ID from metadata if not explicitly provided
    reasoning_engine_id = args.reasoning_engine_id
    if not reasoning_engine_id and os.path.exists(metadata_path):
        with open(metadata_path) as fp:
            meta = json.load(fp)
            raw_id = meta.get("remote_agent_runtime_id", "")
            if "/" in raw_id:
                reasoning_engine_id = raw_id.split("/")[-1]
            elif raw_id:
                reasoning_engine_id = raw_id

    account = config.oauth_user_account
    if not account:
        try:
            import subprocess
            account = subprocess.check_output(
                ["gcloud", "config", "get-value", "account"], text=True
            ).strip()
        except Exception:
            pass

    logger.info("Target Project: %s (Number: %s)", config.project_id, config.effective_project_number)
    logger.info("Target Region:  %s", args.region)
    logger.info("Target Account: %s", account or "(Default)")
    logger.info("Reasoning Engine ID: %s", reasoning_engine_id or "(New Deployment)")

    configure_vertex_ai_user_credentials(account=account, project_id=config.project_id)

    import tempfile
    temp_env = os.path.join(tempfile.gettempdir(), f"adk_deploy_{os.getpid()}.env")
    with open(temp_env, "w") as fp:
        fp.write(f"DISCOVERY_ENGINE_PROJECT_ID={config.project_id}\n")
        fp.write(f"DISCOVERY_ENGINE_PROJECT_NUMBER={config.effective_project_number}\n")
        fp.write(f"DISCOVERY_ENGINE_LOCATION={config.location}\n")
        fp.write(f"DISCOVERY_ENGINE_ID={config.engine_id}\n")
        fp.write(f"JIRA_CONNECTOR_COLLECTION_ID={config.collection_id}\n")
        fp.write(f"JIRA_INSTANCE_URI={config.jira_instance_uri}\n")
        if config.jira_client_id:
            fp.write(f"JIRA_OAUTH_CLIENT_ID={config.jira_client_id}\n")
        fp.write(f"GEMINI_MODEL={config.model}\n")
        if account:
            fp.write(f"OAUTH_USER_ACCOUNT={account}\n")

    try:
        logger.info("Deploying to Vertex AI Agent Engine...")
        result = cli_deploy.to_agent_engine(
            agent_folder=agent_folder,
            agent_engine_id=reasoning_engine_id,
            adk_app="agent_engine_app",
            adk_app_object="root_agent",
            project=config.project_id,
            region=args.region,
            display_name="jira_federated_agent",
            description="Grounded Jira Assistant powered by the Gemini Enterprise Jira Federated Data Connector with per-user 3LO access control",
            env_file=temp_env,
            skip_agent_import_validation=True,
        )
    finally:
        if os.path.exists(temp_env):
            os.remove(temp_env)

    logger.info("Deployment result: %s", result)

    # Update deployment metadata timestamp if succeeded
    if os.path.exists(metadata_path):
        with open(metadata_path) as fp:
            meta = json.load(fp)
        meta["deployment_timestamp"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with open(metadata_path, "w") as fp:
            json.dump(meta, fp, indent=2)
            fp.write("\n")
        logger.info("Updated deployment_metadata.json with new deployment timestamp.")

    print("\n✅ Vertex AI Agent Engine deployment completed successfully!\n")


if __name__ == "__main__":
    main()
