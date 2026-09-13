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
- Apply numbered migrations to a fresh disposable database before any shared environment.
- 010 adds the ONLY two cross-workspace entry points the business role
  may use: `deep_research_list_orphaned_runs()` and
  `deep_research_fail_orphaned_run(uuid)` — both `SECURITY DEFINER`,
  owned by the table owner, fixed `search_path = pg_catalog, public`,
  granted to `brandflow_app` only and revoked from every other role.
  They exist solely for startup orphan recovery of deep-research runs;
  neither returns question/synthesis/candidate content. Never widen
  them into a general cross-workspace read/write interface, and never
  work around them by disabling RLS, granting `BYPASSRLS`, elevating
  the business connection, or setting a global `app.workspace_id`.
- 011 restricts the legacy `increment_token_used(text, integer)`
  `SECURITY DEFINER` RPC to Supabase's trusted `service_role` (when that
  role exists), pins its `search_path = pg_catalog, public`, and revokes
  execution from `PUBLIC`, `brandflow_app`, and `brandflow_checkpoint`.
  Do not grant this cross-user quota mutation RPC to a BrandFlow runtime role.

### Applying missing migrations to an EXISTING stack (005–011)

`docker-entrypoint-initdb.d` only runs when the persistent volume is
FIRST initialized. For an already-running stack, apply the migration
explicitly. Schedule a maintenance window first: 008 replaces the existing
`source_documents.document_type` CHECK constraint, so it takes an exclusive
table lock even though it neither deletes rows nor columns. Do not apply any
migration merely to re-run a test.

After the Compose definition containing the 005–011 mounts has been rolled
out, apply only the migration files absent from that database, in order:

```powershell
foreach ($migration in @(
  '06-consumer-rls-force.sql',
  '07-style-reports.sql',
  '08-style-report-enrichment.sql',
  '09-consumer-material-kinds.sql',
  '10-deep-research.sql',
  '11-orphan-recovery.sql',
  '12-harden-token-rpc.sql'
)) {
  docker compose exec postgres psql -U postgres -d brandflow `
    -v ON_ERROR_STOP=1 `
    -f "/docker-entrypoint-initdb.d/$migration"
}
```

Verify after applying (owner bypass must read `closed`):

```powershell
docker compose exec postgres psql -U postgres -d brandflow -t -c `
  "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname='consumer_projects';"
```

Never delete the data volume to "re-run" migrations; upgrade in place. The consumer gate (`RUN_BRANDFLOW_DB_TESTS=true pnpm test:db:consumer`) applies 001–011 on a disposable container, verifies the 004 workspace policies and 005 FORCE hardening (including owner bypass closed), verifies 006 `style_reports` RLS, proves 007/008 schema contracts, and proves the isolated checkpoint role cannot call the 011-hardened token RPC. The agent-api RLS gate (`RUN_AGENT_DB_TESTS=true`, see Verification below) additionally proves 009 deep-research RLS and the 010 orphan-recovery entries under the plain `brandflow_app` role.
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
2. Confirm Agent readiness. At startup the Agent API sweeps
   restart-orphaned deep-research runs through the 010 recovery
   entries: each abandoned `planned`/`running` run is refunded (ledger
   reservation released) and marked failed with an honest message; a
   run whose refund fails stays non-terminal so the next restart
   retries it. Terminal runs and settled usage are never rewritten.
3. Open the existing task and retry from its checkpoint. Do not replay approval/export calls with a new payload under an old idempotency key.

### Export rejected

Export is server-gated. Confirm all required master/channel/final decisions are satisfied, no critical issue or unsupported lineage remains, the decision actor matches the caller, and the package hash still matches the approved version set.

## Verification

> **pytest 必须分服务目录运行**（v4 P2-2 修正）。两个服务各有独立的
> `pyproject.toml` 与 `pythonpath`；从仓库根目录一次性传两个 `tests` 目录
> 会因 `pythonpath` 冲突报 `ModuleNotFoundError: tests.test_editorial_assist`。
> 正确跑法：分别进入两个目录跑。

```powershell
# agent-api
cd services/agent-api
..\agent-api\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests
cd ..\..

# brand-tools-mcp（复用 agent-api 的 venv 解释器）
cd services\brand-tools-mcp
..\agent-api\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests
cd ..\..

