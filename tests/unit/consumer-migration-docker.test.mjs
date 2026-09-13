import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import test from 'node:test'

const enabled = process.env.RUN_BRANDFLOW_DB_TESTS === 'true'
const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const composePath = path.join(repositoryRoot, 'docker-compose.yml')
const dockerignorePath = path.join(repositoryRoot, '.dockerignore')
const migrationPath = path.join(repositoryRoot, 'docs', 'migrations', '003_consumer_experience.sql')
const checkPath = path.join(repositoryRoot, 'tests', 'unit', 'consumer-migration-checks.sql')
const rlsCheckPath = path.join(repositoryRoot, 'tests', 'unit', 'consumer-rls-004-checks.sql')
const rls005CheckPath = path.join(repositoryRoot, 'tests', 'unit', 'consumer-rls-005-checks.sql')
const securityDefinerCheckPath = path.join(repositoryRoot, 'tests', 'unit', 'security-definer-checks.sql')

test('003_consumer_experience.sql exists and stays additive', () => {
  assert.ok(existsSync(migrationPath), 'docs/migrations/003_consumer_experience.sql is missing')
  const source = readFileSync(migrationPath, 'utf8')
  for (const banned of ['DROP', 'RENAME', 'TRUNCATE']) {
    assert.doesNotMatch(
      source.replace(/--[^\n]*/g, ''),
      new RegExp(`\\b${banned}\\b`, 'i'),
      `the consumer migration must never contain ${banned}`
    )
  }
})

test('fresh Compose initialization applies every numbered migration before grants', () => {
  const compose = readFileSync(composePath, 'utf8')
  const mounts = [
    '001_init.sql:/docker-entrypoint-initdb.d/02-legacy.sql',
    '002_brandflow_v2_foundation.sql:/docker-entrypoint-initdb.d/03-brandflow.sql',
    '003_consumer_experience.sql:/docker-entrypoint-initdb.d/04-consumer.sql',
    '004_consumer_rls.sql:/docker-entrypoint-initdb.d/05-consumer-rls.sql',
    '005_consumer_rls_hardening.sql:/docker-entrypoint-initdb.d/06-consumer-rls-force.sql',
    '006_style_reports.sql:/docker-entrypoint-initdb.d/07-style-reports.sql',
    '007_style_report_enrichment.sql:/docker-entrypoint-initdb.d/08-style-report-enrichment.sql',
    '008_consumer_material_kinds.sql:/docker-entrypoint-initdb.d/09-consumer-material-kinds.sql',
    '009_deep_research.sql:/docker-entrypoint-initdb.d/10-deep-research.sql',
    '010_deep_research_orphan_recovery.sql:/docker-entrypoint-initdb.d/11-orphan-recovery.sql',
    '011_harden_increment_token_used.sql:/docker-entrypoint-initdb.d/12-harden-token-rpc.sql',
    'postgres-grants.sql:/docker-entrypoint-initdb.d/13-grants.sql',
  ]
  let previous = -1
  for (const mount of mounts) {
    const position = compose.indexOf(mount)
    assert.ok(position > previous, `expected Compose initialization mount in order: ${mount}`)
    previous = position
  }
})

test('Docker context excludes retained local backups and sensitive scratch artifacts', () => {
  const dockerignore = readFileSync(dockerignorePath, 'utf8')
  for (const pattern of [
    '.next.*-bak.*',
    '.next.*-bak.*/',
    '.tmp_research',
    'docs/resume-brandagent-ai-pm.md',
    '.clerk-ticket*.tmp',
  ]) {
    assert.match(dockerignore, new RegExp(`^${pattern.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}$`, 'm'))
  }
})

function docker(args, options = {}) {
  return execFileSync('docker', args, {
    cwd: repositoryRoot,
    encoding: 'utf8',
    stdio: options.capture ? 'pipe' : 'inherit',
  })
}

