# BrandFlow deployment and recovery runbook

## Scope

This runbook covers the Web, Agent API, Brand Tools MCP and PostgreSQL services. External platform publication is not implemented; preview is internal HTML only.

## Required secrets

- `GLM_API_KEY`
- `BRAND_MCP_SERVICE_TOKEN`
- `POSTGRES_ADMIN_PASSWORD`
- `AGENT_DB_PASSWORD`
- `CHECKPOINT_DB_PASSWORD`
- Clerk publishable/secret keys and JWKS URL/issuer, plus either a JWT-template audience or comma-separated authorized frontend origins

Use a secret manager outside local development. Never put values in source, logs, screenshots or support tickets. Rotate the MCP token by updating Agent API and MCP together, then restart both services.

## Start

```powershell
docker compose config
docker compose up --build -d
docker compose ps
```

Readiness gates:

- MCP: `GET http://127.0.0.1:8100/health`
- Agent API: `GET http://127.0.0.1:8000/api/v1/readiness`
- Web: `GET http://127.0.0.1:3000/brandflow`

Agent readiness fails closed when PostgreSQL checkpoint isolation, GLM configuration, MCP discovery or internal authentication is unavailable.

## Database rules

- `brandflow_app` owns business reads/writes.
- `brandflow_checkpoint` uses the separate `brandflow_checkpoint` schema and must not equal the business role.
- Apply numbered migrations to a fresh disposable database before any shared environment.
- Content versions, decisions, lineage and audit events are append-only. Never repair them with direct updates.

## Recovery

### MCP unavailable

1. Check MCP health and PostgreSQL connectivity.
2. Confirm `BRAND_MCP_SERVICE_TOKEN` matches without printing it.
3. Restart MCP, then Agent API so startup discovery runs again.
4. Use the task retry action. The UI shows whether saved work is safe and resumes from the last fenced checkpoint.

### Model unavailable or rate limited

1. Preserve the failed task; do not create a duplicate.
2. Verify provider status and quota outside application logs.
3. Retry only when the task error is marked recoverable.
4. Provider usage/cost remains null when the provider did not report it.

### Service restart

1. Restore PostgreSQL first, then MCP, Agent API and Web.
2. Confirm Agent readiness.
3. Open the existing task and retry from its checkpoint. Do not replay approval/export calls with a new payload under an old idempotency key.

### Export rejected

Export is server-gated. Confirm all required master/channel/final decisions are satisfied, no critical issue or unsupported lineage remains, the decision actor matches the caller, and the package hash still matches the approved version set.

## Verification

```powershell
.\services\agent-api\.venv\Scripts\python.exe -m pytest -p no:cacheprovider services\agent-api\tests services\brand-tools-mcp\tests
node node_modules\next\dist\bin\next lint
node node_modules\next\dist\bin\next build
node node_modules\@playwright\test\cli.js test --list
```

Authenticated Playwright execution requires `BRANDFLOW_E2E_STORAGE_STATE`; live API gate coverage additionally requires `BRANDFLOW_E2E_API_TOKEN` and a disposable database. Skipped tests must not be reported as executed capabilities.
