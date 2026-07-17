# BrandFlow Agent API

Directory contract:

```text
services/agent-api/
├── pyproject.toml
├── src/agent_api/
│   ├── api/          FastAPI routers and public response models
│   ├── domain/       Stable domain and AgentState models
│   ├── providers/    LLMProvider interface and explicit providers
│   ├── repositories/ PostgreSQL business persistence
│   └── workflow/     LangGraph nodes, routing and checkpoint setup
└── tests/            Unit, workflow, API and recovery tests
```

Rules:

- No secrets, complete prompts or hidden reasoning in state or logs.
- External model calls are mocked in automated tests.
- Zhipu `glm-4.7` was explicitly verified on 2026-07-14; automated suites still keep the live-provider test opt-in.
- The service does not publish content or call MCP until the corresponding milestone.
- PostgreSQL is authoritative for tasks, versions and human decisions; checkpoints are resumable state only.

## Local startup

The production composition fails closed unless all required settings are present:

- `AGENT_DATABASE_URL`: business role for BrandFlow domain tables.
- `AGENT_CHECKPOINT_DATABASE_URL`: separate checkpoint role and schema; it must not reuse the business connection string.
- `GLM_API_KEY` and `GLM_MODEL` (defaults to `glm-4.7`).
- `CLERK_JWKS_URL` and `CLERK_ISSUER`.
- Either `CLERK_AUDIENCE` for a dedicated Clerk JWT template or `CLERK_AUTHORIZED_PARTIES` for default session tokens. Production startup fails when both are empty.

Verification evidence: the opt-in provider test completed successfully against `glm-4.7` with provider-reported token usage and without printing the API key, prompt, or response content. Run it only in a controlled environment with `RUN_ZHIPU_INTEGRATION=true`.

Run from the repository root:

```powershell
$env:PYTHONPATH="services/agent-api/src"
.\services\agent-api\.venv\Scripts\python.exe -m agent_api.api.server
```

## Checkpoint isolation

Use a dedicated PostgreSQL login whose `search_path` points to a checkpoint-only schema such as `brandflow_checkpoint`. The role needs connect, schema usage/create, and DML privileges only inside that schema. It must have no grants on BrandFlow business tables. The business role must have no grants on the checkpoint schema. `AsyncPostgresSaver.setup()` creates and upgrades its own tables through this restricted connection.

Checkpoint thread IDs and namespaces include the workspace ID, but that application-level scoping is not a substitute for the separate database role. Never expose the checkpoint database connection to the browser or to the MCP service.