test('fresh PostgreSQL applies legacy, BrandFlow and consumer migrations with checks', { skip: !enabled }, () => {
  const container = `brandconsumer-${randomUUID().slice(0, 8)}`
  const migrationsDir = path.join(repositoryRoot, 'docs', 'migrations')

  docker([
    'run', '--rm', '--name', container, '-d',
    '-e', 'POSTGRES_HOST_AUTH_METHOD=trust',
    '-v', `${migrationsDir}:/migrations:ro`,
    'postgres:16-alpine',
  ])

  try {
    docker([
      'exec', container, 'sh', '-c',
      // postgres:alpine briefly accepts connections during initdb's temporary
      // server, then restarts as PID 1. Waiting one extra second prevents the
      // role bootstrap from landing in that short-lived cluster.
      'attempt=0; until pg_isready -U postgres; do attempt=$((attempt+1)); [ "$attempt" -ge 30 ] && exit 1; sleep 0.5; done; sleep 1; psql -v ON_ERROR_STOP=1 -U postgres -c "SELECT 1" >/dev/null',
    ])

    // 010 grants recovery functions to brandflow_app and explicitly revokes
    // them from brandflow_checkpoint. Production Compose creates both roles
    // before migrations; this disposable gate must model that order too.
    docker([
      'exec', container, 'psql', '-v', 'ON_ERROR_STOP=1', '-U', 'postgres', '-c',
      'CREATE ROLE brandflow_app LOGIN NOSUPERUSER NOBYPASSRLS; CREATE ROLE brandflow_checkpoint LOGIN NOSUPERUSER NOBYPASSRLS; CREATE SCHEMA brandflow_checkpoint AUTHORIZATION brandflow_checkpoint; ALTER ROLE brandflow_checkpoint IN DATABASE postgres SET search_path TO brandflow_checkpoint;',
    ])

    // P1-5 acceptance: the gate applies EVERY consumer migration — 004 RLS
    // and the user-authorized 005 FORCE hardening included. A migration
    // file that exists but is never applied by the gate is not a gate.
    for (const file of [
      '001_init.sql',
      '002_brandflow_v2_foundation.sql',
      '003_consumer_experience.sql',
      '004_consumer_rls.sql',
      '005_consumer_rls_hardening.sql',
      '006_style_reports.sql',
      '007_style_report_enrichment.sql',
      '008_consumer_material_kinds.sql',
      '009_deep_research.sql',
      '010_deep_research_orphan_recovery.sql',
      '011_harden_increment_token_used.sql',
    ]) {
      docker(['exec', container, 'psql', '-v', 'ON_ERROR_STOP=1', '-U', 'postgres', '-f', `/migrations/${file}`])
    }
    docker(['cp', checkPath, `${container}:/tmp/consumer-migration-checks.sql`])
    docker(['exec', container, 'psql', '-v', 'ON_ERROR_STOP=1', '-U', 'postgres', '-f', '/tmp/consumer-migration-checks.sql'])
    // 004 verification: all seven consumer tables have RLS enabled and the
    // fail-closed workspace policy, asserted on the disposable container
    docker(['cp', rlsCheckPath, `${container}:/tmp/consumer-rls-004-checks.sql`])
    docker(['exec', container, 'psql', '-v', 'ON_ERROR_STOP=1', '-U', 'postgres', '-f', '/tmp/consumer-rls-004-checks.sql'])
    // 005 verification: RLS is also FORCED — the owner bypass is closed
    docker(['cp', rls005CheckPath, `${container}:/tmp/consumer-rls-005-checks.sql`])
    docker(['exec', container, 'psql', '-v', 'ON_ERROR_STOP=1', '-U', 'postgres', '-f', '/tmp/consumer-rls-005-checks.sql'])
    // 011 verification: the legacy SECURITY DEFINER token RPC is safe for
    // the isolated checkpoint role to coexist with.
    docker(['cp', securityDefinerCheckPath, `${container}:/tmp/security-definer-checks.sql`])
    docker(['exec', container, 'psql', '-v', 'ON_ERROR_STOP=1', '-U', 'postgres', '-f', '/tmp/security-definer-checks.sql'])
  } finally {
    try {
      docker(['stop', container], { capture: true })
    } catch {
      // The daemon may already have removed the disposable container.
    }
  }
})
