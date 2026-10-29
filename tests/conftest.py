"""Pytest fixtures and environment setup for hermetic unit testing."""

import os

# Ensure required environment variables have safe test defaults if unset or empty
_TEST_DEFAULTS = {
    "PROJECT_ID": "test-project-id",
    "PROJECT_NUMBER": "123456789012",
    "DISCOVERY_ENGINE_PROJECT_ID": "test-project-id",
    "DISCOVERY_ENGINE_PROJECT_NUMBER": "123456789012",
    "GOOGLE_CLOUD_PROJECT": "test-project-id",
    "GOOGLE_CLOUD_LOCATION": "us-central1",
    "DISCOVERY_ENGINE_LOCATION": "global",
    "DISCOVERY_ENGINE_ID": "test-engine",
    "JIRA_CONNECTOR_COLLECTION_ID": "jira-federated_test",
    "JIRA_INSTANCE_URI": "https://test-jira.atlassian.net",
    "OAUTH_USER_ACCOUNT": "test-user@example.com",
    "JIRA_OAUTH_CLIENT_ID": "test-client-id",
    "JIRA_OAUTH_CLIENT_SECRET_NAME": "jira_oauth_client",
    "JIRA_OAUTH_SECRET_SECRET_NAME": "jira_oauth_secret",
    "JIRA_CLIENT_ID_SECRET_PATH": "projects/123456789012/secrets/jira_oauth_client",
    "JIRA_CLIENT_SECRET_PATH": "projects/123456789012/secrets/jira_oauth_secret",
}

for key, val in _TEST_DEFAULTS.items():
    current_val = os.environ.get(key, "")
    if not current_val or (current_val.startswith("${") and current_val.endswith("}")):
        os.environ[key] = val
