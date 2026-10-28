"""Configuration and input validation for the Gemini Enterprise Jira Federated Agent."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
import re
import subprocess
from dotenv import load_dotenv

load_dotenv()


def _clean_env_val(val: str | None) -> str:
    """Returns empty string if val is None or an unexpanded template placeholder like ${VAR}."""
    if not val:
        return ""
    trimmed = val.strip()
    if trimmed.startswith("${") and trimmed.endswith("}"):
        return ""
    return trimmed


def _get_gcloud_default_project() -> str:
    """Dynamically falls back to active gcloud config project without hardcoded strings."""
    try:
        proc = subprocess.run(
            ["gcloud", "config", "get-value", "project"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0:
            lines = [
                l.strip()
                for l in proc.stdout.splitlines()
                if l.strip() and not l.startswith("WARNING:")
            ]
            return lines[-1] if lines else ""
    except Exception:
        pass
    return ""


def _get_gcloud_project_number(project_id: str) -> str:
    """Dynamically retrieves the GCP project number for a given project ID."""
    clean_id = _clean_env_val(project_id)
    if not clean_id:
        return ""
    try:
        proc = subprocess.run(
            ["gcloud", "projects", "describe", clean_id, "--format=value(projectNumber)"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0:
            lines = [
                l.strip()
                for l in proc.stdout.splitlines()
                if l.strip() and not l.startswith("WARNING:")
            ]
            return lines[-1] if lines else ""
    except Exception:
        pass
    return ""


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
    """Configuration for the Gemini Enterprise Jira Federated Data Connector.

    All properties are loaded dynamically from environment variables (.env).
    """

    project_id: str = field(
        default_factory=lambda: (
            _clean_env_val(os.getenv("DISCOVERY_ENGINE_PROJECT_ID"))
            or _clean_env_val(os.getenv("GOOGLE_CLOUD_PROJECT"))
            or _clean_env_val(os.getenv("PROJECT_ID"))
            or _get_gcloud_default_project()
        )
    )
    project_number: str = field(
        default_factory=lambda: (
            _clean_env_val(os.getenv("DISCOVERY_ENGINE_PROJECT_NUMBER"))
            or _clean_env_val(os.getenv("PROJECT_NUMBER"))
        )
    )
    location: str = field(
        default_factory=lambda: (
            os.getenv("DISCOVERY_ENGINE_LOCATION")
            or os.getenv("GOOGLE_CLOUD_LOCATION")
            or "global"
        )
    )
    engine_id: str = field(
        default_factory=lambda: (
            os.getenv("DISCOVERY_ENGINE_ID")
            or "grocery-workshop-engine"
        )
    )
    collection_id: str = field(
        default_factory=lambda: os.getenv("JIRA_CONNECTOR_COLLECTION_ID", "")
    )
    jira_instance_uri: str = field(
        default_factory=lambda: os.getenv("JIRA_INSTANCE_URI", "")
    )
    model: str = field(
        default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    )
    oauth_user_account: str = field(
        default_factory=lambda: os.getenv("OAUTH_USER_ACCOUNT", "")
    )
    retrieval_mode: str = field(
        default_factory=lambda: os.getenv("JIRA_RETRIEVAL_MODE", "mcp").lower()
    )
    authorization_id: str = field(
        default_factory=lambda: os.getenv("JIRA_AUTHORIZATION_ID", "jira-oauth-provider")
    )
    jira_client_id: str = field(
        default_factory=lambda: os.getenv("JIRA_OAUTH_CLIENT_ID", "")
    )
    client_id_secret_name: str = field(
        default_factory=lambda: os.getenv("JIRA_OAUTH_CLIENT_SECRET_NAME", "jira_oauth_client")
    )
    client_secret_secret_name: str = field(
        default_factory=lambda: os.getenv("JIRA_OAUTH_SECRET_SECRET_NAME", "jira_oauth_secret")
    )

    @property
    def resolved_project_number(self) -> str:
        clean_num = _clean_env_val(self.project_number)
        if clean_num:
            return clean_num
        clean_id = _clean_env_val(self.project_id)
        if clean_id:
            return _get_gcloud_project_number(clean_id)
        return ""

    def validate(self) -> None:
        """Validates that all required environment variables are set in .env."""
        missing: list[str] = []
        if not self.project_id:
            missing.append("DISCOVERY_ENGINE_PROJECT_ID / GOOGLE_CLOUD_PROJECT")
        if not (self.project_number or self.resolved_project_number):
            missing.append("DISCOVERY_ENGINE_PROJECT_NUMBER")
        if not self.engine_id:
            missing.append("DISCOVERY_ENGINE_ID")
        if not self.collection_id:
            missing.append("JIRA_CONNECTOR_COLLECTION_ID")
        if not self.jira_instance_uri:
            missing.append("JIRA_INSTANCE_URI")
        if missing:
            raise ValueError(
                f"Missing required environment variables in .env: {', '.join(missing)}"
            )

    @property
    def base_api_url(self) -> str:
        if self.location == "global":
            return "https://discoveryengine.googleapis.com/v1alpha"
        return f"https://{self.location}-discoveryengine.googleapis.com/v1alpha"

    @property
    def effective_project_number(self) -> str:
        return self.resolved_project_number or self.project_number

    @property
    def data_connector_name(self) -> str:
        return (
            f"projects/{self.effective_project_number}/locations/{self.location}"
            f"/collections/{self.collection_id}/dataConnector"
        )

    @property
    def engine_name(self) -> str:
        return (
            f"projects/{self.effective_project_number}/locations/{self.location}"
            f"/collections/default_collection/engines/{self.engine_id}"
        )

    @property
    def widget_config_name(self) -> str:
        return f"{self.engine_name}/widgetConfigs/default_search_widget_config"

    @property
    def entity_data_stores(self) -> list[str]:
        prefix = (
            f"projects/{self.effective_project_number}/locations/{self.location}"
            f"/collections/default_collection/dataStores/{self.collection_id}"
        )
        return [f"{prefix}_{entity}" for entity in JIRA_ENTITIES]

    @property
    def stream_assist_url(self) -> str:
        return f"{self.base_api_url}/{self.engine_name}/assistants/default_assistant:streamAssist"

    @property
    def console_connector_url(self) -> str:
        return (
            f"https://console.cloud.google.com/gemini-enterprise/locations/{self.location}"
            f"/engines/{self.engine_id}/collections/{self.collection_id}"
            f"/connector/details?project={self.project_id}"
        )

    @property
    def authorization_name(self) -> str:
        return f"projects/{self.effective_project_number}/locations/{self.location}/authorizations/{self.authorization_id}"

    @property
    def client_id_secret_path(self) -> str:
        val = _clean_env_val(os.getenv("JIRA_CLIENT_ID_SECRET_PATH"))
        if val:
            return val
        return f"projects/{self.effective_project_number}/secrets/{self.client_id_secret_name}"

    @property
    def client_secret_secret_path(self) -> str:
        val = _clean_env_val(os.getenv("JIRA_CLIENT_SECRET_PATH"))
        if val:
            return val
        return f"projects/{self.effective_project_number}/secrets/{self.client_secret_secret_name}"

    @property
    def default_atlassian_auth_uri(self) -> str:
        client_id_param = f"&client_id={self.jira_client_id}" if self.jira_client_id else ""
        return (
            "https://auth.atlassian.com/authorize?audience=api.atlassian.com"
            f"{client_id_param}"
            "&scope=offline_access%20read%3Ajira-user%20read%3Ajira-work"
            "&redirect_uri=https%3A%2F%2Fvertexaisearch.cloud.google.com%2Foauth-redirect"
            "&response_type=code&prompt=consent"
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
