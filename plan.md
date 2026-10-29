# Implementation Plan & Architecture: `gemini-jira-federated` ADK RAG Agent

## 1. Objective
Build a clean, tested Google ADK repository in `gemini-jira-federated` that demonstrates how to build a grounded RAG agent over the Gemini Enterprise **Federated Jira Data Connector**:
- **Target Engine**: `projects/${PROJECT_NUMBER}/locations/global/collections/default_collection/engines/grocery-workshop-engine`
- **Target Agent ID**: `projects/${PROJECT_NUMBER}/locations/global/collections/default_collection/engines/grocery-workshop-engine/assistants/default_assistant/agents/${AGENT_ID}`
- **Target Location**: `global` (Discovery Engine) / `us-central1` (Vertex AI Gemini)
- **Delegated Auth Model**: Pattern 2 (Secret Manager + Discovery Engine Authorization Provider + End-User 3LO)

## 2. Technical Architecture & Google Cloud IAM Auth Manager

For detailed Google Cloud conceptual standards on agent authentication brokering, see:
- [Google Cloud IAM Auth Manager Overview](https://docs.cloud.google.com/iam/docs/auth-manager-overview)
- [Agent Identity 3-Legged OAuth with Auth Manager](https://cloud.google.com/iam/docs/agent-identity-auth-manager-oauth3)
- [Manage Agent Identity Auth Providers](https://cloud.google.com/iam/docs/agent-identity-manage-auth-providers)

### System Architecture Diagram

```mermaid
flowchart TD
    subgraph Client["Client Interface"]
        User["End User (user@your-domain.com)"]
        ChatUI["Gemini Enterprise Chat UI / ADK Web Dev UI"]
        User -->|"1. User Query ('What issues are open?')"| ChatUI
    end

    subgraph AgentPlatform["Vertex AI Agent Engine & ADK Runtime"]
        Agent["Jira Federated Agent\n(ADK LlmAgent / Reasoning Engine)\nAgent ID: ${AGENT_ID}"]
        ChatUI -->|"2. StreamAssist / Query"| Agent
        AgentClient["JiraFederatedConnectorClient\n(Google Bearer Token)"]
        Agent -->|"3. Execute Tool"| AgentClient
    end

    subgraph GoogleIAM["Google Cloud IAM & Discovery Engine Auth Manager"]
        DE["Discovery Engine Gateway\n(jira-federated_...)"]
        AgentClient -->|"4. POST :invokeConnectorMcp\n(Google Bearer Token + tool name + args)"| DE
        
        AuthVault["Auth Manager 3LO Token Vault\n(userIamPrincipal: user@your-domain.com)"]
        DE -->|"5. Resolve Caller & Query 3LO Vault"| AuthVault
        
        AuthProvider["Authorization Provider\n(jira-oauth-provider)"]
        AuthVault -.->|"Configured via"| AuthProvider
        
        SMClient["Secret Manager: jira_oauth_client"]
        SMSecret["Secret Manager: jira_oauth_secret"]
        AuthProvider -->|"Read App ID"| SMClient
        AuthProvider -->|"Read App Secret"| SMSecret
    end

    subgraph AtlassianCloud["Atlassian Jira Cloud"]
        AtlassianAuth["Atlassian OAuth 2.0 (3LO) Endpoint\n(auth.atlassian.com)"]
        AtlassianJira["Atlassian Jira REST & MCP Services\n(https://api.atlassian.com/ex/jira/...)"]
        
        User -.->|"One-time 3LO Consent"| AtlassianAuth
        AtlassianAuth -.->|"Exchange Code for Refresh Token"| DE
        DE -->|"6. Proxy Outbound Action with User's 3LO Token"| AtlassianJira
        AtlassianJira -->|"7. Return Filtered Data (User ACLs)"| DE
    end

    DE -->|"8. Normalized MCP Content Envelope"| AgentClient
    AgentClient -->|"9. Structured Python Dict/List"| Agent
    Agent -->|"10. Synthesized Answer with Citations"| ChatUI
    ChatUI -->|"11. Grounded Markdown Table"| User
```

---

### Sequence Flow: Direct Federated MCP Invocation (`invokeConnectorMcp`)

```mermaid
sequenceDiagram
    autonumber
    actor User as End User (Browser)
    participant Chat as Gemini Enterprise / ADK Web
    participant Agent as ADK LlmAgent
    participant Client as JiraFederatedConnectorClient
    participant DE as Discovery Engine (:invokeConnectorMcp)
    participant Vault as IAM Auth Manager Vault
    participant Jira as Atlassian Jira Cloud

    User->>Chat: "Search for open tickets in project GEAP"
    Chat->>Agent: Execute agent turn
    Agent->>Client: search_jira_issues(project_key='GEAP')
    Client->>DE: POST :invokeConnectorMcp<br/>{"method": "tools/call", "params": {"name": "search_issues", "arguments": {"query": "project = 'GEAP'..."}}}<br/>Header: Authorization: Bearer <Google_Access_Token>
    
    DE->>Vault: Resolve caller identity (userIamPrincipal) & fetch Jira 3LO token
    alt 3LO Token Valid & Present in Vault
        Vault-->>DE: Return active Atlassian 3LO Bearer token
    else Token Expired or Not Authorized
        DE-->>Client: Error / auth_required (authorizationUri)
        Client-->>User: Present 3LO authorization link
    end

    DE->>Jira: Forward action with user's Atlassian Bearer token<br/>POST /rest/api/3/search/jql
    Jira-->>DE: Return issues matching user permissions (JSON)
    DE-->>Client: {"result": {"isError": false, "content": [{"type": "text", "text": "..."}]}}
    Client-->>Agent: {"status": "success", "issues": [...]}
    Agent-->>Chat: Grounded response with issue table and links
    Chat-->>User: Displays issues with key, title, status, priority, and links
```

---

## 3. Required Google Cloud APIs & IAM Roles

### Required Google Cloud APIs
Enable all required APIs with:
```bash
gcloud services enable \
  discoveryengine.googleapis.com \
  aiplatform.googleapis.com \
  secretmanager.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  serviceusage.googleapis.com \
  cloudresourcemanager.googleapis.com \
  --project="${PROJECT_ID}"
```

| API Service Name | Service Endpoint | Purpose |
| :--- | :--- | :--- |
| **Discovery Engine API** | `discoveryengine.googleapis.com` | Gemini Enterprise apps, federated Jira connector (`jira-federated_...`), Auth Manager authorizations, and `:invokeConnectorMcp`. |
| **Vertex AI API** | `aiplatform.googleapis.com` | Vertex AI Gemini models, Reasoning Engines, and Agent Engine runtime. |
| **Secret Manager API** | `secretmanager.googleapis.com` | Storage of Atlassian OAuth Client ID and Secret (`jira_oauth_client`, `jira_oauth_secret`). |
| **IAM API & Credentials API** | `iam.googleapis.com`, `iamcredentials.googleapis.com` | Service account token exchange, caller identity validation, and IAM permissions. |
| **Service Usage & Resource Manager** | `serviceusage.googleapis.com`, `cloudresourcemanager.googleapis.com` | Quotas, service enablement, and project-level policy control. |

### Required IAM Roles

| Identity | Role | Purpose |
| :--- | :--- | :--- |
| **Calling User** (`${OAUTH_USER_ACCOUNT}`) | `roles/discoveryengine.admin` | Access Gemini Enterprise search apps and execute data connector actions (`discoveryengine.dataConnectors.executeAction`). |
| | `roles/aiplatform.user` | Query Vertex AI Reasoning Engine agent. |
| | `roles/secretmanager.viewer` | Read secret metadata. |
| **Discovery Engine SA** (`service-${PROJECT_NUMBER}@gcp-sa-discoveryengine.iam.gserviceaccount.com`) | `roles/secretmanager.secretAccessor` | Access `jira_oauth_client` and `jira_oauth_secret` during 3LO exchange. |
| **Reasoning Engine / Compute SA** (`${PROJECT_NUMBER}-compute@developer.gserviceaccount.com`) | `roles/discoveryengine.admin` | Execute `:invokeConnectorMcp` against the federated collection. |
| | `roles/secretmanager.secretAccessor` | Read app credentials if executing headless scripts. |

---

## 4. Environment & Execution

Activate the local virtual environment:
```bash
source .venv/bin/activate
```
Or execute commands with `uv run`:
```bash
uv run python scripts/setup_jira_auth_provider.py
uv run pytest -v
```

## 5. Option A: Direct Federated MCP Tool (`dataConnector:invokeConnectorMcp`)

### Architecture: Zero Direct Atlassian Credentials in Agent
Instead of the agent holding or negotiating Jira credentials directly, the Discovery Engine Federated Connector natively exposes Model Context Protocol (MCP) tool endpoints. The agent executes tools via the unified Google Cloud Discovery Engine RPC:

```
POST https://discoveryengine.googleapis.com/v1alpha/projects/{project}/locations/{location}/collections/{collection}/dataConnector:invokeConnectorMcp
```

```mermaid
flowchart LR
    Agent["ADK LlmAgent\n(Reasoning Engine / adk web)"]
    DE["Discovery Engine\n(jira-federated_...)"]
    Vault["Auth Manager\nToken Vault (Per-User 3LO)"]
    Jira["Atlassian Jira Cloud\n(your-instance.atlassian.net)"]

    Agent -->|"1. POST :invokeConnectorMcp\n(Google Bearer Token + tool name + args)"| DE
    DE -->|"2. Resolve User & Query Vault"| Vault
    Vault -->|"3. Retrieve User's Jira 3LO Token"| DE
    DE -->|"4. Execute Jira Cloud Action"| Jira
    Jira -->|"5. Return JSON Result"| DE
    DE -->|"6. Return MCP Content Envelope"| Agent
```

### Supported MCP Actions in `jira-federated_1782320633397`
The federated connector provides 32 built-in MCP tools, including:
- **`search_issues`**: Searches issues using bounded or unbounded JQL queries (`{"query": "...", "maxResults": 20}`).
- **`get_issue`**: Retrieves full issue fields, status, priority, and attachments (`{"Id": "GEAP-3"}`).
- **`list_projects` / `search_projects`**: Lists or searches Jira projects accessible to the user.
- **`create_comment`**: Posts an update or comment to a ticket (`{"IssueKey": "...", "Body": "..."}`).
- **`update_comment`**: Updates an existing comment (`{"IssueKey": "...", "Id": ..., "Body": "..."}`).
- **`list_comments`**: Lists all comments on a ticket (`{"IssueKey": "..."}`).
- **`create_issue`**: Creates a new ticket (`{"ProjectKey": "...", "Summary": "...", "IssueTypeId": "10001", "Description": "..."}`).
- **`upload_attachment`**: Attaches a file to a ticket (`{"IssueKey": "...", "InputFileName": "..."}`).
- **`list_tools`**: Catalog inspection via `method: "tools/list"`.

---

## 6. Verification & Testing
- Unit tests: `tests/test_config_and_auth.py`, `tests/test_jira_connector_client.py`, `tests/test_setup_jira_auth_provider.py`.
- Live integration tests: `tests/test_integration_live.py`.
- Atlassian 3LO parameter validation: RFC 6749 compliance (`response_type=code`, `redirect_uri`, `prompt=consent`).
