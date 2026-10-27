"""Configuration and input validation for the Gemini Enterprise Jira Federated Agent."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
import re
from dotenv import load_dotenv

load_dotenv()

JIRA_ENTITIES: tuple[str, ...] = (
    "project",
    "attachment",
    "comment",
    "issue",
    "bug",
    "epic",
    "story",
    "task",
    "worklog",
    "board",
)

_ISSUE_KEY_RE = re.compile(r"^(?:[A-Z][A-Z0-9_]{0,19}-\d+|\d+)$")
_PROJECT_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,19}$")
_SAFE_STATUS_RE = re.compile(r"^[A-Za-z0-9 _\-/]{1,64}$")
_ORDER_BY_RE = re.compile(r"\s+ORDER\s+BY\s+.*$", re.IGNORECASE)


@dataclass(frozen=True)
class ConnectorConfig:
    """Configuration for the Gemini Enterprise Jira Federated Data Connector."""

    project_id: str = field(
        default_factory=lambda: os.getenv(
            "DISCOVERY_ENGINE_PROJECT_ID", "wortz-project-352116"
        )
    )
    project_number: str = field(
        default_factory=lambda: os.getenv(
            "DISCOVERY_ENGINE_PROJECT_NUMBER", "679926387543"
        )
    )
    location: str = field(
        default_factory=lambda: os.getenv("DISCOVERY_ENGINE_LOCATION", "global")
    )
    engine_id: str = field(
        default_factory=lambda: os.getenv(
            "DISCOVERY_ENGINE_ID", "ge-jira-vpcsc-app"
        )
    )
    collection_id: str = field(
        default_factory=lambda: os.getenv(
            "JIRA_CONNECTOR_COLLECTION_ID", "jira-federated_1782320633397"
        )
    )
    jira_instance_uri: str = field(
        default_factory=lambda: os.getenv(
            "JIRA_INSTANCE_URI", "https://jwortz.atlassian.net"
        )
    )
    model: str = field(
        default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    )
    oauth_user_account: str = field(
        default_factory=lambda: os.getenv(
            "OAUTH_USER_ACCOUNT", "admin@jwortz.altostrat.com"
        )
    )

    @property
    def base_api_url(self) -> str:
        if self.location == "global":
            return "https://discoveryengine.googleapis.com/v1alpha"
        return f"https://{self.location}-discoveryengine.googleapis.com/v1alpha"

    @property
    def data_connector_name(self) -> str:
        return (
            f"projects/{self.project_number}/locations/{self.location}"
            f"/collections/{self.collection_id}/dataConnector"
        )

    @property
    def engine_name(self) -> str:
        return (
            f"projects/{self.project_number}/locations/{self.location}"
            f"/collections/default_collection/engines/{self.engine_id}"
        )

    @property
    def widget_config_name(self) -> str:
        return f"{self.engine_name}/widgetConfigs/default_search_widget_config"

    @property
    def entity_data_stores(self) -> list[str]:
        prefix = (
            f"projects/{self.project_number}/locations/{self.location}"
            f"/collections/default_collection/dataStores/{self.collection_id}"
        )
        return [f"{prefix}_{entity}" for entity in JIRA_ENTITIES]

    @property
    def console_connector_url(self) -> str:
        return (
            f"https://console.cloud.google.com/gemini-enterprise/locations/{self.location}"
            f"/engines/{self.engine_id}/collections/{self.collection_id}"
            f"/connector/details?project={self.project_id}"
        )


def validate_issue_key(issue_key: str) -> str:
    """Validates and normalizes a Jira issue key (e.g. 'CCS-50') or numeric ID."""
    cleaned = (issue_key or "").strip().upper()
    if not _ISSUE_KEY_RE.match(cleaned):
        raise ValueError(
            f"Invalid Jira issue key '{issue_key}'. Expected format like 'CCS-50' or 'GEAP-3'."
        )
    return cleaned


def validate_project_key(project_key: str) -> str:
    """Validates and normalizes a Jira project key (e.g. 'CCS' or 'GEAP')."""
    cleaned = (project_key or "").strip().upper()
    if not _PROJECT_KEY_RE.match(cleaned):
        raise ValueError(
            f"Invalid Jira project key '{project_key}'. Expected uppercase key like 'CCS'."
        )
    return cleaned


def _escape_jql_string(value: str) -> str:
    """Escapes backslashes and double quotes for safe inclusion inside JQL quotes."""
    sanitized = value.replace("\\", "\\\\").replace('"', '\\"')
    sanitized = sanitized.replace("\r", " ").replace("\n", " ").strip()
    return sanitized


def build_safe_jql(
    query: str = "",
    jql: str = "",
    project_key: str = "",
    status: str = "",
    issue_type: str = "",
) -> str:
    """Builds a validated JQL filter string without ORDER BY (handled via sort_by)."""
    if jql and jql.strip():
        cleaned_jql = _ORDER_BY_RE.sub("", jql.strip()).strip()
        return cleaned_jql

    clauses: list[str] = []
    if project_key and project_key.strip():
        valid_proj = validate_project_key(project_key)
        clauses.append(f'project = "{valid_proj}"')

    if status and status.strip():
        clean_status = status.strip()
        if not _SAFE_STATUS_RE.match(clean_status):
            raise ValueError(f"Invalid Jira status filter: '{status}'")
        clauses.append(f'status = "{_escape_jql_string(clean_status)}"')

    if issue_type and issue_type.strip():
        clean_type = issue_type.strip()
        if not _SAFE_STATUS_RE.match(clean_type):
            raise ValueError(f"Invalid Jira issue_type filter: '{issue_type}'")
        clauses.append(f'issuetype = "{_escape_jql_string(clean_type)}"')

    if query and query.strip():
        clean_query = query.strip()
        if _ISSUE_KEY_RE.match(clean_query.upper()) and "-" in clean_query:
            clauses.append(f'key = "{clean_query.upper()}"')
        else:
            clauses.append(f'text ~ "{_escape_jql_string(clean_query)}"')

    return " AND ".join(clauses)
