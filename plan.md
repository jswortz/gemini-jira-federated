# Implementation Plan & Architecture: `gemini-jira-federated` ADK RAG Agent

## 1. Objective
Build a clean, tested Google ADK repository in `gemini-jira-federated` that demonstrates how to build a grounded RAG agent over the Gemini Enterprise **Federated Jira Data Connector**:
- **Target Engine**: `projects/679926387543/locations/global/collections/default_collection/engines/grocery-workshop-engine`
- **Target Agent ID**: `projects/679926387543/locations/global/collections/default_collection/engines/grocery-workshop-engine/assistants/default_assistant/agents/16003540595574963813`
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
    subgraph Client["Client Tier"]
        User["End User (admin@jwortz.altostrat.com)"]
        UI["Gemini Enterprise Chat UI / ADK Web Dev UI"]
        User -->|"1. User Query"| UI
    end

    subgraph AgentPlatform["Gemini Enterprise Agent Platform & Vertex AI"]
        Agent["Jira Federated Agent\n(ADK LlmAgent / Reasoning Engine 1626276928405110784)"]
        UI -->|"2. StreamAssist"| Agent
        Tools["Jira Search & MCP Tools"]
        Agent -->|"3. Call Tool"| Tools
    end

    subgraph GoogleIAM["Google Cloud IAM Auth Manager & Discovery Engine"]
        AuthManager["Discovery Engine 3LO Auth Service\n(projects/.../authorizations/jira-oauth-provider)"]
        Tools -->|"4. Check User Token (userIamPrincipal)"| AuthManager
        
        SMClient["Secret Manager: jira_oauth_client"]
        SMSecret["Secret Manager: jira_oauth_secret"]
        AuthManager -->|"5. Fetch App Secrets"| SMClient
        AuthManager -->|"5. Fetch App Secrets"| SMSecret
    end

    subgraph AtlassianCloud["Atlassian Jira Cloud"]
        AuthEndpoint["Atlassian 3LO Authorize Endpoint\n(auth.atlassian.com)"]
        JiraAPI["Atlassian Jira REST API\n(api.atlassian.com/ex/jira/...)"]
        
        User -.->|"6a. Consent & Authorize"| AuthEndpoint
        AuthEndpoint -.->|"6b. Callback with Code"| AuthManager
        AuthManager -->|"7. Proxy Request with User Token"| JiraAPI
    end

    JiraAPI -->|"8. Filtered Issues (User A ACLs)"| Tools
    Tools -->|"9. Grounded Context"| Agent
    Agent -->|"10. Synthesized Answer with Citations"| UI
```

---

### Sequence Flow: End-User 3LO Delegation

```mermaid
sequenceDiagram
    autonumber
    actor User as End User (Browser)
    participant Chat as Gemini Enterprise Chat
    participant Agent as Jira Federated Agent
    participant AuthMgr as IAM Auth Manager / DE Vault
    participant SM as Google Cloud Secret Manager
    participant Atlassian as Atlassian Cloud (Jira)

    User->>Chat: "What Jira tickets are currently open?"
    Chat->>Agent: StreamAssist (agent: 16003540595574963813)
    Agent->>AuthMgr: Check user authorization (userIamPrincipal)
    
    alt User Has Not Consented Yet (First Time)
        AuthMgr-->>Agent: OAuth required (acquireUserAuthorization)
        Agent-->>Chat: Return authorization URI
        Chat-->>User: Display "Sign in with Jira" authorization button
        User->>Atlassian: Navigate to Atlassian 3LO Consent URL
        User->>Atlassian: Grant read access (offline_access, read:jira-user, read:jira-work)
        Atlassian-->>User: Redirect to callback URL with auth code
        User->>AuthMgr: Callback (vertexaisearch.cloud.google.com/static/oauth/oauth.html?code=...)
        AuthMgr->>SM: Read client_id & client_secret (jira_oauth_client / jira_oauth_secret)
        SM-->>AuthMgr: Return Atlassian OAuth app credentials
        AuthMgr->>Atlassian: Exchange code for refresh & access tokens (auth.atlassian.com/oauth/token)
        Atlassian-->>AuthMgr: Return access_token & refresh_token
        AuthMgr->>AuthMgr: Encrypt & store tokens keyed by userIamPrincipal in 3LO Vault
    end

    Agent->>AuthMgr: Execute query with user identity
    AuthMgr->>Atlassian: Forward request with User A's Bearer token (:invokeConnectorMcp / REST)
    Atlassian-->>AuthMgr: Return Jira issues matching User A's permissions
    AuthMgr-->>Agent: Raw normalized issue payload
    Agent-->>Chat: Grounded response with issue keys, summaries, and citations
    Chat-->>User: "Here are the open tickets you have access to..."
```

---

## 3. Environment & Execution

Activate the local virtual environment:
```bash
source /usr/local/google/home/jwortz/gemini-jira-federated/.venv/bin/activate
```
Or execute commands with `uv run`:
```bash
uv run python scripts/setup_jira_auth_provider.py
uv run pytest -v
```

## 4. Verification & Testing
- Unit tests: `tests/test_config_and_auth.py`, `tests/test_jira_connector_client.py`, `tests/test_setup_jira_auth_provider.py`.
- Live integration tests: `tests/test_integration_live.py`.
- Atlassian 3LO parameter validation: RFC 6749 compliance (`response_type=code`, `redirect_uri`, `prompt=consent`).
