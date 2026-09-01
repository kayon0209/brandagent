# BrandFlow deployment and recovery runbook

## Scope

This runbook covers the Web, Agent API, Brand Tools MCP and PostgreSQL services. External platform publication is not implemented; preview is internal HTML only.

### Consumer upgrade compatibility window (plan task 15)

- The consumer workspace (`/app`) and the B-end BrandFlow workspace (`/brandflow`) run side by side during the compatibility window; both stay deployed.
- `/app` is the consumer-facing workspace and the default entry for C-end users; `/brandflow` remains reachable during the compatibility window. Any change to the DEFAULT landing route (`/`) or removal of legacy routes requires separate user authorization plus a rollback switch.
- Quota authority for C-end users is the FastAPI usage ledger (`usage_ledger`); the legacy Supabase quota endpoint is deprecated and not double-written.

## Required secrets

- `GLM_API_KEY`
- `BRAND_MCP_SERVICE_TOKEN`
- `POSTGRES_ADMIN_PASSWORD`
- `AGENT_DB_PASSWORD`
- `CHECKPOINT_DB_PASSWORD`
- Clerk publishable/secret keys and JWKS URL/issuer, plus either a JWT-template audience or comma-separated authorized frontend origins

Use a secret manager outside local development. Never put values in source, logs, screenshots or support tickets. Rotate the MCP token by updating Agent API and MCP together, then restart both services.

## Build exclusivity (Windows)

`corepack pnpm build` and `next dev` share `.next`. If a dev server is
running (or a previous build crashed), stale chunks make the next build
fail with `Cannot find module './NNNN.js'` or prerender
`TypeError: e[o] is not a function` — on ANY source tree, including a
clean checkout. Before building: stop the dev server, `rm -rf .next`
(the build cache only — never the user's `.next.bak.*` backups), then
run `corepack pnpm build` and expect exit 0 with no prerender errors.

## Start

```powershell
docker compose config
docker compose up --build -d
docker compose ps
```

### Web image build arguments

`docker build -f Dockerfile .` works without secrets: `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` defaults to a format-valid placeholder so static prerendering succeeds. Production must pass the real public key (it is safe to embed — it is a public identifier, not a secret):

```powershell
docker build -f Dockerfile `
  --build-arg NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_live_xxx `
  --build-arg NEXT_PUBLIC_BRANDFLOW_API_URL=https://your-web-host .
```

A placeholder-key image can build and start, but Clerk sign-in will fail until the real key is provided; treat it as a build/CI artifact only.

Readiness gates:

- MCP: `GET http://127.0.0.1:8100/health`
- Agent API: `GET http://127.0.0.1:8000/api/v1/readiness`
- Web: `GET http://127.0.0.1:3000/app` (consumer entry; `/brandflow` stays up during the compatibility window)

Agent readiness fails closed when PostgreSQL checkpoint isolation, GLM configuration, MCP discovery or internal authentication is unavailable.

## Database rules

- `brandflow_app` owns business reads/writes.
- `brandflow_checkpoint` uses the separate `brandflow_checkpoint` schema and must not equal the business role.
- Apply numbered migrations to a fresh disposable database before any shared environment. The consumer gate (`RUN_BRANDFLOW_DB_TESTS=true pnpm test:db:consumer`) applies 001-005 and asserts the 004 RLS policies plus the 005 FORCE hardening (owner bypass closed) on a disposable container.
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

## Authenticated E2E identity (real-journey suite)

The real consumer journey (`tests/e2e/consumer-real-journey.spec.ts`) runs
against the real stack and never mocks core consumer APIs. It requires:

- `BRANDFLOW_E2E_STORAGE_STATE` — a Playwright storage-state JSON for a
  disposable Clerk TEST user (never a production identity). Export it by
  signing the test user in once against a disposable environment and
  saving the authenticated browser state.
- `BRANDFLOW_E2E_API_TOKEN` (optional) — a pre-minted agent-api bearer
  token for direct API assertions.
- The backend MUST point at a disposable PostgreSQL database; the suite
  creates real projects/materials and must never run against shared data.

When these are absent the real suite reports itself as "ENVIRONMENT NOT
PREPARED — not executed". A skipped real suite is never a pass; the
`[mock]` UI specs are wiring coverage only and cannot substitute.

### Clerk configuration sanity (no secrets involved)

`/` and `/app*` redirect-loop or 404 symptoms almost always mean the
Clerk keys in the running environment do not come from the SAME Clerk
instance:

- `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` and `CLERK_SECRET_KEY` must be
  issued by the same Clerk application. The publishable key embeds the
  instance prefix (`pk_test_<instance>...` / `pk_live_<instance>...`).
- The token issuer (`CLERK_JWT_ISSUER` / JWKS URL, e.g.
  `https://<instance>.clerk.accounts.dev` or your custom domain) must
  match that same instance prefix. A secret from instance A with a
  publishable key from instance B fails exactly as a redirect loop.
- Verify WITHOUT printing values: decode the publishable key's middle
  segment and compare the instance prefix with the issuer host's
  leftmost label. They must be equal.
- Session tokens must carry the expected `azp` (authorized party) or be
  accepted by the azp-less default path (see
  `services/agent-api/tests/test_clerk_security.py`).