# 真实 PostgreSQL 回归（可选，需 disposable PG + RUN_AGENT_DB_TESTS=true）
$env:RUN_AGENT_DB_TESTS="true"
$env:AGENT_TEST_DATABASE_URL="postgresql://postgres@127.0.0.1:54998/postgres"
cd services/agent-api
..\agent-api\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests
cd ..\..
```

前端：

```powershell
node node_modules\next\dist\bin\next lint
node node_modules\next\dist\bin\next build
node node_modules\@playwright\test\cli.js test --list
```

Authenticated Playwright execution requires `BRANDFLOW_E2E_STORAGE_STATE`; live API gate coverage additionally requires `BRANDFLOW_E2E_API_TOKEN` and a disposable database. Skipped tests must not be reported as executed capabilities.

## Dev backend reload rule (v4 P1-3)

`scripts/start-real-agent-api.mjs` 用 `uvicorn.Server` + `SelectorEventLoop`，
**故意不开 `--reload`**：在 Windows + SelectorEventLoop 下 reload 再加载器
不稳，反而会让"改了没生效"更难排查。因此定为一条硬规则：

> **改了 `services/agent-api/src/agent_api/application/` 或 `repositories/`
> 下的任何文件后，必须重启 18000**：
> `node scripts/start-real-agent-api.mjs`（先杀掉旧 18000 进程，勿动
> 54998 / 8100 / 3000）。不要依赖"热重载"——此环境没有。

这是 round-3g 用 4 小时才排查出来的坑：02:01/02:16/03:07 的改动对运行中的
进程全部无效，验收时才被迫重启。生产启动路径（`start_backend.bat` /
容器入口）不受影响，本规则只针对这个 dev 脚本。

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

## Public read-only MCP edge (agentization P2)

An OPTIONAL second instance of brand-tools-mcp exposing exactly four read
tools (`search_brand_documents`, `get_product_facts`, `get_brand_guidelines`,
`get_channel_spec`) to external MCP clients. Write and high-risk tools are
not registered in that process — absence is the control, not authorization.

**Start (opt-in profile; the default stack never starts it):**

```powershell
# a) static tokens: create the table first (one '<token> <workspace_id>' per line)
#    e.g. content of .\brand-mcp-public-tokens.txt:
#    sk-public-0123456789abcdef 00000000-0000-0000-0000-000000000001
docker compose --env-file .env.local --profile public-mcp up -d brand-tools-mcp-public

# b) Clerk JWT mode: set BRAND_MCP_PUBLIC_CLERK_JWKS_URL / _ISSUER (and optionally
#    _AUDIENCE / _AUTHORIZED_PARTIES) in .env.local first, create an EMPTY token
#    file only if mixing modes; then start the same way
```

**Health:** `GET :8200/health` reports `auth.static_tokens` / `auth.clerk_jwt`
modes (both may be true). **Fail-closed:** with no credential source configured
the factory refuses to boot.

**Revocation:** static tokens are revoked by editing the table and restarting
the service; JWT credentials are bounded by the Clerk key rotation and session
expiry configured on the Clerk side.

**Exposure:** the published port binds to loopback by default. Expose it to the
internet ONLY behind a TLS reverse proxy; MCP directory listing requires a
public HTTPS URL. Publishing to a directory is a release action — needs the
user's explicit approval per the red-line rules.

**Recovery:** restart the container; it is stateless (credentials from env/
file, data from PostgreSQL). The internal `brand-tools-mcp` (:8100) is
unaffected by anything that happens on this edge.

## Production go-live checklist (UX review N15)

Before pointing any public domain at this stack, walk this list — a dev-keys
deployment is a real risk, not a hypothetical:

1. **Clerk keys**: rotate from `sk_test_/pk_test_` dev keys to PRODUCTION
   keys from a live Clerk instance; dev instances allow self-serve sign-up
   without MFA and are not a deployment credential set.
2. **GLM/gateway key rotation**: the GLM_API_KEY has a documented leak
   history (once committed in plaintext to a public repo). Rotate at the
   provider console BEFORE any public deployment, and verify the old key is
   revoked.
3. **TLS**: every public surface (web, public MCP edge if enabled) serves
   behind HTTPS; the public MCP port is loopback-bound and must stay behind
   a reverse proxy.
4. **Secrets inventory**: `.env.local` values must never appear in CI logs
   or container images; confirm `docker compose config` output shows
   placeholders, not values, when piped.
5. **Backup**: enable a daily `pg_dump` of the brandflow database to a
   mounted volume (creators' manuscripts are user assets; recovery order
   stays: PostgreSQL -> MCP -> Agent -> Web per the Recovery section).
6. **Rollback**: `NEXT_PUBLIC_DEFAULT_ENTRY=brandflow` still switches the
   default entry; the /app consumer surface and /brandflow window must both
   be green before swap.
