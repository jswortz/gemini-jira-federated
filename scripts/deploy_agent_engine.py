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

    logger.info("Target Project: %s (Number: %s)", config.project_id, config.project_number)
    logger.info("Target Region:  %s", args.region)
    logger.info("Reasoning Engine ID: %s", reasoning_engine_id or "(New Deployment)")

    configure_vertex_ai_user_credentials(account=config.oauth_user_account, project_id=config.project_id)

    env_file = os.path.join(repo_root, args.env_file) if not os.path.isabs(args.env_file) else args.env_file

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
        env_file=env_file if os.path.exists(env_file) else None,
        skip_agent_import_validation=True,
    )

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
