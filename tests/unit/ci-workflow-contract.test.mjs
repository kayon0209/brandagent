import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import test from 'node:test'

const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const workflow = readFileSync(path.join(repositoryRoot, '.github', 'workflows', 'ci.yml'), 'utf8')
const manifest = JSON.parse(readFileSync(path.join(repositoryRoot, 'package.json'), 'utf8'))

test('CI uses the production pnpm lockfile with a frozen install', () => {
  assert.ok(existsSync(path.join(repositoryRoot, 'pnpm-lock.yaml')), 'CI and Docker must share the committed pnpm lockfile')
  assert.equal(manifest.packageManager, 'pnpm@11.22.0', 'Corepack, CI, and Docker must use the same pnpm version')
  assert.match(workflow, /corepack enable\s*\n\s*pnpm install --frozen-lockfile/)
})

test('CI runs the complete maintained frontend quality gate', () => {
  assert.match(workflow, /run: \|\s*\n\s*pnpm run test:all\s*\n\s*pnpm run typecheck\s*\n\s*pnpm run lint\s*\n\s*pnpm run build/)
})

test('agent-api CI applies repository migrations rather than an empty service-relative path', () => {
  assert.match(workflow, /glob\.glob\("\.\.\/\.\.\/docs\/migrations\/\*\.sql"\)/)
})

test('agent-api CI runs the disposable PostgreSQL and RLS gates as a non-superuser business role', () => {
  assert.match(workflow, /POSTGRES_HOST_AUTH_METHOD:\s*trust/)
  assert.match(workflow, /RUN_AGENT_DB_TESTS:\s*["']?true/)
  assert.match(workflow, /AGENT_TEST_DATABASE_URL:\s*postgresql:\/\/postgres@localhost:5432\/postgres/)
  assert.match(workflow, /CREATE ROLE brandflow_app LOGIN NOSUPERUSER NOBYPASSRLS/)
  assert.match(workflow, /\.\.\/\.\.\/docs\/deployment\/postgres-grants\.sql/)
  assert.match(workflow, /grants_sql = "\\n"\.join\(line for line in open\(grants_file, encoding="utf-8"\) if not line\.lstrip\(\)\.startswith\("\\\\"\)\)/)
  assert.doesNotMatch(workflow, /conn\.execute\(open\(grants_file/)
})
