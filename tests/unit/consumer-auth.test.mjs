import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const read = path => readFile(new URL(`../../${path}`, import.meta.url), 'utf8')

test('brandagent BFF rejects anonymous requests with the public auth envelope', async () => {
  const source = await read('src/app/api/brandagent/[...path]/route.ts')
  assert.match(source, /from '@clerk\/nextjs\/server'/, 'BFF must use Clerk server auth')
  assert.match(source, /await auth\(\)/, 'BFF must resolve the Clerk session server-side')
  assert.match(source, /AUTH_REQUIRED/, 'anonymous requests must get the standard auth envelope')
  assert.match(source, /status: 401/, 'anonymous requests must be rejected with 401')
})

test('brandagent BFF forwards auth, idempotency, event cursor and request id headers', async () => {
  const source = await read('src/app/api/brandagent/[...path]/route.ts')
  for (const header of ['Authorization', 'Idempotency-Key', 'Last-Event-ID', 'X-Request-Id']) {
    assert.ok(
      source.toLowerCase().includes(header.toLowerCase()),
      `BFF must forward the ${header} header`
    )
  }
})

test('agent API internal URL is resolved only on the server side', async () => {
  const source = await read('src/lib/api/server-agent-api.ts')
  assert.match(source, /BRANDFLOW_AGENT_INTERNAL_URL/, 'internal URL must come from env')
  assert.doesNotMatch(source, /NEXT_PUBLIC/, 'internal URL must never use a public env var')
})

test('Next middleware wires Clerk auth for the BFF route', async () => {
  const source = await read('src/middleware.ts')
  assert.match(source, /clerkMiddleware/, 'middleware must install clerkMiddleware')
})

test('/app consumer routes are login-protected in middleware', async () => {
  const source = await read('src/middleware.ts')
  assert.match(source, /auth\.protect/, 'middleware must call auth.protect() for /app')
  assert.match(source, /'\/app\(\.\*\)'/, 'the route matcher must cover all /app pages')
})

test('the browser can no longer reach the agent API through a rewrite bypass', async () => {
  const source = await read('next.config.js')
  assert.doesNotMatch(source, /brandflow-api/, 'the /brandflow-api rewrite must be removed')
  const client = await read('src/lib/api/brandflow.ts')
  assert.match(client, /['"]\/api\/brandagent['"]/, 'client traffic must go through the BFF')
  assert.doesNotMatch(client, /['"]\/brandflow-api['"]/, 'client must not use the removed gateway path')
})

test('useBrandFlow exposes real Clerk auth state instead of hardcoded identity', async () => {
  const source = await read('src/hooks/useBrandFlow.ts')
  assert.match(source, /useAuth/, 'hook must read Clerk auth state')
  assert.doesNotMatch(source, /isSignedIn: true/, 'isSignedIn must not be hardcoded')
  assert.doesNotMatch(source, /hasActiveWorkspace: true/, 'hasActiveWorkspace must not be hardcoded')
  assert.doesNotMatch(source, /organizationRole: '.*' as const/, 'organizationRole must not be hardcoded')
})

test('agent API derives a stable personal workspace for organization-less tokens', async () => {
  const source = await read('services/agent-api/src/agent_api/api/security.py')
  assert.match(source, /experience/, 'Principal must carry the personal/organization experience')
  assert.match(
    source,
    /brandagent:personal:/,
    'personal workspace id must be derived from the Clerk subject'
  )
  assert.match(
    source,
    /brandflow:clerk-org:/,
    'organization tokens must keep resolving through the existing B2B derivation'
  )
})

test('dev auth is opt-in through BRANDFLOW_AUTH_MODE and production fails closed', async () => {
  const settings = await read('services/agent-api/src/agent_api/config.py')
  assert.match(settings, /auth_mode/, 'Settings must expose the explicit auth mode')
  const bootstrap = await read('services/agent-api/src/agent_api/api/bootstrap.py')
  assert.match(bootstrap, /auth_mode == "dev"/, 'dev auth must be gated on the explicit auth mode')
  assert.doesNotMatch(
    bootstrap,
    /dev_mode=\(settings\.environment/,
    'environment=development must no longer silently enable anonymous auth'
  )
})
